import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const username = ref('')
  const mustChangePassword = ref(false)
  const checked = ref(false)

  async function check(): Promise<boolean> {
    try {
      const res = await authApi.me()
      username.value = res.username
      mustChangePassword.value = !!res.must_change_password
      checked.value = true
      return true
    } catch {
      username.value = ''
      checked.value = true
      return false
    }
  }

  async function login(user: string, password: string) {
    const res = await authApi.login(user, password)
    username.value = res.username
    mustChangePassword.value = !!res.must_change_password
    checked.value = true
    return res
  }

  async function logout() {
    try {
      await authApi.logout()
    } finally {
      username.value = ''
    }
  }

  function markPasswordChanged() {
    mustChangePassword.value = false
  }

  return { username, mustChangePassword, checked, check, login, logout, markPasswordChanged }
})
