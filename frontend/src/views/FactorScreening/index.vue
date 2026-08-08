<template>
  <div class="factor-screening">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Filter /></el-icon>
        多因子选股
      </h1>
      <p class="page-description">
        基于多因子打分模型对股票进行综合评分与筛选，功能正在建设中
      </p>
    </div>

    <el-card shadow="never">
      <el-empty description="多因子选股功能开发中，敬请期待" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { Filter } from '@element-plus/icons-vue'
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
}
</style>
