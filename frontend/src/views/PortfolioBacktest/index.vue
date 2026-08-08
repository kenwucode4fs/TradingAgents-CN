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

    <el-card class="placeholder-card" shadow="never">
      <el-empty description="组合回测功能开发中，敬请期待" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { PieChart } from '@element-plus/icons-vue'
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

  .placeholder-card {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 320px;
  }
}
</style>
