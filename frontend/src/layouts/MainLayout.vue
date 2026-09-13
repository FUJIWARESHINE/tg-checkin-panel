<script setup lang="ts">
import { computed, h, ref, type Component } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import {
  NAvatar,
  NButton,
  NIcon,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NLayoutSider,
  NMenu,
  NSpace,
  NTag,
  NTooltip,
  type MenuOption
} from 'naive-ui'
import {
  AlarmOutline,
  ListOutline,
  MoonOutline,
  NotificationsOutline,
  PersonCircleOutline,
  PowerOutline,
  SettingsOutline,
  SpeedometerOutline,
  SunnyOutline,
  TerminalOutline
} from '@vicons/ionicons5'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { feedback } from '@/utils/feedback'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const themeStore = useThemeStore()
const collapsed = ref(false)

const renderIcon = (icon: Component) => () => h(NIcon, null, { default: () => h(icon) })

const menuOptions: MenuOption[] = [
  { label: '仪表盘', key: 'dashboard', icon: renderIcon(SpeedometerOutline) },
  { label: '账号管理', key: 'accounts', icon: renderIcon(PersonCircleOutline) },
  { label: '签到任务', key: 'tasks', icon: renderIcon(AlarmOutline) },
  { label: '签到记录', key: 'records', icon: renderIcon(ListOutline) },
  { label: '推送设置', key: 'notify', icon: renderIcon(NotificationsOutline) },
  { label: '实时日志', key: 'logs', icon: renderIcon(TerminalOutline) },
  { label: '系统设置', key: 'settings', icon: renderIcon(SettingsOutline) }
]

const activeKey = computed(() => {
  const name = String(route.name ?? 'dashboard')
  if (name === 'task-create' || name === 'task-edit') return 'tasks'
  return name
})

function onMenuSelect(key: string) {
  router.push({ name: key })
}

async function handleLogout() {
  const ok = await feedback.confirm({
    title: '退出登录',
    content: '确定要退出当前管理端登录吗？',
    positiveText: '退出'
  })
  if (!ok) return
  await auth.logout()
  router.replace({ name: 'login' })
}
</script>

<template>
  <n-layout has-sider position="absolute" style="height: 100%">
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div
        style="
          height: 56px;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          font-weight: 600;
          font-size: 15px;
        "
      >
        <span
          style="
            display: inline-block;
            width: 24px;
            height: 24px;
            border-radius: 7px;
            background: #229ed9;
            color: #fff;
            text-align: center;
            line-height: 24px;
            font-size: 12px;
          "
          >TG</span
        >
        <span v-if="!collapsed">签到面板</span>
      </div>
      <n-menu
        :value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="20"
        :options="menuOptions"
        @update:value="onMenuSelect"
      />
    </n-layout-sider>

    <n-layout>
      <n-layout-header
        bordered
        style="
          height: 56px;
          padding: 0 20px;
          display: flex;
          align-items: center;
          justify-content: space-between;
        "
      >
        <div style="font-size: 14px; font-weight: 500">
          {{ (route.meta.title as string) || 'TG 自动签到面板' }}
        </div>
        <n-space align="center" :size="10">
          <n-tag v-if="auth.mustChangePassword" type="warning" size="small" round>
            请修改默认密码
          </n-tag>
          <n-tooltip>
            <template #trigger>
              <n-button quaternary circle @click="themeStore.toggle()">
                <template #icon>
                  <n-icon>
                    <MoonOutline v-if="themeStore.mode === 'light'" />
                    <SunnyOutline v-else />
                  </n-icon>
                </template>
              </n-button>
            </template>
            {{ themeStore.mode === 'light' ? '切换到暗色' : '切换到亮色' }}
          </n-tooltip>
          <n-avatar round size="small" style="background: #229ed9">
            {{ (auth.username || 'A').slice(0, 1).toUpperCase() }}
          </n-avatar>
          <span style="font-size: 13px">{{ auth.username || 'admin' }}</span>
          <n-button quaternary circle @click="handleLogout">
            <template #icon>
              <n-icon><PowerOutline /></n-icon>
            </template>
          </n-button>
        </n-space>
      </n-layout-header>

      <n-layout-content
        content-style="padding: 20px;"
        :native-scrollbar="false"
        style="height: calc(100% - 56px)"
      >
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>
