<template>
  <div class="metrics-cards">
    <el-row :gutter="16">
      <el-col
        v-for="item in metricItems"
        :key="item.key"
        :xs="12"
        :sm="8"
        :md="6"
        :lg="6"
      >
        <el-card class="metric-card" shadow="never">
          <div class="metric-label">{{ item.label }}</div>
          <div class="metric-value" :class="item.colorClass">{{ item.display }}</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// 回测绩效指标：百分比字段为比率（展示时需 *100 加 %），其余字段原样展示
interface BacktestMetrics {
  total_return?: number | null
  annual_return?: number | null
  max_drawdown?: number | null
  sharpe?: number | null
  win_rate?: number | null
  profit_loss_ratio?: number | null
  trade_count?: number | null
  avg_holding_days?: number | null
  benchmark_return?: number | null
  [key: string]: number | null | undefined
}

interface Props {
  metrics?: BacktestMetrics
}

const props = withDefaults(defineProps<Props>(), {
  metrics: () => ({})
})

function isValidNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

// 百分比字段：比率 * 100 后加 %
function fmtPercent(v: number | null | undefined): string {
  if (!isValidNumber(v)) return '-'
  return `${(v * 100).toFixed(2)}%`
}

// 普通数值字段：保留指定小数位
function fmtNumber(v: number | null | undefined, decimals: number): string {
  if (!isValidNumber(v)) return '-'
  return v.toFixed(decimals)
}

// 整数字段
function fmtInt(v: number | null | undefined): string {
  if (!isValidNumber(v)) return '-'
  return String(Math.round(v))
}

// 涨跌配色（A股习惯：正红负绿），仅用于收益类指标
function returnColorClass(v: number | null | undefined): string {
  if (!isValidNumber(v)) return ''
  if (v > 0) return 'is-up'
  if (v < 0) return 'is-down'
  return ''
}

interface MetricItem {
  key: string
  label: string
  display: string
  colorClass: string
}

const metricItems = computed<MetricItem[]>(() => {
  const m = props.metrics || {}
  return [
    { key: 'total_return', label: '总收益率', display: fmtPercent(m.total_return), colorClass: returnColorClass(m.total_return) },
    { key: 'annual_return', label: '年化收益率', display: fmtPercent(m.annual_return), colorClass: returnColorClass(m.annual_return) },
    { key: 'max_drawdown', label: '最大回撤', display: fmtPercent(m.max_drawdown), colorClass: '' },
    { key: 'sharpe', label: '夏普比率', display: fmtNumber(m.sharpe, 2), colorClass: '' },
    { key: 'win_rate', label: '胜率', display: fmtPercent(m.win_rate), colorClass: '' },
    { key: 'profit_loss_ratio', label: '盈亏比', display: fmtNumber(m.profit_loss_ratio, 2), colorClass: '' },
    { key: 'trade_count', label: '交易次数', display: fmtInt(m.trade_count), colorClass: '' },
    { key: 'avg_holding_days', label: '平均持仓天数', display: fmtNumber(m.avg_holding_days, 1), colorClass: '' },
    { key: 'benchmark_return', label: '基准收益率(买入持有)', display: fmtPercent(m.benchmark_return), colorClass: returnColorClass(m.benchmark_return) }
  ]
})
</script>

<style scoped lang="scss">
.metrics-cards {
  width: 100%;
}

.metric-card {
  margin-bottom: 16px;

  :deep(.el-card__body) {
    padding: 16px;
  }
}

.metric-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}

.metric-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--el-text-color-primary);

  &.is-up {
    color: #ef4444;
  }

  &.is-down {
    color: #16a34a;
  }
}
</style>
