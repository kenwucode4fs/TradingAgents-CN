<template>
  <div class="rebalance-table">
    <el-table :data="rebalances" style="width: 100%" border stripe row-key="date">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="holdings-detail">
            <div v-if="row.holdings && row.holdings.length > 0" class="holdings-tags">
              <el-tag
                v-for="h in row.holdings"
                :key="h.code"
                class="holding-tag"
                type="info"
                effect="plain"
              >
                {{ h.code }} · {{ fmtPercent(h.weight) }}
              </el-tag>
            </div>
            <el-empty v-else description="暂无持仓明细" :image-size="60" />
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="date" label="日期" width="120" />

      <el-table-column label="买入" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ fmtCodes(row.buys) }}</template>
      </el-table-column>

      <el-table-column label="卖出" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ fmtCodes(row.sells) }}</template>
      </el-table-column>

      <el-table-column label="持仓数" width="100" align="right">
        <template #default="{ row }">{{ fmtInt(row.holdings?.length) }}</template>
      </el-table-column>

      <el-table-column label="组合市值" width="140" align="right">
        <template #default="{ row }">{{ fmtNumber(row.portfolio_value, 2) }}</template>
      </el-table-column>

      <template #empty>
        <el-empty description="暂无调仓记录" :image-size="80" />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
// 调仓明细表：每行一个调仓日，展开行可查看当次持仓明细（code + weight）
interface RebalanceOrder {
  code: string
  shares: number
  price: number
  fee: number
}

interface HoldingItem {
  code: string
  weight: number
}

export interface RebalanceItem {
  date: string
  buys: RebalanceOrder[]
  sells: RebalanceOrder[]
  holdings: HoldingItem[]
  portfolio_value: number
}

interface Props {
  rebalances?: RebalanceItem[]
}

withDefaults(defineProps<Props>(), {
  rebalances: () => []
})

function isValidNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

// 买入/卖出仅展示代码列表，逗号连接；数量较多时依赖 show-overflow-tooltip 展示完整内容
function fmtCodes(orders: RebalanceOrder[] | null | undefined): string {
  if (!orders || orders.length === 0) return '-'
  return orders.map((o) => o.code).join(', ')
}

function fmtNumber(v: number | null | undefined, decimals: number): string {
  if (!isValidNumber(v)) return '-'
  return v.toFixed(decimals)
}

function fmtInt(v: number | null | undefined): string {
  if (!isValidNumber(v)) return '-'
  return String(Math.round(v))
}

// 持仓权重为比率，展示时 * 100 加 %
function fmtPercent(v: number | null | undefined): string {
  if (!isValidNumber(v)) return '-'
  return `${(v * 100).toFixed(2)}%`
}
</script>

<style scoped lang="scss">
.rebalance-table {
  width: 100%;
}

.holdings-detail {
  padding: 12px 24px;
}

.holdings-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.holding-tag {
  margin: 0;
}
</style>
