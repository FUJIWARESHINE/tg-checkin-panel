<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NCard, NForm, NFormItem, NInput, NAlert } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import { feedback } from '@/utils/feedback'
import { extractError } from '@/api'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorText = ref('')

async function submit() {
  if (!username.value || !password.value) {
    errorText.value = '请填写用户名和密码'
    return
  }
  loading.value = true
  errorText.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    feedback.ok('登录成功')
    const redirect = (route.query.redirect as string) || '/'
    router.replace(redirect)
  } catch (error) {
    errorText.value = extractError(error)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div
    style="
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: linear-gradient(135deg, #e8f6fd 0%, #f7fbfd 45%, #eef3ff 100%);
    "
  >
    <n-card
      class="soft-card"
      style="width: 100%; max-width: 420px; box-shadow: 0 18px 48px rgba(34, 158, 217, 0.14)"
    >
      <div style="text-align: center; margin-bottom: 22px">
        <div
          style="
            width: 52px;
            height: 52px;
            border-radius: 16px;
            background: #229ed9;
            color: #fff;
            font-weight: 600;
            line-height: 52px;
            margin: 0 auto 12px;
            font-size: 17px;
          "
        >
          TG
        </div>
        <h1 style="font-size: 19px; font-weight: 600; margin: 0 0 6px">TG 自动签到面板</h1>
        <p style="font-size: 13px; opacity: 0.6; margin: 0">
          Telegram 定时签到 · 可视化任务 · 详细推送
        </p>
      </div>

      <n-alert v-if="errorText" type="error" :show-icon="true" style="margin-bottom: 16px">
        {{ errorText }}
      </n-alert>

      <n-form :show-label="false" @submit.prevent="submit">
        <n-form-item>
          <n-input v-model:value="username" placeholder="管理员账号" size="large" @keyup.enter="submit" />
        </n-form-item>
        <n-form-item>
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            placeholder="密码"
            size="large"
            @keyup.enter="submit"
          />
        </n-form-item>
        <n-button type="primary" size="large" block :loading="loading" @click="submit">
          登 录
        </n-button>
      </n-form>

      <p style="font-size: 12px; opacity: 0.5; margin: 16px 0 0; text-align: center; line-height: 1.7">
        默认账号由环境变量 <code>ADMIN_USERNAME</code> / <code>ADMIN_PASSWORD</code> 决定<br />
        首次登录后请到「系统设置」修改默认密码
      </p>
    </n-card>
  </div>
</template>
