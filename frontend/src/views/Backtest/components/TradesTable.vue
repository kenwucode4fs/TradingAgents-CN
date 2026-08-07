<template>
  <div class="trades-table">
    <el-table :data="trades" style="width: 100%" border stripe>
      <el-table-column prop="date" label="日期" width="120" />
      <el-table-column prop="side" label="方向" width="90">
        <template #default="{ row }">
          <el-tag :type="row.side === 'buy' ? 'primary' : 'warning'" size="small">
            {{ row.side === 'buy' ? '买入' : '卖出' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="price" label="价格" width="100" align="right">
        <template #default="{ row }">{{ fmtNumber(row.price, 2) }}</template>
      </el-table-column>
      <el-table-column prop="shares" label="股数" width="110" align="right">
        <template #default="{ row }">{{ fmtInt(row.shares) }}</template>
      </el-table-column>
      <el-table-column prop="commission" label="佣金" width="100" align="right">
        <template #default="{ row }">{{ fmtNumber(row.commission, 2) }}</template>
      </el-table-column>
      <el-table-column prop="stamp_tax" label="印花税" width="100" align="right">
        <template #default="{ row }">{{ fmtNumber(row.stamp_tax, 2) }}</template>
      </el-table-column>
      <el-table-column prop="transfer_fee" label="过户费" width="100" align="right">
        <template #default="{ row }">{{ fmtNumber(row.transfer_fee, 2) }}</template>
      </el-table-column>
      <el-table-column prop="pnl" label="盈亏" width="110" align="right">
        <template #default="{ row }">
          <span :class="pnlClass(row)">{{ fmtPnl(row) }}</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
// 单笔交易明细：side 为 buy/sell，pnl 买入笔恒为 null，仅卖出笔有数值
interface Trade {
  date: string
  side: 'buy' | 'sell'
  price: number
  shares: number
  commission: number
  stamp_tax: number
  transfer_fee: number
  pnl: number | null
}

interface Props {
  trades?: Trade[]
}

withDefaults(defineProps<Props>(), {
  trades: () => []
})

function isValidNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

function fmtNumber(v: number | null | undefined, decimals: number): string {
  if (!isValidNumber(v)) return '-'
  return v.toFixed(decimals)
}

function fmtInt(v: number | null | undefined): string {
  if (!isValidNumber(v)) return '-'
  return String(Math.round(v))
}

// 买入笔 pnl 恒为 null，展示为 "-"；卖出笔展示带正负号的盈亏金额
function fmtPnl(row: Trade): string {
  if (row.side === 'buy' || !isValidNumber(row.pnl)) return '-'
  const v = row.pnl as number
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}`
}

// A股习惯：盈利（正）显示红色，亏损（负）显示绿色；买入行不上色
function pnlClass(row: Trade): string {
  if (row.side === 'buy' || !isValidNumber(row.pnl)) return ''
  const v = row.pnl as number
  if (v > 0) return 'is-up'
  if (v < 0) return 'is-down'
  return ''
}
</script>

<style scoped lang="scss">
.trades-table {
  width: 100%;
}

.is-up {
  color: #ef4444;
}

.is-down {
  color: #16a34a;
}
</style>
