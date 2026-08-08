<template>
  <div class="result-table">
    <el-table :data="items" style="width: 100%" border stripe>
      <el-table-column prop="rank" label="排名" width="80" sortable align="center" />

      <el-table-column prop="code" label="代码" width="100" sortable />

      <el-table-column prop="name" label="名称" width="120" sortable show-overflow-tooltip />

      <el-table-column prop="industry" label="行业" width="120" sortable show-overflow-tooltip />

      <el-table-column prop="score" label="总分" width="100" sortable align="right">
        <template #default="{ row }">{{ fmtScore(row.score) }}</template>
      </el-table-column>

      <el-table-column
        v-for="key in selectedFactorKeys"
        :key="key"
        :label="key"
        min-width="120"
        align="right"
        :sort-method="(a: ResultRow, b: ResultRow) => sortByFactorNorm(a, b, key)"
        sortable
      >
        <template #default="{ row }">
          <el-tooltip :content="`原始值：${fmtValue(row.factors?.[key]?.value)}`" placement="top">
            <span>{{ fmtScore(row.factors?.[key]?.norm) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="120" fixed="right" align="center">
        <template #default="{ row }">
          <el-button type="primary" link :icon="TrendCharts" @click="emit('backtest', row.code)">
            单股回测
          </el-button>
        </template>
      </el-table-column>

      <template #empty>
        <el-empty description="暂无选股结果" :image-size="80" />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { TrendCharts } from '@element-plus/icons-vue'

// 单个因子的打分明细：value 为原始值，norm 为标准化到 [0,1] 的得分，direction 为该因子的打分方向
interface FactorScore {
  value: number | null | undefined
  norm: number | null | undefined
  direction?: 'asc' | 'desc'
}

// 榜单单行：因子选股结果条目，factors 仅包含本次选中的因子
export interface ResultRow {
  code: string
  name: string
  industry: string
  score: number
  rank: number
  factors: Record<string, FactorScore | undefined>
}

interface Props {
  items: ResultRow[]
  selectedFactorKeys: string[]
}

interface Emits {
  (e: 'backtest', code: string): void
}

withDefaults(defineProps<Props>(), {
  items: () => [],
  selectedFactorKeys: () => []
})
const emit = defineEmits<Emits>()

function isValidNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

// 总分/因子标准化得分统一保留 3 位小数展示
function fmtScore(v: number | null | undefined): string {
  if (!isValidNumber(v)) return '-'
  return v.toFixed(3)
}

// tooltip 中展示的因子原始值，不做小数位裁剪，避免掩盖真实数量级
function fmtValue(v: number | null | undefined): string {
  if (!isValidNumber(v)) return '-'
  return String(v)
}

// 动态因子列排序：按该因子的标准化得分 norm 比较，缺失值统一沉底
function sortByFactorNorm(a: ResultRow, b: ResultRow, key: string): number {
  const av = a.factors?.[key]?.norm
  const bv = b.factors?.[key]?.norm
  const aValid = isValidNumber(av)
  const bValid = isValidNumber(bv)
  if (!aValid && !bValid) return 0
  if (!aValid) return -1
  if (!bValid) return 1
  return av - bv
}
</script>

<style scoped lang="scss">
.result-table {
  width: 100%;
}
</style>
