<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDivider,
  NDropdown,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  NTooltip
} from 'naive-ui'
import {
  AddOutline,
  ArrowDownOutline,
  ArrowUpOutline,
  CopyOutline,
  TrashOutline
} from '@vicons/ionicons5'
import type { ActionStep } from '@/api'
import { STEP_META, type StepMeta } from '@/components/actionFlowMeta'

const props = defineProps<{ modelValue: ActionStep[] }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: ActionStep[]): void }>()

const selected = ref(-1)
const dragIndex = ref(-1)
const overIndex = ref(-1)

const steps = computed(() => props.modelValue || [])

function update(next: ActionStep[]) {
  emit('update:modelValue', next.slice())
}

function addStep(type: string) {
  const meta = STEP_META[type]
  if (!meta) return
  const next = steps.value.slice()
  next.push(JSON.parse(JSON.stringify(meta.preset ?? { type })))
  update(next)
  selected.value = next.length - 1
}

function removeStep(index: number) {
  const next = steps.value.slice()
  next.splice(index, 1)
  update(next)
  selected.value = Math.min(selected.value, next.length - 1)
}

function duplicateStep(index: number) {
  const next = steps.value.slice()
  next.splice(index + 1, 0, JSON.parse(JSON.stringify(steps.value[index])))
  update(next)
  selected.value = index + 1
}

function move(index: number, delta: number) {
  const target = index + delta
  if (target < 0 || target >= steps.value.length) return
  const next = steps.value.slice()
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item)
  update(next)
  selected.value = target
}

function onDragStart(index: number) {
  dragIndex.value = index
}

function onDragOver(index: number, event: DragEvent) {
  event.preventDefault()
  overIndex.value = index
}

function onDrop(index: number) {
  const from = dragIndex.value
  dragIndex.value = -1
  overIndex.value = -1
  if (from < 0 || from === index) return
  const next = steps.value.slice()
  const [item] = next.splice(from, 1)
  next.splice(index, 0, item)
  update(next)
  selected.value = index
}

function onDragEnd() {
  dragIndex.value = -1
  overIndex.value = -1
}

const addOptions = Object.entries(STEP_META).map(([key, meta]) => ({
  label: `${meta.label} · ${meta.desc}`,
  key
}))

function getField(step: ActionStep, path: string): any {
  return path.split('.').reduce<any>((acc, part) => (acc == null ? acc : acc[part]), step)
}

function setField(index: number, path: string, value: any) {
  const next = steps.value.slice()
  const clone = JSON.parse(JSON.stringify(next[index]))
  const parts = path.split('.')
  let cursor = clone
  for (let i = 0; i < parts.length - 1; i += 1) {
    cursor[parts[i]] = cursor[parts[i]] ?? {}
    cursor = cursor[parts[i]]
  }
  const last = parts[parts.length - 1]
  if (value === null || value === '' || (typeof value === 'number' && Number.isNaN(value))) {
    delete cursor[last]
  } else if (path === 'options' && typeof value === 'string') {
    cursor[last] = value
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean)
  } else {
    cursor[last] = value
  }
  next[index] = clone
  update(next)
}

const currentMeta = computed<StepMeta | null>(() => {
  const step = steps.value[selected.value]
  return step ? STEP_META[step.type] ?? null : null
})

const currentStep = computed<ActionStep | null>(() => steps.value[selected.value] ?? null)
</script>

<template>
  <div>
    <n-space align="center" justify="space-between" style="margin-bottom: 12px">
      <n-space align="center" :size="8">
        <span style="font-size: 13px; font-weight: 500">动作流</span>
        <n-tag size="tiny" :bordered="false">{{ steps.length }} 步</n-tag>
      </n-space>
      <n-dropdown trigger="click" :options="addOptions" @select="addStep">
        <n-button size="small" type="primary" dashed>
          <template #icon>
            <n-icon><AddOutline /></n-icon>
          </template>
          添加步骤
        </n-button>
      </n-dropdown>
    </n-space>

    <div style="display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr); gap: 16px">
      <div>
        <n-empty
          v-if="!steps.length"
          description="还没有步骤，点右上角「添加步骤」开始"
          style="padding: 32px 0"
        />
        <div v-else style="display: flex; flex-direction: column; gap: 10px">
          <div
            v-for="(step, index) in steps"
            :key="index"
            class="flow-step"
            :class="{ dragging: dragIndex === index, 'drag-over': overIndex === index }"
            :style="{
              border: selected === index ? '1px solid #229ED9' : '1px solid transparent',
              background: selected === index ? 'rgba(34,158,217,0.08)' : 'rgba(128,128,128,0.06)'
            }"
            draggable="true"
            @click="selected = index"
            @dragstart="onDragStart(index)"
            @dragover="(e) => onDragOver(index, e)"
            @drop="() => onDrop(index)"
            @dragend="onDragEnd"
          >
            <n-space align="center" justify="space-between" :wrap="false">
              <n-space align="center" :size="8" :wrap="false" style="min-width: 0">
                <span class="mono" style="opacity: 0.45; width: 16px">{{ index + 1 }}</span>
                <n-tag size="tiny" :type="(STEP_META[step.type]?.color as any) ?? 'default'" :bordered="false" round>
                  {{ STEP_META[step.type]?.label ?? step.type }}
                </n-tag>
                <span
                  style="
                    font-size: 12px;
                    opacity: 0.7;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    max-width: 220px;
                  "
                >
                  {{ STEP_META[step.type]?.summary(step) ?? '' }}
                </span>
              </n-space>
              <n-space :size="2" :wrap="false">
                <n-tooltip>
                  <template #trigger>
                    <n-button text size="tiny" @click.stop="move(index, -1)">
                      <template #icon><n-icon><ArrowUpOutline /></n-icon></template>
                    </n-button>
                  </template>
                  上移
                </n-tooltip>
                <n-tooltip>
                  <template #trigger>
                    <n-button text size="tiny" @click.stop="move(index, 1)">
                      <template #icon><n-icon><ArrowDownOutline /></n-icon></template>
                    </n-button>
                  </template>
                  下移
                </n-tooltip>
                <n-tooltip>
                  <template #trigger>
                    <n-button text size="tiny" @click.stop="duplicateStep(index)">
                      <template #icon><n-icon><CopyOutline /></n-icon></template>
                    </n-button>
                  </template>
                  复制
                </n-tooltip>
                <n-tooltip>
                  <template #trigger>
                    <n-button text size="tiny" type="error" @click.stop="removeStep(index)">
                      <template #icon><n-icon><TrashOutline /></n-icon></template>
                    </n-button>
                  </template>
                  删除
                </n-tooltip>
              </n-space>
            </n-space>
          </div>
        </div>
      </div>

      <div>
        <n-card
          size="small"
          class="soft-card"
          :title="currentMeta ? `参数：${currentMeta.label}` : '步骤参数'"
        >
          <div v-if="!currentStep" class="empty-hint" style="padding: 32px 0">
            选中左侧任意步骤以编辑参数
          </div>
          <template v-else>
            <n-alert type="default" :bordered="false" style="margin-bottom: 12px; font-size: 12px">
              {{ currentMeta?.desc }}
            </n-alert>
            <n-form label-placement="top" size="small">
              <n-form-item
                v-for="field in currentMeta?.fields ?? []"
                :key="field.key"
                :label="field.label"
              >
                <n-input
                  v-if="field.type === 'text'"
                  :value="getField(currentStep, field.key) ?? ''"
                  :placeholder="field.placeholder"
                  @update:value="(v: string) => setField(selected, field.key, v)"
                />
                <n-input
                  v-else-if="field.type === 'textarea'"
                  type="textarea"
                  :rows="3"
                  :value="getField(currentStep, field.key) ?? ''"
                  :placeholder="field.placeholder"
                  @update:value="(v: string) => setField(selected, field.key, v)"
                />
                <n-input-number
                  v-else-if="field.type === 'number'"
                  :value="getField(currentStep, field.key) ?? null"
                  :step="field.step ?? 1"
                  :min="0"
                  style="width: 100%"
                  @update:value="(v: number | null) => setField(selected, field.key, v)"
                />
                <n-switch
                  v-else-if="field.type === 'switch'"
                  :value="!!getField(currentStep, field.key)"
                  @update:value="(v: boolean) => setField(selected, field.key, v)"
                />
                <n-select
                  v-else-if="field.type === 'select'"
                  :value="getField(currentStep, field.key) ?? null"
                  :options="field.options ?? []"
                  @update:value="(v: string) => setField(selected, field.key, v)"
                />
                <span
                  v-if="field.hint"
                  style="font-size: 11px; opacity: 0.55; margin-top: 2px; display: block"
                >
                  {{ field.hint }}
                </span>
              </n-form-item>
            </n-form>
          </template>
        </n-card>

        <n-divider style="margin: 14px 0" />

        <n-alert type="info" :bordered="false" style="font-size: 12px; line-height: 1.8">
          可用变量：<code>{last_reply}</code> 最近收到的回复、<code>{date}</code> 今天日期、
          <code>{task}</code> 任务名、<code>{target}</code> 目标。用「正则提取」定义的变量可被后续步骤引用。
        </n-alert>
      </div>
    </div>
  </div>
</template>
