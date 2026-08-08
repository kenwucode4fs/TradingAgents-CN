<template>
  <div class="factor-config">
    <div v-if="factorsMeta.length === 0" class="factor-config-empty">
      <el-empty description="暂无可用因子" :image-size="60" />
    </div>

    <div v-else class="factor-config-groups">
      <div v-for="group in groupedFactors" :key="group.category" class="factor-config-group">
        <div class="factor-config-group-title">{{ group.category }}</div>

        <div class="factor-config-rows">
          <div v-for="meta in group.items" :key="meta.key" class="factor-config-row">
            <el-checkbox
              v-model="localState[meta.key].enabled"
              class="factor-config-checkbox"
              @change="emitUpdate"
            >
              {{ meta.name }}
            </el-checkbox>

            <template v-if="localState[meta.key].enabled">
              <span class="factor-config-label">权重</span>
              <el-input-number
                v-model="localState[meta.key].weight"
                :min="0.01"
                :precision="2"
                :step="0.1"
                size="small"
                class="factor-config-weight"
                @change="emitUpdate"
              />

              <el-radio-group
                v-model="localState[meta.key].direction"
                size="small"
                class="factor-config-direction"
                @change="emitUpdate"
              >
                <el-radio-button label="desc">越大越好</el-radio-button>
                <el-radio-button label="asc">越小越好</el-radio-button>
              </el-radio-group>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'

type Direction = 'asc' | 'desc'

// 因子元信息（来自 /factors 接口）
interface FactorMeta {
  key: string
  name: string
  category: string
  default_direction: Direction
}

// 对外暴露的单个因子配置（仅已启用因子会出现在数组中）
interface FactorConfigItem {
  key: string
  weight: number
  direction: Direction
}

// 本地维护的因子状态：覆盖 factorsMeta 中全部因子（含未启用项），用于渲染勾选框/权重/方向控件
interface LocalFactorState {
  enabled: boolean
  weight: number
  direction: Direction
}

interface Props {
  modelValue: FactorConfigItem[]
  factorsMeta: FactorMeta[]
}

interface Emits {
  (e: 'update:modelValue', value: FactorConfigItem[]): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const DEFAULT_WEIGHT = 1

// key -> 本地状态；不直接 mutate props，所有交互都读写这份本地副本
const localState = reactive<Record<string, LocalFactorState>>({})

// 按 category 分组展示，分组顺序取 factorsMeta 中首次出现的顺序
const groupedFactors = computed(() => {
  const order: string[] = []
  const map = new Map<string, FactorMeta[]>()
  props.factorsMeta.forEach((meta) => {
    if (!map.has(meta.category)) {
      map.set(meta.category, [])
      order.push(meta.category)
    }
    map.get(meta.category)!.push(meta)
  })
  return order.map((category) => ({ category, items: map.get(category)! }))
})

// 汇总本地状态中已启用的因子，生成对外输出的数组（顺序与 factorsMeta 一致）
function toConfigItems(): FactorConfigItem[] {
  return props.factorsMeta
    .filter((meta) => localState[meta.key]?.enabled)
    .map((meta) => ({
      key: meta.key,
      weight: localState[meta.key].weight,
      direction: localState[meta.key].direction
    }))
}

// 用于防止 emit -> 父组件更新 modelValue -> 本地 watch 再次同步 -> 死循环
// 记录上一次向外 emit 的序列化内容，watch 中若与之相同则说明是自身触发的回声，直接跳过
let lastEmittedSnapshot = ''

function emitUpdate() {
  const payload = toConfigItems()
  lastEmittedSnapshot = JSON.stringify(payload)
  emit('update:modelValue', payload)
}

// 依据 factorsMeta + 外部 modelValue 初始化/补齐本地状态。
// 已存在的本地状态保留不动（避免 factorsMeta 异步刷新或外部同步时覆盖用户正在编辑的值）。
function syncFromMeta(meta: FactorMeta[], external: FactorConfigItem[]) {
  const externalMap = new Map(external.map((item) => [item.key, item]))
  const metaKeys = new Set(meta.map((m) => m.key))

  // 防御性清理：移除已不在 factorsMeta 中的旧 key
  Object.keys(localState).forEach((key) => {
    if (!metaKeys.has(key)) {
      delete localState[key]
    }
  })

  meta.forEach((m) => {
    if (localState[m.key]) return
    const ext = externalMap.get(m.key)
    localState[m.key] = ext
      ? { enabled: true, weight: ext.weight, direction: ext.direction }
      : { enabled: false, weight: DEFAULT_WEIGHT, direction: m.default_direction }
  })
}

syncFromMeta(props.factorsMeta, props.modelValue)
lastEmittedSnapshot = JSON.stringify(toConfigItems())

// factorsMeta 一般只在页面加载时请求一次，若异步到达/刷新则补齐新出现的因子的本地状态
watch(
  () => props.factorsMeta,
  (meta) => {
    syncFromMeta(meta, props.modelValue)
  }
)

watch(
  () => props.modelValue,
  (newValue) => {
    const snapshot = JSON.stringify(newValue)
    if (snapshot === lastEmittedSnapshot) {
      // 本组件自身 emit 触发的父级更新回声，忽略以避免死循环
      return
    }
    lastEmittedSnapshot = snapshot

    const externalMap = new Map((newValue || []).map((item) => [item.key, item]))
    props.factorsMeta.forEach((m) => {
      const ext = externalMap.get(m.key)
      if (ext) {
        localState[m.key] = { enabled: true, weight: ext.weight, direction: ext.direction }
      } else if (localState[m.key]) {
        localState[m.key].enabled = false
      }
    })
  },
  { deep: true }
)
</script>

<style scoped lang="scss">
.factor-config {
  width: 100%;
}

.factor-config-empty {
  padding: 8px 0;
}

.factor-config-groups {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.factor-config-group {
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  padding: 12px;
}

.factor-config-group-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}

.factor-config-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.factor-config-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.factor-config-checkbox {
  width: 140px;
  flex-shrink: 0;
}

.factor-config-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.factor-config-weight {
  width: 110px;
}

.factor-config-direction {
  flex-shrink: 0;
}
</style>
</content>
