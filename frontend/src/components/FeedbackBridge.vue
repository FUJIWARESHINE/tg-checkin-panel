<script setup lang="ts">
import { useDialog, useMessage, useNotification } from 'naive-ui'
import { registerFeedback } from '@/utils/feedback'

registerFeedback({
  message: useMessage(),
  dialog: useDialog(),
  notification: useNotification()
})
</script>

<template>
  <router-view />
</template>
