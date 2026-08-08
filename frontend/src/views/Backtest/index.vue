<template>
  <div class="backtest">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Histogram /></el-icon>
        策略回测
      </h1>
      <p class="page-description">
        配置策略参数并运行历史回测，查看净值曲线、绩效指标与逐笔交易明细
      </p>
    </div>

    <!-- 回测参数配置 -->
    <el-card class="config-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>回测参数</span>
        </div>
      </template>

      <el-form label-width="110px" class="backtest-form">
        <!-- 股票与区间 -->
        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="股票代码" required>
              <el-input
                v-model="stockCode"
                placeholder="输入6位A股代码，如 000001"
                maxlength="6"
                clearable
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
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
        </el-row>

        <!-- 资金与成本 -->
        <el-row :gutter="16">
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
          <el-col :span="6">
            <el-form-item label="佣金率">
              <el-input-number
                v-model="cost.commission_rate"
                :min="0"
                :step="0.00005"
                :precision="5"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="最低佣金">
              <el-input-number
                v-model="cost.min_commission"
                :min="0"
                :step="1"
                :precision="2"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="印花税率">
              <el-input-number
                v-model="cost.stamp_tax_rate"
                :min="0"
                :step="0.0001"
                :precision="4"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 持仓与过户费 -->
        <el-row :gutter="16">
          <el-col :span="6">
            <el-form-item label="过户费率">
              <el-input-number
                v-model="cost.transfer_fee_rate"
                :min="0"
                :step="0.00001"
                :precision="5"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="分仓数">
              <el-input-number
                v-model="position.parts"
                :min="1"
                :max="10"
                :step="1"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="减仓模式">
              <el-select v-model="position.reduce_mode" style="width: 100%">
                <el-option label="逐次减仓" value="reduce_one" />
                <el-option label="一次清仓" value="clear_all" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 买入/卖出条件 -->
        <el-row :gutter="16" class="condition-row">
          <el-col :span="12">
            <ConditionEditor v-model="buyGroup" title="买入条件" />
          </el-col>
          <el-col :span="12">
            <ConditionEditor v-model="sellGroup" title="卖出条件" />
          </el-col>
        </el-row>

        <!-- 提交 -->
        <div class="submit-row">
          <el-button
            type="primary"
            size="large"
            :icon="VideoPlay"
            :loading="submitting"
            :disabled="polling"
            @click="submitBacktest"
          >
            {{ polling ? '回测运行中...' : '开始回测' }}
          </el-button>
        </div>

        <el-alert
          v-if="polling"
          type="info"
          :closable="false"
          show-icon
          class="progress-alert"
        >
          <template #title>
            <el-icon class="rotating-icon"><Loading /></el-icon>
            回测运行中，已用时 {{ elapsedSeconds }} 秒，请耐心等待...
          </template>
        </el-alert>
      </el-form>
    </el-card>

    <!-- 回测结果 -->
    <el-card v-if="result" class="result-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>回测结果 - {{ result.symbol || stockCode || '' }}</span>
        </div>
      </template>

      <MetricsCards :metrics="result.metrics" />
      <EquityChart
        class="result-block"
        :equity-curve="result.equity_curve"
        :benchmark-curve="result.benchmark_curve"
      />
      <TradesTable class="result-block" :trades="result.trades" />
    </el-card>

    <!-- 历史回测记录 -->
    <el-card class="history-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>历史回测记录</span>
          <el-button text :icon="Refresh" :loading="historyLoading" @click="loadHistory">
            刷新
          </el-button>
        </div>
      </template>

      <el-table v-loading="historyLoading" :data="historyList" style="width: 100%">
        <el-table-column prop="symbol" label="股票代码" width="120" />
        <el-table-column label="回测区间" min-width="200">
          <template #default="{ row }">
            {{ row.config?.start_date || '-' }} ~ {{ row.config?.end_date || '-' }}
          </template>
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
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" text @click="viewHistory(row)">查看</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无历史回测记录" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { Histogram, VideoPlay, Loading, Refresh } from '@element-plus/icons-vue'
import { backtestApi } from '@/api/backtest'
import ConditionEditor from './components/ConditionEditor.vue'
import EquityChart from './components/EquityChart.vue'
import MetricsCards from './components/MetricsCards.vue'
import TradesTable from './components/TradesTable.vue'

// ConditionEditor v-model 契约：{rules:[{left,op,right}], logic:'AND'|'OR'}
interface ConditionRule {
  left: string
  op: '>' | '<' | 'cross_up' | 'cross_down'
  right: string | number
}
interface ConditionGroup {
  rules: ConditionRule[]
  logic: 'AND' | 'OR'
}

// 回测结果：result(task_id) 返回的字段均为下划线命名，展示组件用驼峰 props，
// 绑定时需显式映射（见模板 EquityChart 的 :equity-curve/:benchmark-curve）
interface BacktestResult {
  task_id?: string
  symbol?: string
  config?: Record<string, any>
  equity_curve?: [string, number][]
  benchmark_curve?: [string, number][]
  metrics?: Record<string, number | null>
  trades?: any[]
  [key: string]: any
}

const route = useRoute()

// ------- 表单状态 -------
// 第一版仅 A 股单股，直接输入 6 位代码；提交时后端回测自带数据存在性校验
const stockCode = ref('')
const dateRange = ref<[string, string]>([
  dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
  dayjs().format('YYYY-MM-DD')
])
const initialCapital = ref(100000)
const cost = reactive({
  commission_rate: 0.00025,
  min_commission: 5,
  stamp_tax_rate: 0.001,
  transfer_fee_rate: 0.00001
})
const position = reactive<{ parts: number; reduce_mode: 'reduce_one' | 'clear_all' }>({
  parts: 3,
  reduce_mode: 'reduce_one'
})
const buyGroup = ref<ConditionGroup>({ rules: [], logic: 'AND' })
const sellGroup = ref<ConditionGroup>({ rules: [], logic: 'OR' })

function disabledDate(time: Date) {
  return time.getTime() > Date.now()
}

// ------- 提交与轮询 -------
const submitting = ref(false)
const polling = ref(false)
const elapsedSeconds = ref(0)
const taskId = ref('')
const result = ref<BacktestResult | null>(null)

let pollTimer: ReturnType<typeof setInterval> | null = null
let elapsedTimer: ReturnType<typeof setInterval> | null = null
let pollStartTime = 0

const POLL_INTERVAL = 1500
const POLL_TIMEOUT = 5 * 60 * 1000 // 5分钟超时

function validateForm(): boolean {
  if (!/^\d{6}$/.test(stockCode.value.trim())) {
    ElMessage.warning('请输入6位A股代码，如 000001')
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
  if (!initialCapital.value || initialCapital.value <= 0) {
    ElMessage.warning('初始资金需大于0')
    return false
  }
  return true
}

function buildPayload() {
  return {
    symbol: stockCode.value.trim(),
    start_date: dateRange.value[0],
    end_date: dateRange.value[1],
    initial_capital: initialCapital.value,
    cost: { ...cost },
    position: { ...position },
    buy_rules: buyGroup.value.rules,
    buy_logic: buyGroup.value.logic,
    sell_rules: sellGroup.value.rules,
    sell_logic: sellGroup.value.logic
  }
}

async function submitBacktest() {
  if (!validateForm()) return

  submitting.value = true
  result.value = null
  try {
    const payload = buildPayload()
    const res = await backtestApi.run(payload)
    const id = res.data?.task_id
    if (!id) {
      ElMessage.error('未获取到任务ID，请重试')
      return
    }
    taskId.value = id
    ElMessage.success('回测任务已提交，正在运行...')
    startPolling(id)
  } catch (error: any) {
    ElMessage.error(error?.message || '提交回测失败')
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
      ElMessage.error('回测超时，请稍后在历史记录中查看结果')
      return
    }

    try {
      const res = await backtestApi.status(id)
      const status = res.data?.status
      if (status === 'done') {
        stopPolling()
        await loadResult(id)
        ElMessage.success('回测完成')
        loadHistory()
      } else if (status === 'failed') {
        stopPolling()
        ElMessage.error(res.data?.error || '回测失败')
      }
      // status === 'running'：继续轮询
    } catch (error: any) {
      // 单次轮询请求失败不中断整体轮询，静默重试
      console.error('查询回测状态失败:', error)
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
    const res = await backtestApi.result(id)
    result.value = res.data
  } catch (error: any) {
    ElMessage.error(error?.message || '获取回测结果失败')
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
    const res = await backtestApi.history()
    historyList.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    ElMessage.error(error?.message || '获取历史回测记录失败')
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
  // 从多因子选股榜单跳转过来时，query.symbol 带入股票代码，自动填入表单
  const symbol = route.query.symbol
  if (symbol) {
    stockCode.value = String(symbol)
  }
  loadHistory()
})
</script>

<style lang="scss" scoped>
.backtest {
  .page-header {
    margin-bottom: 20px;

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 24px;
      font-weight: 600;
      margin: 0 0 8px 0;
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

  .selected-stock {
    display: flex;
    align-items: center;
    min-height: 32px;
  }

  .condition-row {
    margin-top: 8px;
    margin-bottom: 8px;
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
