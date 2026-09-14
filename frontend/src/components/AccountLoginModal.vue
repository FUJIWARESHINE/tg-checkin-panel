<script setup lang="ts">
import { ref, watch } from 'vue'
import { NAlert, NButton, NForm, NFormItem, NInput, NModal, NSpace, NStep, NSteps } from 'naive-ui'
import { accountApi, extractError, type Account } from '@/api'
import { feedback } from '@/utils/feedback'

const props = defineProps<{ show: boolean; account: Account | null }>()
const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'success'): void
}>()

const step = ref(1)
const phone = ref('')
const code = ref('')
const password = ref('')
const loginToken = ref('')
const loading = ref(false)
const errorText = ref('')

function reset() {
  step.value = 1
  phone.value = props.account?.phone?.replace(/\*/g, '') ?? ''
  code.value = ''
  password.value = ''
  loginToken.value = ''
  errorText.value = ''
}

watch(
  () => props.show,
  (visible) => {
    if (visible) reset()
  }
)

function close() {
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

    <p style="font-size: 12px; opacity: 0.55; margin: 0 0 12px; line-height: 1.7">
      验证码会发送到该账号已登录的 Telegram 客户端；若收不到，请确认手机号带国家区号且网络/代理可用。
    </p>

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
  </n-modal>
</template>
