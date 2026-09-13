<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NCheckboxGroup,
  NDivider,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpace,
  NSwitch,
  NTag
} from 'naive-ui'
import { notifyApi, extractError, EVENT_LABELS, type ChannelTypeMeta, type NotifyChannel } from '@/api'
import { feedback } from '@/utils/feedback'
import { formatTime } from '@/utils/format'

const channels = ref<NotifyChannel[]>([])
const typeMeta = ref<Record<string, ChannelTypeMeta>>({})
const loading = ref(false)
const saving = ref(false)
const testing = ref<number | 'new' | null>(null)

const modalShow = ref(false)
const editingId = ref<number | null>(null)
const form = ref({
  name: '',
  type: 'telegram',
  config: {} as Record<string, any>,
  enabled: true,
  on_events: ['success', 'fail', 'auth_expired'] as string[],
  quiet_start: '',
  quiet_end: '',
  quiet_only_fail: true
})

const typeOptions = computed(() =>
  Object.entries(typeMeta.value).map(([key, meta]) => ({ label: meta.label, value: key }))
)
const currentMeta = computed(() => typeMeta.value[form.value.type])

async function load() {
  loading.value = true
  try {
    const [types, list] = await Promise.all([notifyApi.types(), notifyApi.list()])
    typeMeta.value = types.types
    channels.value = list
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = {
    name: 'Telegram 通知',
    type: 'telegram',
    config: {},
    enabled: true,
    on_events: ['success', 'fail', 'auth_expired'],
    quiet_start: '',
    quiet_end: '',
    quiet_only_fail: true
  }
  modalShow.value = true
}

function openEdit(row: NotifyChannel) {
  editingId.value = row.id
  form.value = {
    name: row.name,
    type: row.type,
    config: { ...row.config_masked },
    enabled: row.enabled,
    on_events: [...row.on_events],
    quiet_start: row.quiet_start,
    quiet_end: row.quiet_end,
    quiet_only_fail: row.quiet_only_fail
  }
  modalShow.value = true
}

function onTypeChange(value: string) {
  form.value.type = value
  form.value.config = {}
}

async function submit() {
  if (!form.value.name.trim()) {
    feedback.warn('请填写渠道名称')
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await notifyApi.update(editingId.value, { ...form.value })
      feedback.ok('渠道已更新')
    } else {
      await notifyApi.create({ ...form.value })
      feedback.ok('渠道已创建')
    }
    modalShow.value = false
    await load()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    saving.value = false
  }
}

async function testForm() {
  testing.value = 'new'
  try {
    await notifyApi.test({
      type: form.value.type,
      config: { ...form.value.config, _channel_id: editingId.value ?? undefined }
    })
    feedback.ok('测试消息已发送，请查看接收端')
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    testing.value = null
  }
}

async function testSaved(row: NotifyChannel) {
  testing.value = row.id
  try {
    await notifyApi.testSaved(row.id)
    feedback.ok('测试消息已发送')
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    testing.value = null
    load()
  }
}

async function removeChannel(row: NotifyChannel) {
  const ok = await feedback.confirm({
    title: '删除渠道',
    content: `确定删除推送渠道「${row.name}」？`,
    positiveText: '删除'
  })
  if (!ok) return
  try {
    await notifyApi.remove(row.id)
    feedback.ok('渠道已删除')
    load()
  } catch (error) {
    feedback.error(extractError(error))
  }
}

function eventLabels(events: string[]) {
  if (!events.length) return '全部事件'
  return events.map((e) => EVENT_LABELS[e] ?? e).join(' / ')
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">推送设置</h2>
        <p class="page-desc">
          用你自己的通知 Bot 把签到结果推给你。注意：这里配的是「通知通道」，与签到用的个人号是两回事。
        </p>
      </div>
      <n-space>
        <n-button :loading="loading" @click="load">刷新</n-button>
        <n-button type="primary" @click="openCreate">新增渠道</n-button>
      </n-space>
    </div>

    <n-alert type="info" :show-icon="true">
      <b>Telegram 推送怎么配？</b>① 找 @BotFather 创建一个 Bot，拿到 Bot Token；
      ② 给 @userinfobot 发消息，拿到你自己的 Chat ID；③ 把两者填进下面。
      别忘了先给这个 Bot 发一条消息，否则 Bot 无法主动找你。
    </n-alert>

    <n-grid :cols="3" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
      <n-gi v-for="row in channels" :key="row.id" span="3 s:3 m:1">
        <n-card class="soft-card" size="small" hoverable>
          <template #header>
            <n-space align="center" :size="8">
              <span style="font-weight: 500">{{ row.name }}</span>
              <n-tag size="tiny" :bordered="false" round>{{ typeMeta[row.type]?.label ?? row.type }}</n-tag>
              <n-tag v-if="!row.enabled" size="tiny" type="warning" :bordered="false" round>已停用</n-tag>
            </n-space>
          </template>
          <n-space vertical :size="6" style="font-size: 12px">
            <div>订阅事件：{{ eventLabels(row.on_events) }}</div>
            <div v-if="row.quiet_start && row.quiet_end">
              静默时段：{{ row.quiet_start }} - {{ row.quiet_end }}
            </div>
            <div>最近推送：{{ formatTime(row.last_sent_at) }}</div>
            <div v-if="row.last_result" :style="{ color: row.last_result === 'ok' ? '#18a058' : '#d03050' }">
              结果：{{ row.last_result === 'ok' ? '正常' : row.last_result }}
            </div>
          </n-space>
          <template #footer>
            <n-space :size="6">
              <n-button size="tiny" type="primary" :loading="testing === row.id" @click="testSaved(row)">
                测试推送
              </n-button>
              <n-button size="tiny" @click="openEdit(row)">编辑</n-button>
              <n-button size="tiny" type="error" quaternary @click="removeChannel(row)">删除</n-button>
            </n-space>
          </template>
        </n-card>
      </n-gi>
      <n-gi v-if="!channels.length && !loading" span="3">
        <n-card class="soft-card" size="small">
          <div class="empty-hint">
            还没有推送渠道。建议先加一个 Telegram Bot 渠道，最省事也最稳。
          </div>
        </n-card>
      </n-gi>
    </n-grid>

    <n-modal
      v-model:show="modalShow"
      preset="card"
      :title="editingId ? '编辑推送渠道' : '新增推送渠道'"
      style="max-width: 620px; width: 94vw"
      :bordered="false"
    >
      <n-form label-placement="top">
        <n-grid :cols="2" :x-gap="16">
          <n-gi>
            <n-form-item label="渠道名称">
              <n-input v-model:value="form.name" placeholder="例如：我的 TG 通知" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="渠道类型">
              <n-select
                :value="form.type"
                :options="typeOptions"
                :disabled="!!editingId"
                @update:value="onTypeChange"
              />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-alert v-if="currentMeta?.hint" type="default" :bordered="false" style="margin-bottom: 14px; font-size: 12px">
          {{ currentMeta.hint }}
        </n-alert>

        <n-grid :cols="2" :x-gap="16">
          <n-gi v-for="field in currentMeta?.fields ?? []" :key="field.key" :span="field.type === 'json' ? 2 : 1">
            <n-form-item :label="`${field.label}${field.required ? ' *' : ''}`">
              <n-input
                v-if="field.type === 'text' || field.type === 'password'"
                v-model:value="form.config[field.key]"
                :type="field.type === 'password' ? 'password' : 'text'"
                :show-password-on="field.type === 'password' ? 'click' : undefined"
                :placeholder="field.placeholder"
              />
              <n-input-number
                v-else-if="field.type === 'number'"
                v-model:value="form.config[field.key]"
                style="width: 100%"
                :placeholder="field.placeholder"
              />
              <n-switch
                v-else-if="field.type === 'switch'"
                v-model:value="form.config[field.key]"
              />
              <n-input
                v-else-if="field.type === 'json'"
                v-model:value="form.config[field.key]"
                type="textarea"
                :rows="3"
                placeholder='{"X-Token": "abc"}'
              />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-divider style="margin: 4px 0 14px" />

        <n-form-item label="订阅事件">
          <n-checkbox-group v-model:value="form.on_events">
            <n-space :size="14">
              <n-checkbox v-for="(label, key) in EVENT_LABELS" :key="key" :value="key" :label="label" />
            </n-space>
          </n-checkbox-group>
        </n-form-item>

        <n-grid :cols="3" :x-gap="12">
          <n-gi>
            <n-form-item label="静默开始（HH:mm）">
              <n-input v-model:value="form.quiet_start" placeholder="23:00" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="静默结束（HH:mm）">
              <n-input v-model:value="form.quiet_end" placeholder="07:00" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="静默时仍推失败">
              <n-switch v-model:value="form.quiet_only_fail" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-form-item label="启用">
          <n-switch v-model:value="form.enabled" />
        </n-form-item>
      </n-form>

      <template #footer>
        <n-space justify="space-between" style="width: 100%">
          <n-button :loading="testing === 'new'" @click="testForm">发送测试消息</n-button>
          <n-space>
            <n-button @click="modalShow = false">取消</n-button>
            <n-button type="primary" :loading="saving" @click="submit">保存</n-button>
          </n-space>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
