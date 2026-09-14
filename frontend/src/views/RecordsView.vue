<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NDatePicker,
  NDescriptions,
  NDescriptionsItem,
  NInput,
  NModal,
  NPagination,
  NSelect,
  NSpace,
  NTag,
  NPopconfirm,
  type DataTableColumns
} from 'naive-ui'
import { recordApi, taskApi, extractError, type RecordItem, type Task } from '@/api'
import { feedback } from '@/utils/feedback'
import { formatDuration, formatTime, statusTagType, triggerLabel } from '@/utils/format'

const rows = ref<RecordItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const tasks = ref<Task[]>([])
const filter = ref({
  task_id: null as number | null,
  status: null as string | null,
  keyword: '',
  range: null as [number, number] | null
})

const detailShow = ref(false)
const detail = ref<RecordItem | null>(null)

const checkedRowKeys = ref<number[]>([])
const deleting = ref(false)

const taskOptions = ref<{ label: string; value: number }[]>([])

async function load() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
    if (filter.value.task_id) params.task_id = filter.value.task_id
    if (filter.value.status) params.status = filter.value.status
    if (filter.value.keyword.trim()) params.keyword = filter.value.keyword.trim()
    if (filter.value.range) {
      params.start = new Date(filter.value.range[0]).toISOString()
      params.end = new Date(filter.value.range[1]).toISOString()
    }
    const data = await recordApi.list(params)
    rows.value = data.items
    total.value = data.total
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    loading.value = false
  }
}

function resetFilter() {
  filter.value = { task_id: null, status: null, keyword: '', range: null }
  page.value = 1
  load()
}

function exportCsv() {
  const params: Record<string, any> = {}
  if (filter.value.task_id) params.task_id = filter.value.task_id
  if (filter.value.status) params.status = filter.value.status
  if (filter.value.keyword.trim()) params.keyword = filter.value.keyword.trim()
  if (filter.value.range) {
    params.start = new Date(filter.value.range[0]).toISOString()
    params.end = new Date(filter.value.range[1]).toISOString()
  }
  window.open(recordApi.exportUrl(params), '_blank')
}

async function clearRecords(days: number) {
  deleting.value = true
  try {
    const res = await recordApi.clear(days)
    feedback.ok(res.message)
    checkedRowKeys.value = []
    page.value = 1
    await load()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    deleting.value = false
  }
}

async function removeSelected() {
  const ids = [...checkedRowKeys.value]
  if (!ids.length) return
  deleting.value = true
  try {
    const res = await recordApi.removeSelected(ids)
    feedback.ok(res.message)
    // 整页都被删掉时回退一页，避免停在空白页
    if (ids.length >= rows.value.length && page.value > 1) page.value -= 1
    checkedRowKeys.value = []
    await load()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    deleting.value = false
  }
}

async function clearAllRecords() {
  deleting.value = true
  try {
    const res = await recordApi.clearAll()
    feedback.ok(res.message)
    checkedRowKeys.value = []
    page.value = 1
    await load()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    deleting.value = false
  }
}

function openDetail(row: RecordItem) {
  detail.value = row
  detailShow.value = true
}

const columns: DataTableColumns<RecordItem> = [
  { type: 'selection' },
  { title: '时间', key: 'run_at', width: 168, render: (row) => formatTime(row.run_at) },
  { title: '任务', key: 'task_name', minWidth: 130, ellipsis: { tooltip: true } },
  { title: '账号', key: 'account_name', width: 110, ellipsis: { tooltip: true } },
  { title: '目标', key: 'target', width: 130, ellipsis: { tooltip: true } },
  { title: '触发', key: 'trigger', width: 80, render: (row) => triggerLabel(row.trigger) },
  {
    title: '状态',
    key: 'status',
    width: 88,
    render: (row) =>
      h(NTag, { size: 'small', round: true, bordered: false, type: statusTagType(row.status) }, {
        default: () => (row.status === 'success' ? '成功' : '失败')
      })
  },
  { title: '尝试', key: 'attempt', width: 66 },
  { title: '耗时', key: 'duration_ms', width: 82, render: (row) => formatDuration(row.duration_ms) },
  {
    title: '结果摘要',
    key: 'summary',
    minWidth: 220,
    ellipsis: { tooltip: true },
    render: (row) => row.reward_text || row.matched_keyword || row.reply_snippet || row.error || '—'
  },
  {
    title: '操作',
    key: 'actions',
    width: 76,
    render: (row) => h(NButton, { size: 'tiny', onClick: () => openDetail(row) }, { default: () => '详情' })
  }
]

onMounted(async () => {
  try {
    const list = await taskApi.list()
    taskOptions.value = list.map((t) => ({ label: t.name, value: t.id }))
  } catch {
    /* 忽略：任务列表加载失败不影响记录查询 */
  }
  await load()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">签到记录</h2>
        <p class="page-desc">每一次执行的完整留痕，包含命中关键词、提取到的奖励与错误信息。</p>
      </div>
      <n-space>
        <n-button @click="exportCsv">导出 CSV</n-button>
        <n-button
          type="error"
          :disabled="!checkedRowKeys.length"
          :loading="deleting"
          @click="removeSelected"
        >
          删除选中{{ checkedRowKeys.length ? `（${checkedRowKeys.length}）` : '' }}
        </n-button>
        <n-popconfirm @positive-click="() => clearRecords(30)">
          <template #trigger>
            <n-button type="error" quaternary :loading="deleting">清理 30 天前</n-button>
          </template>
          删除 30 天以前的记录，确定？
        </n-popconfirm>
        <n-popconfirm @positive-click="clearAllRecords">
          <template #trigger>
            <n-button type="error" quaternary :loading="deleting">清空全部</n-button>
          </template>
          将删除全部 {{ total }} 条签到记录，且不可恢复，确定继续？
        </n-popconfirm>
        <n-button :loading="loading" @click="load">刷新</n-button>
      </n-space>
    </div>

    <n-card class="soft-card" size="small">
      <n-space align="center" :size="10" style="margin-bottom: 14px; flex-wrap: wrap">
        <n-select
          v-model:value="filter.task_id"
          :options="taskOptions"
          clearable
          placeholder="全部任务"
          style="width: 180px"
        />
        <n-select
          v-model:value="filter.status"
          :options="[
            { label: '成功', value: 'success' },
            { label: '失败', value: 'fail' }
          ]"
          clearable
          placeholder="全部状态"
          style="width: 130px"
        />
        <n-date-picker v-model:value="filter.range" type="datetimerange" clearable style="width: 340px" />
        <n-input
          v-model:value="filter.keyword"
          placeholder="搜索目标 / 任务 / 回复内容"
          style="width: 220px"
          @keyup.enter="() => { page = 1; load() }"
        />
        <n-button type="primary" @click="() => { page = 1; load() }">查询</n-button>
        <n-button @click="resetFilter">重置</n-button>
      </n-space>

      <n-data-table
        v-model:checked-row-keys="checkedRowKeys"
        :columns="columns"
        :data="rows"
        :bordered="false"
        :loading="loading"
        size="small"
        remote
        :row-key="(row: RecordItem) => row.id"
        :scroll-x="1250"
      />

      <n-space justify="end" style="margin-top: 14px">
        <n-pagination
          v-model:page="page"
          v-model:page-size="pageSize"
          :item-count="total"
          :page-sizes="[10, 20, 50, 100]"
          show-size-picker
          show-quick-jumper
          @update:page="load"
          @update:page-size="() => { page = 1; load() }"
        />
      </n-space>
    </n-card>

    <n-modal
      v-model:show="detailShow"
      preset="card"
      title="执行详情"
      style="max-width: 680px; width: 94vw"
      :bordered="false"
    >
      <n-descriptions v-if="detail" :column="2" label-placement="top" bordered size="small">
        <n-descriptions-item label="时间">{{ formatTime(detail.run_at) }}</n-descriptions-item>
        <n-descriptions-item label="任务">{{ detail.task_name }}</n-descriptions-item>
        <n-descriptions-item label="账号">{{ detail.account_name }}</n-descriptions-item>
        <n-descriptions-item label="目标">{{ detail.target }}</n-descriptions-item>
        <n-descriptions-item label="触发方式">{{ triggerLabel(detail.trigger) }}</n-descriptions-item>
        <n-descriptions-item label="耗时">{{ formatDuration(detail.duration_ms) }}</n-descriptions-item>
        <n-descriptions-item label="状态">
          <n-tag :type="statusTagType(detail.status)" size="small" round :bordered="false">
            {{ detail.status === 'success' ? '成功' : '失败' }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="命中关键词">{{ detail.matched_keyword || '—' }}</n-descriptions-item>
        <n-descriptions-item label="提取奖励">{{ detail.reward_text || '—' }}</n-descriptions-item>
        <n-descriptions-item label="尝试次数">第 {{ detail.attempt }} 次</n-descriptions-item>
        <n-descriptions-item label="完整回复" :span="2">
          <div class="mono" style="white-space: pre-wrap; max-height: 200px; overflow: auto">
            {{ detail.reply_snippet || '—' }}
          </div>
        </n-descriptions-item>
        <n-descriptions-item v-if="detail.error" label="错误信息" :span="2">
          <div class="mono" style="color: #d03050; white-space: pre-wrap">{{ detail.error }}</div>
        </n-descriptions-item>
        <n-descriptions-item v-if="detail.detail?.trace?.length" label="步骤轨迹" :span="2">
          <div class="mono" style="max-height: 220px; overflow: auto">
            <div v-for="(step, i) in detail.detail.trace" :key="i">
              {{ i + 1 }}. [{{ step.ok ? 'OK' : 'FAIL' }}] {{ step.type }} — {{ step.message }}
            </div>
          </div>
        </n-descriptions-item>
      </n-descriptions>
    </n-modal>
  </div>
</template>
