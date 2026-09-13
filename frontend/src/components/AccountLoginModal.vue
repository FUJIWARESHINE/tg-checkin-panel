<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NForm,
  NFormItem,
  NImage,
  NInput,
  NModal,
  NSpace,
  NStep,
  NSteps,
  NTabs,
  NTabPane,
  NTag
} from 'naive-ui'
import { accountApi, extractError, type Account } from '@/api'
import { feedback } from '@/utils/feedback'

const props = defineProps<{ show: boolean; account: Account | null }>()
const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'success'): void
}>()

const mode = ref<'phone' | 'qr'>('phone')
const step = ref(1)
const phone = ref('')
const code = ref('')
const password = ref('')
const loginToken = ref('')
const qrUrl = ref('')
const qrState = ref('pending')
const qrMessage = ref('')
const loading = ref(false)
const errorText = ref('')
let timer: number | undefined

function reset() {
  step.value = 1
  phone.value = props.account?.phone?.replace(/\*/g, '') ?? ''
  code.value = ''
  password.value = ''
  loginToken.value = ''
  qrUrl.value = ''
  qrState.value = 'pending'
  qrMessage.value = ''
  errorText.value = ''
  stopPolling()
}

function stopPolling() {
  if (timer) {
    window.clearInterval(timer)
    timer = undefined
  }
}

watch(
  () => props.show,
  (visible) => {
    if (visible) {
      reset()
    } else {
      stopPolling()
    }
  }
)

function close() {
  stopPolling()
  emit('update:show', false)
}

async function sendCode() {
  if (!props.account) return
  if (!phone.value.trim()) {
    errorText.value = '请填写手机号（含国家区号，例如 +8613800000000）'
    return
  }
  loading.value = true
  errorText.value = ''
  try {
    const res = await accountApi.sendCode(props.account.id, phone.value.trim())
    loginToken.value = res.login_token
    step.value = 2
    feedback.ok('验证码已发送，请到 Telegram 客户端查看')
  } catch (error) {
    errorText.value = extractError(error)
  } finally {
    loading.value = false
  }
}

async function verifyCode() {
  if (!code.value.trim()) {
    errorText.value = '请输入验证码'
    return
  }
  loading.value = true
  errorText.value = ''
  try {
    const res = await accountApi.verifyCode(loginToken.value, code.value.trim())
    if (res.state === 'need_password') {
      step.value = 3
    } else {
      feedback.ok('登录成功')
      emit('success')
      close()
    }
  } catch (error) {
    errorText.value = extractError(error)
  } finally {
    loading.value = false
  }
}

async function verifyPassword() {
  loading.value = true
  errorText.value = ''
  try {
    await accountApi.verifyPassword(loginToken.value, password.value)
    feedback.ok('两步验证通过，登录成功')
    emit('success')
    close()
  } catch (error) {
    errorText.value = extractError(error)
  } finally {
    loading.value = false
  }
}

async function startQr() {
  if (!props.account) return
  loading.value = true
  errorText.value = ''
  try {
    const res = await accountApi.startQr(props.account.id)
    loginToken.value = res.login_token
    qrUrl.value = res.url
    qrState.value = 'pending'
    qrMessage.value = '请用手机 Telegram 扫描二维码'
    stopPolling()
    timer = window.setInterval(async () => {
      try {
        const poll = await accountApi.pollQr(loginToken.value)
        qrState.value = poll.state
        qrMessage.value = poll.message
        if (poll.state === 'done') {
          stopPolling()
          feedback.ok('扫码登录成功')
          emit('success')
          close()
        } else if (poll.state === 'need_password') {
          stopPolling()
        } else if (poll.state === 'error') {
          stopPolling()
        }
      } catch (error) {
        stopPolling()
        errorText.value = extractError(error)
      }
    }, 2500)
  } catch (error) {
    errorText.value = extractError(error)
  } finally {
    loading.value = false
  }
}

function switchMode(value: string) {
  mode.value = value as 'phone' | 'qr'
  stopPolling()
  errorText.value = ''
  if (value === 'qr') startQr()
}
</script>

<template>
  <n-modal
    :show="show"
    preset="card"
    style="max-width: 560px; width: 92vw"
    :title="`登录账号：${account?.name ?? ''}`"
    :bordered="false"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <n-alert v-if="errorText" type="error" style="margin-bottom: 14px">{{ errorText }}</n-alert>

    <n-tabs :value="mode" type="segment" @update:value="switchMode">
      <n-tab-pane name="phone" tab="手机号登录">
        <n-steps :current="step" size="small" style="margin: 8px 0 18px">
          <n-step title="获取验证码" />
          <n-step title="填写验证码" />
          <n-step title="两步验证" />
        </n-steps>

        <n-form :show-label="false">
          <n-form-item v-if="step === 1">
            <n-input
              v-model:value="phone"
              placeholder="+8613800000000"
              :disabled="loading"
              @keyup.enter="sendCode"
            />
          </n-form-item>
          <n-form-item v-else-if="step === 2">
            <n-input
              v-model:value="code"
              placeholder="Telegram 收到的 5 位验证码"
              :disabled="loading"
              @keyup.enter="verifyCode"
            />
          </n-form-item>
          <n-form-item v-else>
            <n-input
              v-model:value="password"
              type="password"
              show-password-on="click"
              placeholder="两步验证密码"
              :disabled="loading"
              @keyup.enter="verifyPassword"
            />
          </n-form-item>
        </n-form>

        <n-space justify="end">
          <n-button v-if="step === 1" type="primary" :loading="loading" @click="sendCode">
            发送验证码
          </n-button>
          <n-button v-else-if="step === 2" type="primary" :loading="loading" @click="verifyCode">
            提交验证码
          </n-button>
          <n-button v-else type="primary" :loading="loading" @click="verifyPassword">
            提交并登录
          </n-button>
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="qr" tab="二维码登录">
        <div style="text-align: center; padding: 8px 0 4px">
          <n-image
            v-if="qrUrl"
            :src="qrUrl"
            width="200"
            :img-props="{ style: 'border-radius: 10px; padding: 8px; background: #fff' }"
          />
          <div v-else style="height: 200px; display: grid; place-items: center; opacity: 0.6">
            正在生成二维码…
          </div>
          <div style="margin-top: 12px">
            <n-tag
              :type="qrState === 'error' ? 'error' : qrState === 'need_password' ? 'warning' : 'info'"
              round
              :bordered="false"
            >
              {{ qrMessage || '等待扫码' }}
            </n-tag>
          </div>
          <p style="font-size: 12px; opacity: 0.55; margin-top: 10px; line-height: 1.7">
            手机 Telegram → 设置 → 设备 → 扫描二维码
          </p>
        </div>

        <n-form v-if="qrState === 'need_password'" :show-label="false" style="margin-top: 8px">
          <n-form-item>
            <n-input
              v-model:value="password"
              type="password"
              show-password-on="click"
              placeholder="该账号已开启两步验证，请输入密码"
            />
          </n-form-item>
        </n-form>
        <n-space justify="end">
          <n-button size="small" @click="startQr">刷新二维码</n-button>
          <n-button
            v-if="qrState === 'need_password'"
            type="primary"
            :loading="loading"
            @click="verifyPassword"
          >
            提交两步验证密码
          </n-button>
        </n-space>
      </n-tab-pane>
    </n-tabs>
  </n-modal>
</template>
