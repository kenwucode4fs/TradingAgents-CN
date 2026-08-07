<template>
  <div class="backtest">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Histogram /></el-icon>
        策略回测
      </h1>
      <p class="page-description">
        配置策略参数并运行历史回测
      </p>
    </div>

    <el-card class="placeholder-card" shadow="never">
      <el-empty description="策略回测功能开发中，敬请期待" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { Histogram } from '@element-plus/icons-vue'
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
}
</style>
