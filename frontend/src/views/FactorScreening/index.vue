<template>
  <div class="factor-screening">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Filter /></el-icon>
        多因子选股
      </h1>
      <p class="page-description">
        基于多因子打分模型对股票进行综合评分与筛选
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

    <!-- 选股域配置 -->
    <el-card class="config-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>选股域</span>
        </div>
      </template>

      <el-form label-width="100px" class="universe-form">
        <el-row :gutter="24">
          <el-col :span="6">
            <el-form-item label="剔除ST">
              <el-switch v-model="universe.excludeSt" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="剔除次新">
              <el-switch v-model="universe.excludeNew" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="行业筛选">
              <el-select
                v-model="universe.industries"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="留空表示不限行业，可输入后回车添加"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :span="6">
            <el-form-item label="市值下限">
              <el-input-number
                v-model="universe.mvMin"
                :min="0"
                :controls="false"
                clearable
                placeholder="不限"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="市值上限">
              <el-input-number
                v-model="universe.mvMax"
                :min="0"
                :controls="false"
                clearable
                placeholder="不限"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="Top N">
              <el-input-number v-model="topN" :min="1" :max="500" :step="10" style="width: 100%" />
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
            @click="submitScreen"
          >
            {{ polling ? '选股运行中...' : '开始选股' }}
          </el-button>
        </div>

        <el-alert v-if="polling" type="info" :closable="false" show-icon class="progress-alert">
          <template #title>
            <el-icon class="rotating-icon"><Loading /></el-icon>
            选股运行中，已用时 {{ elapsedSeconds }} 秒，请耐心等待...
          </template>
        </el-alert>
      </el-form>
    </el-card>

    <!-- 选股结果 -->
    <el-card v-if="resultItems.length" class="result-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>选股结果（共 {{ resultItems.length }} 只）</span>
        </div>
      </template>

      <ResultTable
        :items="resultItems"
        :selected-factor-keys="selectedFactorKeys"
        @backtest="onBacktest"
      />
    </el-card>

    <!-- 历史选股记录 -->
    <el-card class="history-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>历史选股记录</span>
          <el-button text :icon="Refresh" :loading="historyLoading" @click="loadHistory">
            刷新
          </el-button>
        </div>
      </template>

      <el-table v-loading="historyLoading" :data="historyList" style="width: 100%">
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="因子数" width="100" align="center">
          <template #default="{ row }">{{ row.config?.factors?.length ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="Top N" width="100" align="center">
          <template #default="{ row }">{{ row.config?.top_n ?? '-' }}</template>
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
          <el-empty description="暂无历史选股记录" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { Filter, VideoPlay, Loading, Refresh } from '@element-plus/icons-vue'
import {
  factorApi,
  type FactorConfigItem,
  type FactorUniverse,
  type FactorScreenRunRequest
} from '@/api/factorScreening'
import FactorConfig from './components/FactorConfig.vue'
import ResultTable, { type ResultRow } from './components/ResultTable.vue'

type Direction = 'asc' | 'desc'

// 因子元信息（/factors 接口返回）
interface FactorMeta {
  key: string
  name: string
  category: string
  default_direction: Direction
}

const router = useRouter()

// ------- 因子配置 -------
const factorsMeta = ref<FactorMeta[]>([])
const factorConfig = ref<FactorConfigItem[]>([])

// ------- 选股域配置 -------
const universe = reactive<{
  excludeSt: boolean
  excludeNew: boolean
  industries: string[]
  mvMin: number | null | undefined
  mvMax: number | null | undefined
}>({
  excludeSt: false,
  excludeNew: false,
  industries: [],
  mvMin: null,
  mvMax: null
})
const topN = ref(50)

async function loadFactorsMeta() {
  try {
    const res = await factorApi.factors()
    factorsMeta.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    ElMessage.error(error?.message || '获取因子列表失败')
  }
}

function validateForm(): boolean {
  if (!factorConfig.value.length) {
    ElMessage.warning('请至少选择一个因子')
    return false
  }
  if (!topN.value || topN.value <= 0) {
    ElMessage.warning('Top N 需大于0')
    return false
  }
  return true
}

function buildPayload(): FactorScreenRunRequest {
  const universePayload: FactorUniverse = {
    exclude_st: universe.excludeSt,
    exclude_new: universe.excludeNew,
    industries: universe.industries
  }
  if (universe.mvMin !== null && universe.mvMin !== undefined) {
    universePayload.mv_min = universe.mvMin
  }
  if (universe.mvMax !== null && universe.mvMax !== undefined) {
    universePayload.mv_max = universe.mvMax
  }

  return {
    factors: factorConfig.value.map((f) => ({ key: f.key, weight: f.weight, direction: f.direction })),
    universe: universePayload,
    top_n: topN.value
  }
}

// ------- 提交与轮询 -------
const submitting = ref(false)
const polling = ref(false)
const elapsedSeconds = ref(0)
const taskId = ref('')

// 结果榜单：selectedFactorKeys 记录本次展示结果所使用的因子 key 列表，
// 需与 resultItems 每行 factors 的 key 保持一致（提交选股时来自 payload.factors，
// 历史回看时来自该条记录 config.factors）
const resultItems = ref<ResultRow[]>([])
const selectedFactorKeys = ref<string[]>([])

let pollTimer: ReturnType<typeof setInterval> | null = null
let elapsedTimer: ReturnType<typeof setInterval> | null = null
let pollStartTime = 0

const POLL_INTERVAL = 1500
const POLL_TIMEOUT = 5 * 60 * 1000 // 5分钟超时

async function submitScreen() {
  if (!validateForm()) return

  submitting.value = true
  resultItems.value = []
  try {
    const payload = buildPayload()
    const res = await factorApi.run(payload)
    const id = res.data?.task_id
    if (!id) {
      ElMessage.error('未获取到任务ID，请重试')
      return
    }
    taskId.value = id
    // 提交时的因子 key 列表，用于结果展示，与 payload.factors 保持一致
    selectedFactorKeys.value = payload.factors.map((f) => f.key)
    ElMessage.success('选股任务已提交，正在运行...')
    startPolling(id)
  } catch (error: any) {
    ElMessage.error(error?.message || '提交选股失败')
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
      ElMessage.error('选股超时，请稍后在历史记录中查看结果')
      return
    }

    try {
      const res = await factorApi.status(id)
      const status = res.data?.status
      if (status === 'done') {
        stopPolling()
        await loadResult(id)
        ElMessage.success('选股完成')
        loadHistory()
      } else if (status === 'failed') {
        stopPolling()
        ElMessage.error(res.data?.error || '选股失败')
      }
      // status === 'running'：继续轮询
    } catch (error: any) {
      // 单次轮询请求失败不中断整体轮询，静默重试
      console.error('查询选股任务状态失败:', error)
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
    const res = await factorApi.result(id)
    resultItems.value = Array.isArray(res.data?.items) ? res.data.items : []
  } catch (error: any) {
    ElMessage.error(error?.message || '获取选股结果失败')
  }
}

onUnmounted(() => {
  stopPolling()
})

// ------- 单股回测跳转 -------
function onBacktest(code: string) {
  router.push({ path: '/backtest', query: { symbol: code } })
}

// ------- 历史记录 -------
const historyList = ref<any[]>([])
const historyLoading = ref(false)

async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await factorApi.history()
    historyList.value = Array.isArray(res.data) ? res.data : []
  } catch (error: any) {
    ElMessage.error(error?.message || '获取历史选股记录失败')
  } finally {
    historyLoading.value = false
  }
}

async function viewHistory(row: any) {
  try {
    const res = await factorApi.result(row.task_id)
    resultItems.value = Array.isArray(res.data?.items) ? res.data.items : []
    // 历史记录回看：selectedFactorKeys 取该条结果落库时的 config.factors，
    // 而非当前页面正在编辑的 factorConfig，避免与该条历史结果的因子集合不一致
    const configFactors = res.data?.config?.factors
    selectedFactorKeys.value = Array.isArray(configFactors) ? configFactors.map((f: any) => f.key) : []
  } catch (error: any) {
    ElMessage.error(error?.message || '获取选股结果失败')
  }
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
.factor-screening {
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
