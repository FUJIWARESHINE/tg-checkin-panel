<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NModal,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NDescriptions,
  NDescriptionsItem,
  type DataTableColumns
} from 'naive-ui'
import { taskApi, extractError, type Task, type TaskTemplate } from '@/api'
import { feedback } from '@/utils/feedback'
import { formatRelative, formatTime, statusTagType } from '@/utils/format'

const router = useRouter()
const tasks = ref<Task[]>([])
const templates = ref<TaskTemplate[]>([])
const loading = ref(false)
const runningId = ref<number | null>(null)

const detailShow = ref(false)
const detailTask = ref<Task | null>(null)

const templateShow = ref(false)
const editingTemplate = ref<TaskTemplate | null>(null)
const templateForm = ref({ name: '', description: '' })

async function load() {
  loading.value = true
  try {
    const [t, tp] = await Promise.all([taskApi.list(), taskApi.templates()])
    tasks.value = t
    templates.value = tp
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    loading.value = false
  }
}

async function toggle(row: Task, enabled: boolean) {
  try {
    await taskApi.toggle(row.id, enabled)
    row.enabled = enabled
    feedback.ok(enabled ? '任务已启用' : '任务已停用')
  } catch (error) {
    feedback.error(extractError(error))
    load()
  }
}

async function runNow(row: Task) {
  runningId.value = row.id
  try {
    const res = await taskApi.run(row.id, true)
    feedback.ok(res.message || '已开始执行')
    setTimeout(load, 4000)
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    runningId.value = null
  }
}

async function removeTask(row: Task) {
  try {
    await taskApi.remove(row.id)
    feedback.ok('任务已删除')
    load()
  } catch (error) {
    feedback.error(extractError(error))
  }
}

function openDetail(row: Task) {
  detailTask.value = row
  detailShow.value = true
}

function editTemplate(row: TaskTemplate) {
  editingTemplate.value = row
  templateForm.value = { name: row.name, description: row.description }
  templateShow.value = true
}

async function submitTemplate() {
  if (!editingTemplate.value) return
  if (!templateForm.value.name.trim()) {
    feedback.warn('模板名称不能为空')
    return
  }
  try {
    await taskApi.updateTemplate(editingTemplate.value.id, {
      ...editingTemplate.value,
      name: templateForm.value.name.trim(),
      description: templateForm.value.description
    })
    feedback.ok('模板已更新，引用它的任务已同步')
    templateShow.value = false
    load()
  } catch (error) {
    feedback.error(extractError(error))
  }
}

async function removeTemplate(row: TaskTemplate) {
  try {
    await taskApi.removeTemplate(row.id)
    feedback.ok('模板已删除')
    load()
  } catch (error) {
    feedback.error(extractError(error))
  }
}

const columns: DataTableColumns<Task> = [
  {
    title: '任务',
    key: 'name',
    minWidth: 160,
    render: (row) =>
      h(
        'div',
        {},
        [
          h('div', { style: 'font-weight:500;font-size:13px' }, row.name),
          row.remark ? h('div', { style: 'font-size:11px;opacity:.6' }, row.remark) : null
        ].filter(Boolean) as any
      )
  },
  { title: '账号', key: 'account_name', width: 110, ellipsis: { tooltip: true } },
  {
    title: '签到目标',
    key: 'targets',
    width: 150,
    ellipsis: { tooltip: true },
    render: (row) => (row.targets || []).map((t) => t.chat).join(', ') || '—'
  },
  { title: '调度', key: 'schedule_text', width: 130 },
  {
    title: '随机延迟',
    key: 'random_delay_sec',
    width: 96,
    render: (row) => (row.random_delay_sec ? `±${row.random_delay_sec}s` : '关闭')
  },
  {
    title: '下次执行',
    key: 'next_run_at',
    width: 150,
    render: (row) => (row.enabled ? formatRelative(row.next_run_at) : '—')
  },
  {
    title: '最近状态',
    key: 'last_status',
    width: 110,
    render: (row) =>
      row.last_status
        ? h(
            NTag,
            { size: 'small', round: true, bordered: false, type: statusTagType(row.last_status) },
            { default: () => (row.last_status === 'success' ? '成功' : '失败') }
          )
        : h('span', { style: 'opacity:.5' }, '未执行')
  },
  {
    title: '启用',
    key: 'enabled',
    width: 76,
    render: (row) =>
      h(NSwitch, {
        value: row.enabled,
        size: 'small',
        'onUpdate:value': (value: boolean) => toggle(row, value)
      })
  },
  {
    title: '操作',
    key: 'actions',
    width: 230,
    render: (row) =>
      h(NSpace, { size: 6, wrap: false }, {
        default: () => [
          h(
            NButton,
            { size: 'tiny', type: 'primary', loading: runningId === row.id, onClick: () => runNow(row) },
            { default: () => '立即执行' }
          ),
          h(NButton, { size: 'tiny', onClick: () => openDetail(row) }, { default: () => '详情' }),
          h(
            NButton,
            {
              size: 'tiny',
              onClick: () => router.push({ name: 'task-edit', params: { id: row.id } })
            },
            { default: () => '编辑' }
          ),
          h(
            NPopconfirm,
            { onPositiveClick: () => removeTask(row) },
            {
              trigger: () => h(NButton, { size: 'tiny', type: 'error', quaternary: true }, { default: () => '删除' }),
              default: () => '删除后不可恢复，确定？'
            }
          )
        ]
      })
  }
]

const templateColumns: DataTableColumns<TaskTemplate> = [
  { title: '模板名称', key: 'name', minWidth: 160 },
  { title: '说明', key: 'description', ellipsis: { tooltip: true } },
  { title: '步骤数', key: 'action_flow', width: 90, render: (row) => `${(row.action_flow || []).length} 步` },
  {
    title: '引用任务',
    key: 'ref_count',
    width: 100,
    render: (row) =>
      h(NTag, { size: 'small', round: true, bordered: false }, { default: () => `${row.ref_count} 个` })
  },
  {
    title: '操作',
    key: 'actions',
    width: 150,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: 'tiny', onClick: () => editTemplate(row) }, { default: () => '编辑' }),
          h(
            NPopconfirm,
            { onPositiveClick: () => removeTemplate(row) },
            {
              trigger: () => h(NButton, { size: 'tiny', type: 'error', quaternary: true }, { default: () => '删除' }),
              default: () => '仅删除模板，不影响已创建的任务。确定？'
            }
          )
        ]
      })
  }
]

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">签到任务</h2>
        <p class="page-desc">定时执行、随机延迟、失败重试与补跑都在这里配置。</p>
      </div>
      <n-space>
        <n-button :loading="loading" @click="load">刷新</n-button>
        <n-button type="primary" @click="router.push({ name: 'task-create' })">新建任务</n-button>
      </n-space>
    </div>

    <n-tabs type="line" animated>
      <n-tab-pane name="tasks" :tab="`任务（${tasks.length}）`">
        <n-card class="soft-card" size="small">
          <n-data-table
            v-if="tasks.length"
            :columns="columns"
            :data="tasks"
            :bordered="false"
            :loading="loading"
            size="small"
            :row-key="(row: Task) => row.id"
            :scroll-x="1400"
          />
          <div v-else class="empty-hint">还没有任务。点击「新建任务」，用可视化编辑器拖一个签到流程出来。</div>
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="templates" :tab="`任务模板（${templates.length}）`">
        <n-alert type="info" :show-icon="true" style="margin-bottom: 14px">
          模板用于复用同一套动作流。修改模板会<b>同步更新</b>所有引用它的任务，适合批量维护。
        </n-alert>
        <n-card class="soft-card" size="small">
          <n-data-table
            v-if="templates.length"
            :columns="templateColumns"
            :data="templates"
            :bordered="false"
            size="small"
            :row-key="(row: TaskTemplate) => row.id"
          />
          <div v-else class="empty-hint">
            还没有模板。在任务编辑页把当前动作流「另存为模板」即可创建。
          </div>
        </n-card>
      </n-tab-pane>
    </n-tabs>

    <n-modal
      v-model:show="detailShow"
      preset="card"
      title="任务详情"
      style="max-width: 720px; width: 94vw"
      :bordered="false"
    >
      <n-descriptions v-if="detailTask" :column="2" label-placement="top" bordered size="small">
        <n-descriptions-item label="任务名">{{ detailTask.name }}</n-descriptions-item>
        <n-descriptions-item label="账号">{{ detailTask.account_name }}</n-descriptions-item>
        <n-descriptions-item label="调度">
          {{ detailTask.schedule_text }}（{{ detailTask.schedule_type }}: {{ detailTask.schedule_value }}）
        </n-descriptions-item>
        <n-descriptions-item label="时区">{{ detailTask.timezone || '跟随全局' }}</n-descriptions-item>
        <n-descriptions-item label="下一个执行">
          {{ detailTask.next_runs?.length ? formatTime(detailTask.next_runs[0]) : '—' }}
        </n-descriptions-item>
        <n-descriptions-item label="最后执行">{{ formatTime(detailTask.last_run_at) }}</n-descriptions-item>
        <n-descriptions-item label="成功规则" :span="2">
          {{ detailTask.success_rule?.mode }} · {{ (detailTask.success_rule?.keywords || []).join(' / ') || '（收到回复即成功）' }}
        </n-descriptions-item>
        <n-descriptions-item label="重试策略" :span="2">
          最多 {{ detailTask.retry_policy?.max }} 次，间隔 {{ detailTask.retry_policy?.interval_sec }}s，
          {{ detailTask.retry_policy?.until_success ? '重试到成功' : '按次数上限' }}
        </n-descriptions-item>
        <n-descriptions-item label="最后消息" :span="2">
          {{ detailTask.last_message || '—' }}
        </n-descriptions-item>
        <n-descriptions-item label="动作流" :span="2">
          <n-space vertical :size="6">
            <div v-for="(step, i) in detailTask.action_flow" :key="i" class="mono">
              {{ i + 1 }}. {{ step.type }} — {{ JSON.stringify(step).slice(0, 120) }}
            </div>
          </n-space>
        </n-descriptions-item>
      </n-descriptions>
    </n-modal>

    <n-modal
      v-model:show="templateShow"
      preset="card"
      title="编辑模板"
      style="max-width: 460px"
      :bordered="false"
    >
      <n-alert type="warning" :show-icon="true" style="margin-bottom: 14px">
        保存后会同步覆盖引用该模板的 {{ editingTemplate?.ref_count ?? 0 }} 个任务的动作流。
      </n-alert>
      <n-form label-placement="top">
        <n-form-item label="模板名称">
          <n-input v-model:value="templateForm.name" />
        </n-form-item>
        <n-form-item label="说明">
          <n-input v-model:value="templateForm.description" type="textarea" :rows="3" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="templateShow = false">取消</n-button>
          <n-button type="primary" @click="submitTemplate">保存并同步</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
