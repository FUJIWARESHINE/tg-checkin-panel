<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NCheckboxGroup,
  NDivider,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NIcon,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  NTooltip
} from 'naive-ui'
import { AddOutline, CloseOutline } from '@vicons/ionicons5'
import ActionFlowEditor from '@/components/ActionFlowEditor.vue'
import { defaultFlow } from '@/components/actionFlowMeta'
import {
  accountApi,
  extractError,
  notifyApi,
  taskApi,
  type Account,
  type ActionStep,
  type DialogItem,
  type NotifyChannel,
  type Target
} from '@/api'
import { feedback } from '@/utils/feedback'
import { EVENT_LABELS } from '@/api'
import { formatTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const taskId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => taskId.value !== null)

const accounts = ref<Account[]>([])
const channels = ref<NotifyChannel[]>([])
const loading = ref(false)
const saving = ref(false)

const form = ref({
  name: '',
  remark: '',
  account_id: null as number | null,
  template_id: null as number | null,
  targets: [] as Target[],
  action_flow: [] as ActionStep[],
  schedule_type: 'cron' as 'cron' | 'daily' | 'interval',
  schedule_value: '0 8 * * *',
  timezone: '',
  random_delay_sec: 300,
  timeout_sec: 300,
  success_rule: { mode: 'contains' as 'contains' | 'regex' | 'exact' | 'all', keywords: [] as string[] },
  retry_policy: { max: 3, interval_sec: 3600, until_success: false },
  catch_up: false,
  notify_channel_ids: [] as number[],
  notify_on: ['success', 'fail', 'auth_expired'] as string[],
  enabled: true
})

const keywordsText = ref('签到成功\n已签到\n获得\n积分')
const targetInput = ref('')
const preview = ref<{ ok: boolean; text?: string; next_runs?: string[]; message?: string }>({ ok: false })

const dialogDrawer = ref(false)
const dialogs = ref<DialogItem[]>([])
const dialogsLoading = ref(false)

const templateSaveShow = ref(false)
const templateName = ref('')
const templateDesc = ref('')

const accountOptions = computed(() =>
  accounts.value.map((a) => ({ label: `${a.name}（${a.status === 'online' ? '在线' : '离线'}）`, value: a.id }))
)

const channelOptions = computed(() =>
  channels.value.map((c) => ({ label: `${c.name}（${c.type}）`, value: c.id }))
)

const scheduleTypeOptions = [
  { label: 'Cron 表达式', value: 'cron' },
  { label: '每天定点', value: 'daily' },
  { label: '固定间隔', value: 'interval' }
]

const cronPlaceholder = computed(() => {
  if (form.value.schedule_type === 'cron') return '0 8 * * *   （每天 08:00）'
  if (form.value.schedule_type === 'daily') return '08:00 或 08:00:30'
  return '12h、30m、90s'
})

async function load() {
  loading.value = true
  try {
    const [accs, chans] = await Promise.all([accountApi.list(), notifyApi.list()])
    accounts.value = accs
    channels.value = chans

    if (isEdit.value && taskId.value) {
      const task = await taskApi.get(taskId.value)
      form.value = {
        name: task.name,
        remark: task.remark,
        account_id: task.account_id,
        template_id: task.template_id,
        targets: (task.targets || []).map((t) => ({ ...t })),
        action_flow: (task.action_flow || []).map((s) => ({ ...s })),
        schedule_type: task.schedule_type,
        schedule_value: task.schedule_value,
        timezone: task.timezone,
        random_delay_sec: task.random_delay_sec,
        timeout_sec: task.timeout_sec,
        success_rule: { ...task.success_rule },
        retry_policy: { ...task.retry_policy },
        catch_up: task.catch_up,
        notify_channel_ids: [...(task.notify_channel_ids || [])],
        notify_on: [...(task.notify_on || [])],
        enabled: task.enabled
      }
      keywordsText.value = (task.success_rule?.keywords || []).join('\n')
    } else {
      if (accs.length === 1) form.value.account_id = accs[0].id
      form.value.action_flow = defaultFlow()
    }
    await refreshPreview()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    loading.value = false
  }
}

async function refreshPreview() {
  try {
    preview.value = await taskApi.previewSchedule({
      schedule_type: form.value.schedule_type,
      schedule_value: form.value.schedule_value,
      timezone: form.value.timezone
    })
  } catch {
    preview.value = { ok: false }
  }
}

watch(
  () => [form.value.schedule_type, form.value.schedule_value, form.value.timezone],
  () => {
    if (form.value.schedule_value) refreshPreview()
  }
)

function addTarget() {
  const value = targetInput.value.trim()
  if (!value) return
  if (form.value.targets.some((t) => t.chat === value)) {
    feedback.warn('该目标已存在')
    return
  }
  form.value.targets.push({ chat: value, thread_id: null })
  targetInput.value = ''
}

function removeTarget(index: number) {
  form.value.targets.splice(index, 1)
}

async function openDialogs() {
  if (!form.value.account_id) {
    feedback.warn('请先选择账号')
    return
  }
  dialogDrawer.value = true
  dialogsLoading.value = true
  dialogs.value = []
  try {
    dialogs.value = await accountApi.dialogs(form.value.account_id)
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    dialogsLoading.value = false
  }
}

function pickDialog(item: DialogItem) {
  if (!form.value.targets.some((t) => t.chat === item.username)) {
    form.value.targets.push({ chat: item.username, thread_id: null })
  }
  feedback.ok(`已添加 ${item.username}`)
}

function buildPayload() {
  const keywords = keywordsText.value
    .split('\n')
    .map((k) => k.trim())
    .filter(Boolean)
  return {
    ...form.value,
    targets: form.value.targets,
    action_flow: form.value.action_flow,
    success_rule: { mode: form.value.success_rule.mode, keywords },
    retry_policy: form.value.retry_policy
  }
}

async function save(runAfter = false) {
  if (!form.value.name.trim()) {
    feedback.warn('请填写任务名称')
    return
  }
  if (!form.value.account_id) {
    feedback.warn('请选择执行账号')
    return
  }
  if (!form.value.targets.length) {
    feedback.warn('至少配置一个签到目标')
    return
  }
  if (!form.value.action_flow.length) {
    feedback.warn('动作流不能为空')
    return
  }
  saving.value = true
  try {
    const payload = buildPayload()
    let saved
    if (isEdit.value && taskId.value) {
      saved = await taskApi.update(taskId.value, payload)
    } else {
      saved = await taskApi.create(payload)
    }
    feedback.ok('任务已保存')
    if (runAfter) {
      await taskApi.run(saved.id, true)
      feedback.info('已触发一次立即执行，可在「签到记录」查看结果')
    }
    router.push({ name: 'tasks' })
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    saving.value = false
  }
}

async function saveAsTemplate() {
  if (!templateName.value.trim()) {
    feedback.warn('请填写模板名称')
    return
  }
  try {
    const keywords = keywordsText.value
      .split('\n')
      .map((k) => k.trim())
      .filter(Boolean)
    await taskApi.createTemplate({
      name: templateName.value.trim(),
      description: templateDesc.value,
      action_flow: form.value.action_flow,
      success_rule: { mode: form.value.success_rule.mode, keywords },
      retry_policy: form.value.retry_policy
    })
    feedback.ok('模板已保存，可在任务列表的「任务模板」中管理')
    templateSaveShow.value = false
    templateName.value = ''
    templateDesc.value = ''
  } catch (error) {
    feedback.error(extractError(error))
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">{{ isEdit ? '编辑任务' : '新建任务' }}</h2>
        <p class="page-desc">配置签到目标、动作流、调度与推送订阅。</p>
      </div>
      <n-space>
        <n-button @click="router.push({ name: 'tasks' })">返回列表</n-button>
        <n-button type="primary" :loading="saving" @click="save(false)">保存</n-button>
        <n-button type="primary" ghost :loading="saving" @click="save(true)">保存并立即执行</n-button>
      </n-space>
    </div>

    <n-grid :cols="3" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
      <n-gi span="3 m:2">
        <n-card class="soft-card" title="基础信息" size="small">
          <n-form label-placement="top">
            <n-grid :cols="2" :x-gap="16">
              <n-gi>
                <n-form-item label="任务名称">
                  <n-input v-model:value="form.name" placeholder="例如：每日签到 XX Bot" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="执行账号">
                  <n-select
                    v-model:value="form.account_id"
                    :options="accountOptions"
                    placeholder="选择一个已登录的账号"
                  />
                </n-form-item>
              </n-gi>
              <n-gi span="2">
                <n-form-item label="备注（可选）">
                  <n-input v-model:value="form.remark" placeholder="便于区分多个任务" />
                </n-form-item>
              </n-gi>
              <n-gi span="2">
                <n-form-item label="签到目标">
                  <div style="width: 100%">
                    <n-space style="margin-bottom: 8px" :size="8" align="center">
                      <n-input
                        v-model:value="targetInput"
                        placeholder="@botusername 或 -1001234567890"
                        style="width: 320px"
                        @keyup.enter="addTarget"
                      />
                      <n-button @click="addTarget">
                        <template #icon><n-icon><AddOutline /></n-icon></template>
                        添加
                      </n-button>
                      <n-button quaternary @click="openDialogs">从会话列表选择</n-button>
                    </n-space>
                    <n-space :size="8" style="flex-wrap: wrap">
                      <n-tag
                        v-for="(target, index) in form.targets"
                        :key="target.chat"
                        closable
                        round
                        :bordered="false"
                        @close="removeTarget(index)"
                      >
                        {{ target.chat }}
                      </n-tag>
                      <span v-if="!form.targets.length" style="font-size: 12px; opacity: 0.55">
                        还没有目标，添加一个机器人用户名或群组 ID
                      </span>
                    </n-space>
                  </div>
                </n-form-item>
              </n-gi>
            </n-grid>
          </n-form>
        </n-card>

        <n-card class="soft-card" size="small" style="margin-top: 16px">
          <template #header>
            <n-space align="center" justify="space-between" style="width: 100%">
              <span>动作流编排</span>
              <n-button size="tiny" quaternary @click="templateSaveShow = true">另存为模板</n-button>
            </n-space>
          </template>
          <action-flow-editor v-model="form.action_flow" />
        </n-card>
      </n-gi>

      <n-gi span="3 m:1">
        <n-card class="soft-card" title="调度设置" size="small">
          <n-form label-placement="top" size="small">
            <n-form-item label="调度方式">
              <n-select v-model:value="form.schedule_type" :options="scheduleTypeOptions" />
            </n-form-item>
            <n-form-item label="表达式">
              <n-input v-model:value="form.schedule_value" :placeholder="cronPlaceholder" />
            </n-form-item>
            <n-alert
              :type="preview.ok ? 'success' : 'warning'"
              :bordered="false"
              style="margin-bottom: 12px; font-size: 12px"
            >
              <span v-if="preview.ok">
                {{ preview.text }}
                <div v-if="preview.next_runs?.length" style="margin-top: 4px; opacity: 0.8">
                  下次：{{ preview.next_runs.slice(0, 3).map((t) => formatTime(t)).join(' ｜ ') }}
                </div>
              </span>
              <span v-else>{{ preview.message || '表达式待填写' }}</span>
            </n-alert>
            <n-form-item label="时区（留空跟随全局）">
              <n-input v-model:value="form.timezone" placeholder="Asia/Shanghai" />
            </n-form-item>
            <n-form-item label="随机延迟（秒，模拟真人）">
              <n-input-number v-model:value="form.random_delay_sec" :min="0" :step="30" style="width: 100%" />
            </n-form-item>
            <n-form-item label="单次执行超时（秒）">
              <n-input-number v-model:value="form.timeout_sec" :min="30" :step="30" style="width: 100%" />
            </n-form-item>
            <n-form-item label="错过后自动补跑">
              <n-switch v-model:value="form.catch_up" />
            </n-form-item>
            <n-form-item label="启用任务">
              <n-switch v-model:value="form.enabled" />
            </n-form-item>
          </n-form>
        </n-card>

        <n-card class="soft-card" title="成功判定" size="small" style="margin-top: 16px">
          <n-form label-placement="top" size="small">
            <n-form-item label="匹配方式">
              <n-select
                v-model:value="form.success_rule.mode"
                :options="[
                  { label: '包含关键词', value: 'contains' },
                  { label: '正则匹配', value: 'regex' },
                  { label: '完全相等', value: 'exact' },
                  { label: '只要有回复就算成功', value: 'all' }
                ]"
              />
            </n-form-item>
            <n-form-item label="成功关键词（每行一个）">
              <n-input
                v-model:value="keywordsText"
                type="textarea"
                :rows="4"
                placeholder="签到成功&#10;已签到&#10;获得"
              />
            </n-form-item>
          </n-form>
        </n-card>

        <n-card class="soft-card" title="重试策略" size="small" style="margin-top: 16px">
          <n-form label-placement="top" size="small">
            <n-form-item label="最大重试次数">
              <n-input-number v-model:value="form.retry_policy.max" :min="0" :max="50" style="width: 100%" />
            </n-form-item>
            <n-form-item label="重试间隔（秒）">
              <n-input-number
                v-model:value="form.retry_policy.interval_sec"
                :min="30"
                :step="300"
                style="width: 100%"
              />
            </n-form-item>
            <n-form-item label="重试到成功为止">
              <n-switch v-model:value="form.retry_policy.until_success" />
            </n-form-item>
          </n-form>
        </n-card>

        <n-card class="soft-card" title="推送订阅" size="small" style="margin-top: 16px">
          <n-form label-placement="top" size="small">
            <n-form-item label="推送渠道">
              <n-select
                v-model:value="form.notify_channel_ids"
                multiple
                :options="channelOptions"
                placeholder="选择要接收通知的渠道"
              />
            </n-form-item>
            <n-form-item label="订阅事件">
              <n-checkbox-group v-model:value="form.notify_on">
                <n-space vertical :size="6">
                  <n-checkbox v-for="(label, key) in EVENT_LABELS" :key="key" :value="key" :label="label" />
                </n-space>
              </n-checkbox-group>
            </n-form-item>
          </n-form>
          <n-alert v-if="!channels.length" type="info" :bordered="false" style="font-size: 12px">
            还没有推送渠道，去「推送设置」添加一个 Telegram Bot 渠道。
          </n-alert>
        </n-card>
      </n-gi>
    </n-grid>

    <n-drawer v-model:show="dialogDrawer" :width="480" placement="right">
      <n-drawer-content title="选择签到目标" closable>
        <p style="font-size: 12px; opacity: 0.6; margin-top: 0">点击条目即可加入目标列表。</p>
        <n-empty
          v-if="!dialogsLoading && !dialogs.length"
          description="没有拉到会话，请确认账号已登录"
          style="margin-top: 40px"
        />
        <n-space vertical :size="8">
          <n-card
            v-for="item in dialogs"
            :key="item.id"
            size="small"
            hoverable
            style="cursor: pointer"
            @click="pickDialog(item)"
          >
            <n-space align="center" justify="space-between">
              <span style="font-size: 13px">{{ item.title }}</span>
              <n-space :size="6">
                <n-tag size="tiny" :bordered="false" :type="item.is_bot ? 'info' : 'default'">
                  {{ item.is_bot ? '机器人' : item.kind }}
                </n-tag>
                <span class="mono" style="opacity: 0.7">{{ item.username }}</span>
              </n-space>
            </n-space>
          </n-card>
        </n-space>
      </n-drawer-content>
    </n-drawer>

    <n-modal v-model:show="templateSaveShow" preset="card" title="另存为模板" style="max-width: 440px" :bordered="false">
      <n-form label-placement="top">
        <n-form-item label="模板名称">
          <n-input v-model:value="templateName" placeholder="例如：标准文字签到" />
        </n-form-item>
        <n-form-item label="说明">
          <n-input v-model:value="templateDesc" type="textarea" :rows="3" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="templateSaveShow = false">取消</n-button>
          <n-button type="primary" @click="saveAsTemplate">保存模板</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
