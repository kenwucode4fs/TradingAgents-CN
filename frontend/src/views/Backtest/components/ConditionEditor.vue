<template>
  <div class="condition-editor">
    <div class="condition-editor-header">
      <span class="condition-editor-title">{{ title }}</span>
      <el-radio-group v-model="logic" size="small" @change="handleChange">
        <el-radio-button label="AND">且 (AND)</el-radio-button>
        <el-radio-button label="OR">或 (OR)</el-radio-button>
      </el-radio-group>
    </div>

    <div v-if="localRules.length === 0" class="condition-editor-empty">
      <el-empty description="暂无条件，点击下方按钮添加" :image-size="60" />
    </div>

    <div v-else class="condition-editor-rows">
      <div v-for="(rule, index) in localRules" :key="index" class="condition-row">
        <el-select
          v-model="rule.left"
          placeholder="指标"
          class="condition-select"
          @change="handleChange"
        >
          <el-option
            v-for="opt in INDICATOR_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>

        <el-select
          v-model="rule.op"
          placeholder="比较符"
          class="condition-select condition-select-op"
          @change="handleOpChange(rule)"
        >
          <el-option
            v-for="opt in OPERATOR_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>

        <el-radio-group
          v-model="rule.valueType"
          size="small"
          class="condition-value-type"
          @change="handleValueTypeChange(rule)"
        >
          <el-radio-button label="value" :disabled="isCrossOp(rule.op)">数值</el-radio-button>
          <el-radio-button label="indicator">指标</el-radio-button>
        </el-radio-group>

        <el-input-number
          v-if="rule.valueType === 'value'"
          v-model="rule.right"
          :controls="false"
          class="condition-select"
          @change="handleChange"
        />
        <el-select
          v-else
          v-model="rule.right"
          placeholder="指标"
          class="condition-select"
          @change="handleChange"
        >
          <el-option
            v-for="opt in INDICATOR_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>

        <el-button
          :icon="Delete"
          circle
          size="small"
          class="condition-row-delete"
          @click="removeRule(index)"
        />
      </div>
    </div>

    <div class="condition-editor-footer">
      <el-button :icon="Plus" size="small" @click="addRule">添加条件</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'

type OperatorType = '>' | '<' | 'cross_up' | 'cross_down'
type ValueType = 'value' | 'indicator'

interface ConditionRule {
  left: string
  op: OperatorType
  right: string | number
}

interface ConditionGroup {
  rules: ConditionRule[]
  logic: 'AND' | 'OR'
}

// 内部使用的规则行：多带一个 valueType 字段用于控制右值输入形式，不参与对外序列化
interface LocalRule {
  left: string
  op: OperatorType
  right: string | number
  valueType: ValueType
}

interface Props {
  modelValue: ConditionGroup
  title: string
}

interface Emits {
  (e: 'update:modelValue', value: ConditionGroup): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 指标选项常量：value 为后端约定的英文标识，label 为中文展示
const INDICATOR_OPTIONS = [
  { label: 'MA5', value: 'ma5' },
  { label: 'MA10', value: 'ma10' },
  { label: 'MA20', value: 'ma20' },
  { label: 'MA60', value: 'ma60' },
  { label: 'EMA12', value: 'ema12' },
  { label: 'EMA26', value: 'ema26' },
  { label: 'MACD DIF', value: 'macd_dif' },
  { label: 'MACD DEA', value: 'macd_dea' },
  { label: 'MACD 柱', value: 'macd_bar' },
  { label: 'RSI6', value: 'rsi6' },
  { label: 'RSI12', value: 'rsi12' },
  { label: 'RSI14', value: 'rsi14' },
  { label: 'BOLL 上轨', value: 'boll_up' },
  { label: 'BOLL 中轨', value: 'boll_mid' },
  { label: 'BOLL 下轨', value: 'boll_low' },
  { label: '收盘价', value: 'close' }
] as const

const OPERATOR_OPTIONS: Array<{ label: string; value: OperatorType }> = [
  { label: '>', value: '>' },
  { label: '<', value: '<' },
  { label: '上穿(金叉)', value: 'cross_up' },
  { label: '下穿(死叉)', value: 'cross_down' }
]

const DEFAULT_INDICATOR = INDICATOR_OPTIONS[0].value
// cross_up/cross_down 要求右值必须是指标序列，切到 cross 时用它作为重置默认值
const DEFAULT_CROSS_INDICATOR = 'ma20'

// cross_up/cross_down 两侧都必须是指标序列，引擎不支持右值为数值
function isCrossOp(op: OperatorType): boolean {
  return op === 'cross_up' || op === 'cross_down'
}

// 生成一条默认空规则
function createDefaultRule(): LocalRule {
  return {
    left: DEFAULT_INDICATOR,
    op: '>',
    right: 0,
    valueType: 'value'
  }
}

// 根据外部传入的 right 推断值类型：number 视为常数值，否则视为指标
function inferValueType(right: string | number): ValueType {
  return typeof right === 'number' ? 'value' : 'indicator'
}

function toLocalRule(rule: ConditionRule): LocalRule {
  return {
    left: rule.left,
    op: rule.op,
    right: rule.right,
    valueType: inferValueType(rule.right)
  }
}

function toConditionGroup(): ConditionGroup {
  return {
    logic: logic.value,
    rules: localRules.map((rule) => ({
      left: rule.left,
      op: rule.op,
      right: rule.right
    }))
  }
}

const logic = ref<'AND' | 'OR'>(props.modelValue?.logic || 'AND')
const localRules = reactive<LocalRule[]>(
  (props.modelValue?.rules || []).map(toLocalRule)
)

// 用于防止 emit -> 父组件更新 modelValue -> 本地 watch 再次同步 -> 死循环
// 记录上一次向外 emit 的序列化内容，watch 中若与之相同则说明是自身触发的回声，直接跳过
let lastEmittedSnapshot = JSON.stringify(toConditionGroup())

function emitUpdate() {
  const payload = toConditionGroup()
  lastEmittedSnapshot = JSON.stringify(payload)
  emit('update:modelValue', payload)
}

function handleChange() {
  emitUpdate()
}

function handleValueTypeChange(rule: LocalRule) {
  // 切换值类型时重置右值为该类型下的合理默认值
  rule.right = rule.valueType === 'value' ? 0 : DEFAULT_INDICATOR
  emitUpdate()
}

function handleOpChange(rule: LocalRule) {
  // cross_up/cross_down 要求右值必须是指标，若之前是数值类型则强制切回指标并重置为合法默认值
  if (isCrossOp(rule.op) && rule.valueType === 'value') {
    rule.valueType = 'indicator'
    rule.right = DEFAULT_CROSS_INDICATOR
  }
  emitUpdate()
}

function addRule() {
  localRules.push(createDefaultRule())
  emitUpdate()
}

function removeRule(index: number) {
  localRules.splice(index, 1)
  emitUpdate()
}

watch(
  () => props.modelValue,
  (newValue) => {
    const snapshot = JSON.stringify(newValue)
    if (snapshot === lastEmittedSnapshot) {
      // 这是本组件自身 emit 引起的父级更新回声，忽略以避免死循环
      return
    }
    lastEmittedSnapshot = snapshot

    logic.value = newValue?.logic || 'AND'
    const newRules = (newValue?.rules || []).map(toLocalRule)
    localRules.splice(0, localRules.length, ...newRules)
  },
  { deep: true }
)
</script>

<style scoped lang="scss">
.condition-editor {
  width: 100%;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  padding: 12px;
}

.condition-editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.condition-editor-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.condition-editor-empty {
  padding: 8px 0;
}

.condition-editor-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.condition-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.condition-select {
  width: 130px;
}

.condition-select-op {
  width: 140px;
}

.condition-value-type {
  flex-shrink: 0;
}

.condition-row-delete {
  flex-shrink: 0;
}

.condition-editor-footer {
  margin-top: 12px;
}
</style>
