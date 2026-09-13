<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NDivider,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NSpace,
  NSwitch,
  NTag
} from 'naive-ui'
import { authApi, extractError, systemApi, type SystemInfo } from '@/api'
import { feedback } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'
import { formatBytes } from '@/utils/format'

const auth = useAuthStore()
const info = ref<SystemInfo | null>(null)
const loading = ref(false)
const saving = ref(false)
const rebuilding = ref(false)
const catching = ref(false)

const settings = ref({
  timezone: 'Asia/Shanghai',
  tg_proxy: '',
  default_random_delay_sec: 300,
  default_retry_max: 3,
  default_retry_interval: 3600,
  task_timeout_sec: 300,
  step_timeout_sec: 60,
  max_concurrent_tasks: 3,
  ai_enabled: false,
  openai_api_key: '',
  openai_base_url: 'https://api.openai.com/v1',
  openai_model: 'gpt-4o-mini'
})

const passwordForm = ref({ old_password: '', new_password: '', confirm: '' })
const passwordSaving = ref(false)

async function load() {
  loading.value = true
  try {
    const [i, s] = await Promise.all([systemApi.info(), systemApi.settings()])
    info.value = i
    settings.value = { ...settings.value, ...s }
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  saving.value = true
  try {
    const payload: Record<string, any> = { ...settings.value }
    if (payload.openai_api_key === '********') delete payload.openai_api_key
    await systemApi.saveSettings(payload)
    feedback.ok('设置已保存并生效')
    await load()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    saving.value = false
  }
}

async function rebuild() {
  rebuilding.value = true
  try {
    const res = await systemApi.rebuild()
    feedback.ok(res.message)
    await load()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    rebuilding.value = false
  }
}

async function catchUp() {
  catching.value = true
  try {
    const res = await systemApi.catchUp()
    feedback.info(res.message)
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    catching.value = false
  }
}

async function changePassword() {
  if (!passwordForm.value.old_password || !passwordForm.value.new_password) {
    feedback.warn('请填写完整')
    return
  }
  if (passwordForm.value.new_password !== passwordForm.value.confirm) {
    feedback.warn('两次输入的新密码不一致')
    return
  }
  passwordSaving.value = true
  try {
    await authApi.changePassword(passwordForm.value.old_password, passwordForm.value.new_password)
    feedback.ok('密码已更新')
    passwordForm.value = { old_password: '', new_password: '', confirm: '' }
    auth.markPasswordChanged()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    passwordSaving.value = false
  }
}

function backup() {
  window.open(systemApi.backupUrl(), '_blank')
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">系统设置</h2>
        <p class="page-desc">全局代理、时区、默认调度参数、AI 能力与数据备份。</p>
      </div>
      <n-button :loading="loading" @click="load">刷新</n-button>
    </div>

    <n-alert v-if="auth.mustChangePassword" type="warning" :show-icon="true">
      你正在使用默认密码，请立刻在下方「修改密码」中更换，否则面板存在安全风险。
    </n-alert>

    <n-grid :cols="2" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
      <n-gi span="2 m:1">
        <n-card class="soft-card" title="运行信息" size="small">
          <n-descriptions v-if="info" :column="1" label-placement="left" size="small" bordered>
            <n-descriptions-item label="版本">{{ info.app_name }} v{{ info.version }}</n-descriptions-item>
            <n-descriptions-item label="调度器">
              <n-tag :type="info.scheduler_running ? 'success' : 'error'" size="small" round :bordered="false">
                {{ info.scheduler_running ? '运行中' : '已停止' }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="在线账号">{{ info.accounts_online }}</n-descriptions-item>
            <n-descriptions-item label="任务">
              {{ info.tasks_enabled }} 启用 / {{ info.tasks_total }} 总计
            </n-descriptions-item>
            <n-descriptions-item label="数据目录">
              <span class="mono">{{ info.data_dir }}</span>
            </n-descriptions-item>
            <n-descriptions-item label="数据库大小">{{ formatBytes(info.db_size) }}</n-descriptions-item>
            <n-descriptions-item label="当前代理">{{ info.proxy }}</n-descriptions-item>
            <n-descriptions-item label="AI 识图">
              <n-tag :type="info.ai_enabled ? 'success' : 'default'" size="small" round :bordered="false">
                {{ info.ai_enabled ? '已启用' : '未启用' }}
              </n-tag>
            </n-descriptions-item>
          </n-descriptions>

          <n-divider style="margin: 16px 0" />

          <n-space>
            <n-button size="small" :loading="rebuilding" @click="rebuild">重建调度任务</n-button>
            <n-button size="small" :loading="catching" @click="catchUp">立即补跑未完成任务</n-button>
            <n-button size="small" @click="backup">下载数据库备份</n-button>
          </n-space>
        </n-card>
      </n-gi>

      <n-gi span="2 m:1">
        <n-card class="soft-card" title="全局设置" size="small">
          <n-form label-placement="top" size="small">
            <n-grid :cols="2" :x-gap="12">
              <n-gi>
                <n-form-item label="时区">
                  <n-input v-model:value="settings.timezone" placeholder="Asia/Shanghai" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="全局代理">
                  <n-input v-model:value="settings.tg_proxy" placeholder="socks5://host.docker.internal:7890" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="默认随机延迟（秒）">
                  <n-input-number v-model:value="settings.default_random_delay_sec" :min="0" :step="30" style="width: 100%" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="默认最大重试">
                  <n-input-number v-model:value="settings.default_retry_max" :min="0" :max="50" style="width: 100%" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="默认重试间隔（秒）">
                  <n-input-number v-model:value="settings.default_retry_interval" :min="30" :step="300" style="width: 100%" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="任务总超时（秒）">
                  <n-input-number v-model:value="settings.task_timeout_sec" :min="30" :step="30" style="width: 100%" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="单步超时（秒）">
                  <n-input-number v-model:value="settings.step_timeout_sec" :min="10" :step="10" style="width: 100%" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="任务最大并发">
                  <n-input-number v-model:value="settings.max_concurrent_tasks" :min="1" :max="10" style="width: 100%" />
                </n-form-item>
              </n-gi>
            </n-grid>

            <n-divider style="margin: 4px 0 14px">AI 识图答题（可选）</n-divider>

            <n-grid :cols="2" :x-gap="12">
              <n-gi>
                <n-form-item label="启用 AI">
                  <n-switch v-model:value="settings.ai_enabled" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="模型">
                  <n-input v-model:value="settings.openai_model" placeholder="gpt-4o-mini" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="API Key">
                  <n-input
                    v-model:value="settings.openai_api_key"
                    type="password"
                    show-password-on="click"
                    placeholder="sk-..."
                  />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="Base URL">
                  <n-input v-model:value="settings.openai_base_url" placeholder="https://api.openai.com/v1" />
                </n-form-item>
              </n-gi>
            </n-grid>

            <n-space justify="end">
              <n-button type="primary" :loading="saving" @click="saveSettings">保存设置</n-button>
            </n-space>
          </n-form>
        </n-card>
      </n-gi>

      <n-gi span="2">
        <n-card class="soft-card" title="修改密码" size="small">
          <n-form label-placement="top" size="small">
            <n-grid :cols="3" :x-gap="12">
              <n-gi>
                <n-form-item label="原密码">
                  <n-input v-model:value="passwordForm.old_password" type="password" show-password-on="click" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="新密码">
                  <n-input v-model:value="passwordForm.new_password" type="password" show-password-on="click" />
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item label="确认新密码">
                  <n-input v-model:value="passwordForm.confirm" type="password" show-password-on="click" />
                </n-form-item>
              </n-gi>
            </n-grid>
            <n-space justify="end">
              <n-button :loading="passwordSaving" @click="changePassword">更新密码</n-button>
            </n-space>
          </n-form>
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>
