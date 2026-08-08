<template>
  <div class="portfolio-backtest">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><PieChart /></el-icon>
        组合回测
      </h1>
      <p class="page-description">
        基于多因子选股结果构建投资组合并进行历史回测
      </p>
    </div>

    <!-- 因子配置 -->
    <el-card class="config-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>因子配置</span>
        </div>
      </template>

      <FactorConfig v-model="factorConfig" :factors-meta="factorsMeta" />
    </el-card>

    <!-- 回测参数 -->
    <el-card class="config-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>回测参数</span>
        </div>
      </template>

      <el-form label-width="100px" class="params-form">
        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="回测区间" required>
              <el-date-picker
                v-model="dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                :disabled-date="disabledDate"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="Top N">
              <el-input-number v-model="topN" :min="1" :max="500" :step="10" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="初始资金">
              <el-input-number
                v-model="initialCapital"
                :min="1000"
                :step="10000"
                :precision="0"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <div class="submit-row">
          <el-button
            type="primary"
            size="large"
            :icon="VideoPlay"
            :loading="submitting"
            :disabled="polling"
            @click="submitBacktest"
          >
            {{ polling ? '组合回测运行中...' : '开始回测' }}
          </el-button>
        </div>

        <el-alert v-if="polling" type="info" :closable="false" show-icon class="progress-alert">
          <template #title>
            <el-icon class="rotating-icon"><Loading /></el-icon>
            组合回测需遍历全市场候选股逐月调仓，通常需要 10 分钟以上，已用时 {{ elapsedSeconds }} 秒，请耐心等待，勿关闭页面...
          </template>
        </el-alert>
      </el-form>
    </el-card>

    <!-- 回测结果 -->
    <el-card v-if="result" class="result-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>回测结果</span>
        </div>
      </template>

      <PortfolioMetrics :metrics="result.metrics" />
      <EquityVsBenchmark
        class="result-block"
        :equity-curve="result.equity_curve"
        :benchmark-curve="result.benchmark_curve"
      />
      <RebalanceTable class="result-block" :rebalances="result.rebalances" />
    </el-card>

    <!-- 历史组合回测记录 -->
    <el-card class="history-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>历史组合回测记录</span>
          <el-button text :icon="Refresh" :loading="historyLoading" @click="loadHistory">
            刷新
          </el-button>
        </div>
      </template>

      <el-table v-loading="historyLoading" :data="historyList" style="width: 100%">
        <el-table-column label="回测区间" min-width="200">
          <template #default="{ row }">
            {{ row.config?.start_date || '-' }} ~ {{ row.config?.end_date || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="因子数" width="100" align="center">
          <template #default="{ row }">{{ row.config?.factors?.length ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="总收益率" width="120">
          <template #default="{ row }">
            <span :class="returnClass(row.metrics?.total_return)">
              {{ formatReturn(row.metrics?.total_return) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="任务ID" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.task_id }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" text @click="viewHistory(row)">查看</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无历史组合回测记录" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { PieChart, VideoPlay, Loading, Refresh } from '@element-plus/icons-vue'
import { factorApi } from '@/api/factorScreening'
import { portfolioApi, type PortfolioBacktestRunRequest } from '@/api/portfolioBacktest'
import FactorConfig from '@/views/FactorScreening/components/FactorConfig.vue'
import EquityVsBenchmark from './components/EquityVsBenchmark.vue'
import PortfolioMetrics from './components/PortfolioMetrics.vue'
import RebalanceTable from './components/RebalanceTable.vue'

type Direction = 'asc' | 'desc'

// 因子元信息（/factors 接口返回）
interface FactorMeta {
  key: string
  name: string
  category: string
  default_direction: Direction
}

// 因子配置项（FactorConfig v-model 契约）
interface FactorConfigItem {
  key: string
  weight: number
  direction: Direction
}

// 组合回测结果：result(task_id) 返回的字段均为下划线命名，展示组件用驼峰 props，
// 绑定时需显式映射（见模板 EquityVsBenchmark 的 :equity-curve/:benchmark-curve）
interface PortfolioBacktestResult {
  task_id?: string
  config?: Record<string, any>
  equity_curve?: [string, number][]
  benchmark_curve?: [string, number][]
  metrics?: Record<string, number | null>
  rebalances?: any[]
  [key: string]: any
}

// ------- 因子配置 -------
const factorsMeta = ref<FactorMeta[]>([])
const factorConfig = ref<FactorConfigItem[]>([])

async function loadFactorsMeta() {
  try {
    const res = await factorApi.factors()
    factorsMeta.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    ElMessage.error(error?.message || '获取因子列表失败')
  }
}

// ------- 回测参数 -------
const dateRange = ref<[string, string]>([
  dayjs().subtract(2, 'year').format('YYYY-MM-DD'),
  dayjs().format('YYYY-MM-DD')
])
const topN = ref(50)
const initialCapital = ref(1000000)

function disabledDate(time: Date) {
  return time.getTime() > Date.now()
}

function validateForm(): boolean {
  if (!factorConfig.value.length) {
    ElMessage.warning('请至少选择一个因子')
    return false
  }
  if (!dateRange.value || !dateRange.value[0] || !dateRange.value[1]) {
    ElMessage.warning('请选择回测区间')
    return false
  }
  if (dateRange.value[0] >= dateRange.value[1]) {
    ElMessage.warning('开始日期需早于结束日期')
    return false
  }
  if (!topN.value || topN.value <= 0) {
    ElMessage.warning('Top N 需大于0')
    return false
  }
  if (!initialCapital.value || initialCapital.value <= 0) {
    ElMessage.warning('初始资金需大于0')
    return false
  }
  return true
}

function buildPayload(): PortfolioBacktestRunRequest {
  return {
    factors: factorConfig.value.map((f) => ({ key: f.key, weight: f.weight, direction: f.direction })),
    start_date: dateRange.value[0],
    end_date: dateRange.value[1],
    top_n: topN.value,
    initial_capital: initialCapital.value
  }
}

// ------- 提交与轮询 -------
// 组合回测计算耗时较长（容器化冒烟实测：全市场候选+2年区间约13分钟才 done），
// 轮询超时上限需给足余量，避免真实计算尚未完成就被前端提前判定为超时
const submitting = ref(false)
const polling = ref(false)
const elapsedSeconds = ref(0)
const taskId = ref('')
const result = ref<PortfolioBacktestResult | null>(null)

let pollTimer: ReturnType<typeof setInterval> | null = null
let elapsedTimer: ReturnType<typeof setInterval> | null = null
let pollStartTime = 0

const POLL_INTERVAL = 1000
const POLL_TIMEOUT = 20 * 60 * 1000 // 20分钟超时（全市场候选+多年区间实测约13分钟，留足余量）

async function submitBacktest() {
  if (!validateForm()) return

  submitting.value = true
  result.value = null
  try {
    const payload = buildPayload()
    const res = await portfolioApi.run(payload)
    const id = res.data?.task_id
    if (!id) {
      ElMessage.error('未获取到任务ID，请重试')
      return
    }
    taskId.value = id
    ElMessage.success('组合回测任务已提交，正在运行...')
    startPolling(id)
  } catch (error: any) {
    ElMessage.error(error?.message || '提交组合回测失败')
  } finally {
    submitting.value = false
  }
}

function startPolling(id: string) {
  stopPolling()
  polling.value = true
  elapsedSeconds.value = 0
  pollStartTime = Date.now()

  elapsedTimer = setInterval(() => {
    elapsedSeconds.value = Math.floor((Date.now() - pollStartTime) / 1000)
  }, 1000)

  pollTimer = setInterval(async () => {
    if (Date.now() - pollStartTime > POLL_TIMEOUT) {
      stopPolling()
      ElMessage.error('组合回测超时，请稍后在历史记录中查看结果')
      return
    }

    try {
      const res = await portfolioApi.status(id)
      const status = res.data?.status
      if (status === 'done') {
        stopPolling()
        await loadResult(id)
        ElMessage.success('组合回测完成')
        loadHistory()
      } else if (status === 'failed') {
        stopPolling()
        ElMessage.error(res.data?.error || '组合回测失败')
      }
      // status === 'running'：继续轮询
    } catch (error: any) {
      // 单次轮询请求失败不中断整体轮询，静默重试
      console.error('查询组合回测任务状态失败:', error)
    }
  }, POLL_INTERVAL)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
  polling.value = false
}

async function loadResult(id: string) {
  try {
    const res = await portfolioApi.result(id)
    result.value = res.data
  } catch (error: any) {
    ElMessage.error(error?.message || '获取组合回测结果失败')
  }
}

onUnmounted(() => {
  stopPolling()
})

// ------- 历史记录 -------
const historyList = ref<any[]>([])
const historyLoading = ref(false)

async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await portfolioApi.history()
    historyList.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    ElMessage.error(error?.message || '获取历史组合回测记录失败')
  } finally {
    historyLoading.value = false
  }
}

async function viewHistory(row: any) {
  await loadResult(row.task_id)
}

function formatReturn(v: number | null | undefined): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '-'
  return `${(v * 100).toFixed(2)}%`
}

function returnClass(v: number | null | undefined): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return ''
  if (v > 0) return 'is-up'
  if (v < 0) return 'is-down'
  return ''
}

function formatDate(v: string | undefined): string {
  if (!v) return '-'
  return dayjs(v).format('YYYY-MM-DD HH:mm')
}

onMounted(() => {
  loadFactorsMeta()
  loadHistory()
})
</script>

<style lang="scss" scoped>
.portfolio-backtest {
  .page-header {
    margin-bottom: 20px;

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 22px;
      font-weight: 600;
      margin: 0 0 8px;
    }

    .page-description {
      color: var(--el-text-color-secondary);
      margin: 0;
    }
  }

  .config-card,
  .result-card,
  .history-card {
    margin-bottom: 20px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .submit-row {
    display: flex;
    justify-content: center;
    margin-top: 16px;
  }

  .progress-alert {
    margin-top: 16px;

    .rotating-icon {
      margin-right: 4px;
      vertical-align: middle;
      animation: rotating 1.2s linear infinite;
    }
  }

  .result-block {
    margin-top: 16px;
  }

  .is-up {
    color: #ef4444;
  }

  .is-down {
    color: #16a34a;
  }
}

@keyframes rotating {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
