import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' }
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '仪表盘' }
      },
      {
        path: 'accounts',
        name: 'accounts',
        component: () => import('@/views/AccountsView.vue'),
        meta: { title: '账号管理' }
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('@/views/TasksView.vue'),
        meta: { title: '签到任务' }
      },
      {
        path: 'tasks/new',
        name: 'task-create',
        component: () => import('@/views/TaskEditorView.vue'),
        meta: { title: '新建任务' }
      },
      {
        path: 'tasks/:id/edit',
        name: 'task-edit',
        component: () => import('@/views/TaskEditorView.vue'),
        meta: { title: '编辑任务' }
      },
      {
        path: 'records',
        name: 'records',
        component: () => import('@/views/RecordsView.vue'),
        meta: { title: '签到记录' }
      },
      {
        path: 'notify',
        name: 'notify',
        component: () => import('@/views/NotifyView.vue'),
        meta: { title: '推送设置' }
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@/views/LogsView.vue'),
        meta: { title: '实时日志' }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '系统设置' }
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.checked) {
    await auth.check()
  }
  if (to.meta.public) {
    if (auth.username && to.name === 'login') return { name: 'dashboard' }
    return true
  }
  if (!auth.username) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || ''
  document.title = title ? `${title} · TG 自动签到面板` : 'TG 自动签到面板'
})

export default router
