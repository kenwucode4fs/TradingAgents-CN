<template>
  <div class="equity-chart">
    <v-chart class="chart" :option="chartOption" autoresize />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { use as echartsUse } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

echartsUse([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

// 曲线点：[日期字符串, 净值]
type CurvePoint = [string, number]

interface Props {
  equityCurve?: CurvePoint[]
  benchmarkCurve?: CurvePoint[]
}

const props = withDefaults(defineProps<Props>(), {
  equityCurve: () => [],
  benchmarkCurve: () => []
})

// x 轴日期：以策略净值曲线为准，若为空则回退到基准曲线
const dates = computed(() => {
  const source = props.equityCurve.length > 0 ? props.equityCurve : props.benchmarkCurve
  return source.map((item) => item[0])
})

const chartOption = computed<EChartsOption>(() => ({
  tooltip: {
    trigger: 'axis'
  },
  legend: {
    data: ['策略净值', '买入持有']
  },
  grid: {
    left: 50,
    right: 20,
    top: 40,
    bottom: 30
  },
  xAxis: {
    type: 'category',
    data: dates.value,
    boundaryGap: false
  },
  yAxis: {
    type: 'value',
    scale: true
  },
  series: [
    {
      name: '策略净值',
      type: 'line',
      data: props.equityCurve.map((item) => item[1]),
      showSymbol: false,
      smooth: true,
      itemStyle: { color: '#ef4444' }
    },
    {
      name: '买入持有',
      type: 'line',
      data: props.benchmarkCurve.map((item) => item[1]),
      showSymbol: false,
      smooth: true,
      itemStyle: { color: '#64748b' }
    }
  ]
}))
</script>

<style scoped lang="scss">
.equity-chart {
  width: 100%;
}

.chart {
  width: 100%;
  height: 360px;
}
</style>
