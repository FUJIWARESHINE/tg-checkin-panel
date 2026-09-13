<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NGi,
  NGrid,
  NIcon,
  NSpace,
  NSpin,
  NStatistic,
  NTag,
  NThing,
  type DataTableColumns
} from 'naive-ui'
import {
  CheckmarkCircleOutline,
  CloseCircleOutline,
  FlashOutline,
  TrendingUpOutline
} from '@vicons/ionicons5'
import type { EChartsOption } from 'echarts'
import EChart from '@/components/EChart.vue'
import { recordApi, systemApi, type RecordItem, type StatsData, type SystemInfo } from '@/api'
import { extractError } from '@/api'
import { feedback } from '@/utils/feedback'
import { useThemeStore } from '@/stores/theme'
import { formatDuration, formatTime, statusTagType, triggerLabel } from '@/utils/format'

const stats = ref<StatsData | null>(null)
const info = ref<SystemInfo | null>(null)
const loading = ref(true)
const themeStore = useThemeStore()

async function load() {
  loading.value = true
  try {
    const [s, i] = await Promise.all([recordApi.stats(30), systemApi.info()])
    stats.value = s
    info.value = i
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    loading.value = false
  }
}

const accent = computed(() => (themeStore.mode === 'dark' ? '#e5e5e5' : '#333333'))
const gridColor = computed(() => (themeStore.mode === 'dark' ? '#3a3a3a' : '#eeeeee'))

const chartOption = computed<EChartsOption>(() => {
  const data = stats.value?.heatmap ?? []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['成功', '失败'], textStyle: { color: accent.value }, top: 0, right: 0 },
    grid: { left: 8, right: 12, top: 42, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: gridColor.value } },
      axisLabel: { color: accent.value, fontSize: 11, interval: Math.max(0, Math.floor(data.length / 10) - 1) }
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: gridColor.value } },
      axisLabel: { color: accent.value, fontSize: 11 }
    },
    series: [
      {
        name: '成功',
        type: 'bar',
        stack: 'total',
        barMaxWidth: 16,
        itemStyle: { color: '#18a058', borderRadius: [0, 0, 0, 0] },
        data: data.map((d) => d.success)
      },
      {
        name: '失败',
        type: 'bar',
        stack: 'total',
        barMaxWidth: 16,
        itemStyle: { color: '#d03050', borderRadius: [4, 4, 0, 0] },
        data: data.map((d) => d.fail)
      }
    ]
  }
})

const columns: DataTableColumns<RecordItem> = [
  { title: '时间', key: 'run_at', width: 165, render: (r) => formatTime(r.run_at) },
  { title: '任务', key: 'task_name', ellipsis: { tooltip: true } },
  { title: '账号', key: 'account_name', width: 110, ellipsis: { tooltip: true } },
  { title: '目标', key: 'target', width: 140, ellipsis: { tooltip: true } },
  {
    title: '触发',
    key: 'trigger',
    width: 88,
    render: (r) => triggerLabel(r.trigger)
  },
  { title: '耗时', key: 'duration_ms', width: 84, render: (r) => formatDuration(r.duration_ms) },
  {
    title: '状态',
    key: 'status',
    width: 92,
    render: (r) =>
      h(NTag, { type: statusTagType(r.status), size: 'small', round: true, bordered: false }, {
        default: () => (r.status === 'success' ? '成功' : '失败')
      })
  }
]

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">仪表盘</h2>
        <p class="page-desc">签到概览、执行趋势与系统运行状态。</p>
      </div>
      <n-space>
        <n-button :loading="loading" @click="load">刷新</n-button>
        <router-link :to="{ name: 'task-create' }">
          <n-button type="primary">新建任务</n-button>
        </router-link>
      </n-space>
    </div>

    <n-alert v-if="info && !info.scheduler_running" type="warning" :show-icon="true">
      调度器未运行，定时任务不会触发。请到「系统设置」检查。
    </n-alert>
    <n-alert v-if="info && info.accounts_online === 0" type="info" :show-icon="true">
      还没有已登录的 Telegram 账号。
      <router-link :to="{ name: 'accounts' }">去添加账号 →</router-link>
    </n-alert>

    <n-spin :show="loading">
      <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
        <n-gi span="4 s:2 m:1">
          <n-card class="soft-card" size="small">
            <n-statistic label="今日签到成功" :value="stats?.today_success ?? 0">
              <template #prefix>
                <n-icon color="#18a058"><CheckmarkCircleOutline /></n-icon>
              </template>
            </n-statistic>
          </n-card>
        </n-gi>
        <n-gi span="4 s:2 m:1">
          <n-card class="soft-card" size="small">
            <n-statistic label="今日失败" :value="stats?.today_fail ?? 0">
              <template #prefix>
                <n-icon color="#d03050"><CloseCircleOutline /></n-icon>
              </template>
            </n-statistic>
          </n-card>
        </n-gi>
        <n-gi span="4 s:2 m:1">
          <n-card class="soft-card" size="small">
            <n-statistic label="今日执行次数" :value="stats?.today_total ?? 0">
              <template #prefix>
                <n-icon color="#229ed9"><FlashOutline /></n-icon>
              </template>
            </n-statistic>
          </n-card>
        </n-gi>
        <n-gi span="4 s:2 m:1">
          <n-card class="soft-card" size="small">
            <n-statistic label="近 7 天成功率" :value="stats?.success_rate_7d ?? 0" suffix="%">
              <template #prefix>
                <n-icon color="#f0a020"><TrendingUpOutline /></n-icon>
              </template>
            </n-statistic>
          </n-card>
        </n-gi>
      </n-grid>

      <n-grid :cols="3" :x-gap="16" :y-gap="16" style="margin-top: 16px" responsive="screen" item-responsive>
        <n-gi span="3 m:2">
          <n-card class="soft-card" title="近 30 天签到趋势" size="small">
            <e-chart :option="chartOption" height="280px" />
          </n-card>
        </n-gi>
        <n-gi span="3 m:1">
          <n-card class="soft-card" title="系统状态" size="small">
            <n-thing v-if="info">
              <template #description>
                <n-space vertical :size="10" style="font-size: 13px">
                  <div>版本：{{ info.app_name }} v{{ info.version }}</div>
                  <div>
                    调度器：
                    <n-tag :type="info.scheduler_running ? 'success' : 'error'" size="small" round :bordered="false">
                      {{ info.scheduler_running ? '运行中' : '已停止' }}
                    </n-tag>
                  </div>
                  <div>在线账号：{{ info.accounts_online }}</div>
                  <div>任务数：{{ info.tasks_enabled }} / {{ info.tasks_total }} 启用</div>
                  <div>时区：{{ info.timezone }}</div>
                  <div>代理：{{ info.proxy }}</div>
                  <div>数据库：{{ (info.db_size / 1024).toFixed(1) }} KB</div>
                  <div>
                    AI 识图：
                    <n-tag :type="info.ai_enabled ? 'success' : 'default'" size="small" round :bordered="false">
                      {{ info.ai_enabled ? '已启用' : '未启用' }}
                    </n-tag>
                  </div>
                </n-space>
              </template>
            </n-thing>
          </n-card>
        </n-gi>
      </n-grid>

      <n-card class="soft-card" title="最近执行记录" size="small" style="margin-top: 16px">
        <template #header-extra>
          <router-link :to="{ name: 'records' }">
            <n-button text type="primary" size="small">查看全部</n-button>
          </router-link>
        </template>
        <n-data-table
          v-if="stats?.recent?.length"
          :columns="columns"
          :data="stats.recent"
          :bordered="false"
          size="small"
          :row-key="(row: RecordItem) => row.id"
        />
        <div v-else class="empty-hint">暂无执行记录，先去创建一个签到任务吧。</div>
      </n-card>
    </n-spin>
  </div>
</template>
