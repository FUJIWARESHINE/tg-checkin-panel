import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

type Mode = 'light' | 'dark'

const KEY = 'tgcp-theme'

export const useThemeStore = defineStore('theme', () => {
  const stored = (localStorage.getItem(KEY) as Mode | null) ?? 'light'
  const mode = ref<Mode>(stored)
  const followSystem = ref(!localStorage.getItem(KEY))

  watch(mode, (value) => {
    localStorage.setItem(KEY, value)
    followSystem.value = false
  })

  function toggle() {
    mode.value = mode.value === 'dark' ? 'light' : 'dark'
  }

  function init() {
    if (followSystem.value) {
      mode.value = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
  }

  return { mode, followSystem, toggle, init }
})
