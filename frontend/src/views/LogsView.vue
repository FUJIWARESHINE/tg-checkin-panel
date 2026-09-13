<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, nextTick, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NCheckboxGroup,
  NInput,
  NSpace,
  NSwitch,
  NTag
} from 'naive-ui'
import { logsSocketUrl } from '@/api'
import { feedback } from '@/utils/feedback'

interface LogItem {
  ts?: string
  level?: string
  logger?: string
  message?: string
  type?: string
}

const logs = ref<LogItem[]>([])
const connected = ref(false)
const paused = ref(false)
const autoScroll = ref(true)
const keyword = ref('')
const levels = ref<string[]>(['INFO', 'WARNING', 'ERROR'])
const maxLines = 1000

let socket: WebSocket | null = null
let retryTimer: number | undefined
const container = ref<HTMLDivElement | null>(null)

const levelColor: Record<string, string> = {
  DEBUG: 'default',
  INFO: 'info',
  WARNING: 'warning',
  ERROR: 'error',
  CRITICAL: 'error'
}

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return logs.value.filter((item) => {
    if (item.type === 'ping') return false
    if (item.level && !levels.value.includes(item.level)) return false
    if (kw && !`${item.logger ?? ''} ${item.message ?? ''}`.toLowerCase().includes(kw)) return false
    return true
  })
})

function connect() {
  disconnect()
  try {
    socket = new WebSocket(logsSocketUrl())
  } catch (error) {
    feedback.error('无法建立日志连接')
    return
  }

  socket.onopen = () => {
    connected.value = true
  }

  socket.onmessage = (event) => {
    if (paused.value) return
    try {
      const item = JSON.parse(event.data) as LogItem
      logs.value.push(item)
      if (logs.value.length > maxLines) {
        logs.value.splice(0, logs.value.length - maxLines)
      }
      if (autoScroll.value) {
        nextTick(() => {
          if (container.value) container.value.scrollTop = container.value.scrollHeight
        })
      }
    } catch {
      /* 忽略非 JSON 消息 */
    }
  }

  socket.onclose = () => {
    connected.value = false
    retryTimer = window.setTimeout(connect, 4000)
  }

  socket.onerror = () => {
    connected.value = false
  }
}

function disconnect() {
  if (retryTimer) {
    window.clearTimeout(retryTimer)
    retryTimer = undefined
  }
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
  connected.value = false
}

function clearLogs() {
  logs.value = []
}

function downloadLogs() {
  const text = filtered.value
    .map((i) => `${i.ts ?? ''} | ${i.level ?? ''} | ${i.logger ?? ''} | ${i.message ?? ''}`)
    .join('\n')
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `tg-checkin-logs-${Date.now()}.log`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(connect)
onBeforeUnmount(disconnect)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">实时日志</h2>
        <p class="page-desc">服务端日志实时推送，排查签到失败原因时最有用。</p>
      </div>
      <n-space align="center">
        <n-tag :type="connected ? 'success' : 'error'" size="small" round :bordered="false">
          {{ connected ? '已连接' : '已断开' }}
        </n-tag>
        <n-button size="small" @click="connect">重连</n-button>
        <n-button size="small" @click="downloadLogs">下载</n-button>
        <n-button size="small" quaternary type="error" @click="clearLogs">清空</n-button>
      </n-space>
    </div>

    <n-card class="soft-card" size="small">
      <n-space align="center" :size="12" style="margin-bottom: 12px; flex-wrap: wrap">
        <n-input v-model:value="keyword" placeholder="关键词过滤" size="small" style="width: 220px" />
        <n-checkbox-group v-model:value="levels" size="small">
          <n-space :size="12">
            <n-checkbox value="DEBUG" label="DEBUG" size="small" />
            <n-checkbox value="INFO" label="INFO" size="small" />
            <n-checkbox value="WARNING" label="WARNING" size="small" />
            <n-checkbox value="ERROR" label="ERROR" size="small" />
          </n-space>
        </n-checkbox-group>
        <n-space align="center" :size="6">
          <span style="font-size: 12px">自动滚动</span>
          <n-switch v-model:value="autoScroll" size="small" />
        </n-space>
        <n-space align="center" :size="6">
          <span style="font-size: 12px">暂停</span>
          <n-switch v-model:value="paused" size="small" />
        </n-space>
        <span style="font-size: 12px; opacity: 0.55">{{ filtered.length }} 条</span>
      </n-space>

      <div
        ref="container"
        class="log-line"
        style="
          height: 62vh;
          overflow: auto;
          padding: 12px 14px;
          border-radius: 10px;
          background: rgba(128, 128, 128, 0.08);
        "
      >
        <div v-for="(item, index) in filtered" :key="index">
          <span style="opacity: 0.5">{{ item.ts }}</span>
          <span
            :style="{
              margin: '0 8px',
              color:
                item.level === 'ERROR' || item.level === 'CRITICAL'
                  ? '#d03050'
                  : item.level === 'WARNING'
                    ? '#f0a020'
                    : '#18a058'
            }"
            >{{ (item.level ?? '').padEnd(7) }}</span
          >
          <span style="opacity: 0.65">{{ item.logger }}</span>
          <span> {{ item.message }}</span>
        </div>
        <div v-if="!filtered.length" class="empty-hint">暂无日志输出</div>
      </div>
    </n-card>
  </div>
</template>
