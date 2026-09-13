<script setup lang="ts">
import { computed, onMounted } from 'vue'
import {
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  NNotificationProvider,
  darkTheme,
  dateZhCN,
  zhCN,
  type GlobalThemeOverrides
} from 'naive-ui'
import FeedbackBridge from '@/components/FeedbackBridge.vue'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
themeStore.init()

const theme = computed(() => (themeStore.mode === 'dark' ? darkTheme : null))

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#229ED9',
    primaryColorHover: '#3BB0E5',
    primaryColorPressed: '#1B87BC',
    primaryColorSuppl: '#229ED9',
    successColor: '#18a058',
    warningColor: '#f0a020',
    errorColor: '#d03050',
    borderRadius: '8px',
    borderRadiusSmall: '6px'
  },
  Card: {
    borderRadius: '14px'
  }
}
</script>

<template>
  <n-config-provider
    :theme="theme"
    :theme-overrides="themeOverrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <n-message-provider :max="4">
      <n-dialog-provider>
        <n-notification-provider :max="3">
          <feedback-bridge />
        </n-notification-provider>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
