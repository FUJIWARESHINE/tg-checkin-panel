import axios, { type AxiosError } from 'axios'

const http = axios.create({
  baseURL: '/',
  timeout: 120000,
  withCredentials: true
})

export function extractError(error: unknown): string {
  const err = error as AxiosError<{ message?: string; detail?: string }>
  return (
    err?.response?.data?.message ||
    (err?.response?.data as any)?.detail ||
    err?.message ||
    '请求失败'
  )
}

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => Promise.reject(error)
)

/* ------------------------------------------------------------ 类型 */

export interface Account {
  id: number
  name: string
  phone: string
  api_id: number
  api_hash_masked: string
  proxy: string
  status: string
  is_active: boolean
  me_info: Record<string, any> | null
  has_session: boolean
  last_login_at: string | null
  last_active_at: string | null
  created_at: string | null
}

export interface DialogItem {
  id: number
  title: string
  kind: string
  username: string
  is_bot: boolean
}

export interface Target {
  chat: string
  thread_id: number | null
}

export interface ActionStep {
  type: string
  [key: string]: any
}

export interface SuccessRule {
  mode: 'contains' | 'regex' | 'exact' | 'all'
  keywords: string[]
}

export interface RetryPolicy {
  max: number
  interval_sec: number
  until_success: boolean
}

export interface Task {
  id: number
  name: string
  remark: string
  account_id: number
  account_name: string
  template_id: number | null
  targets: Target[]
  action_flow: ActionStep[]
  schedule_type: 'cron' | 'daily' | 'interval'
  schedule_value: string
  timezone: string
  random_delay_sec: number
  timeout_sec: number
  success_rule: SuccessRule
  retry_policy: RetryPolicy
  catch_up: boolean
  notify_channel_ids: number[]
  notify_on: string[]
  enabled: boolean
  last_run_at: string | null
  next_run_at: string | null
  last_status: string
  last_message: string
  schedule_text: string
  next_runs: string[]
}

export interface TaskTemplate {
  id: number
  name: string
  description: string
  action_flow: ActionStep[]
  success_rule: SuccessRule
  retry_policy: RetryPolicy
  ref_count: number
  created_at: string | null
}

export interface RecordItem {
  id: number
  task_id: number | null
  task_name: string
  account_name: string
  target: string
  trigger: string
  status: string
  attempt: number
  duration_ms: number
  matched_keyword: string
  reply_snippet: string
  reward_text: string
  error: string
  detail: Record<string, any> | null
  run_at: string
}

export interface StatsData {
  today_success: number
  today_fail: number
  today_total: number
  success_rate_7d: number
  heatmap: { date: string; success: number; fail: number }[]
  recent: RecordItem[]
}

export interface NotifyChannel {
  id: number
  name: string
  type: string
  config_masked: Record<string, any>
  enabled: boolean
  on_events: string[]
  quiet_start: string
  quiet_end: string
  quiet_only_fail: boolean
  last_result: string
  last_sent_at: string | null
  created_at: string | null
}

export interface SystemInfo {
  app_name: string
  version: string
  timezone: string
  proxy: string
  scheduler_running: boolean
  accounts_online: number
  tasks_total: number
  tasks_enabled: number
  data_dir: string
  db_size: number
  ai_enabled: boolean
  mask_hint: string
}

export interface ChannelField {
  key: string
  label: string
  type: string
  required?: boolean
  placeholder?: string
}

export interface ChannelTypeMeta {
  label: string
  hint?: string
  fields: ChannelField[]
}

export const EVENT_LABELS: Record<string, string> = {
  success: '签到成功',
  fail: '签到失败',
  retry: '触发重试',
  auth_expired: '登录失效',
  scheduler_error: '调度异常'
}

/* ------------------------------------------------------------ 接口 */

export const authApi = {
  login: (username: string, password: string) =>
    http.post('/api/auth/login', { username, password }).then((r) => r.data),
  logout: () => http.post('/api/auth/logout').then((r) => r.data),
  me: () => http.get('/api/auth/me').then((r) => r.data),
  changePassword: (old_password: string, new_password: string) =>
    http.post('/api/auth/password', { old_password, new_password }).then((r) => r.data)
}

export const accountApi = {
  list: () => http.get<Account[]>('/api/accounts').then((r) => r.data),
  create: (payload: Record<string, any>) =>
    http.post<Account>('/api/accounts', payload).then((r) => r.data),
  update: (id: number, payload: Record<string, any>) =>
    http.patch<Account>(`/api/accounts/${id}`, payload).then((r) => r.data),
  remove: (id: number) => http.delete(`/api/accounts/${id}`).then((r) => r.data),
  sendCode: (id: number, phone: string, force_sms = false) =>
    http.post(`/api/accounts/${id}/login/send-code`, { phone, force_sms }).then((r) => r.data),
  verifyCode: (login_token: string, code: string) =>
    http.post('/api/accounts/login/verify-code', { login_token, code }).then((r) => r.data),
  verifyPassword: (login_token: string, password: string) =>
    http.post('/api/accounts/login/verify-password', { login_token, password }).then((r) => r.data),
  logout: (id: number) => http.post(`/api/accounts/${id}/logout`).then((r) => r.data),
  check: (id: number) => http.post(`/api/accounts/${id}/check`).then((r) => r.data),
  dialogs: (id: number) => http.get<DialogItem[]>(`/api/accounts/${id}/dialogs`).then((r) => r.data)
}

export const taskApi = {
  list: () => http.get<Task[]>('/api/tasks').then((r) => r.data),
  get: (id: number) => http.get<Task>(`/api/tasks/${id}`).then((r) => r.data),
  create: (payload: Record<string, any>) => http.post<Task>('/api/tasks', payload).then((r) => r.data),
  update: (id: number, payload: Record<string, any>) =>
    http.put<Task>(`/api/tasks/${id}`, payload).then((r) => r.data),
  remove: (id: number) => http.delete(`/api/tasks/${id}`).then((r) => r.data),
  toggle: (id: number, enabled: boolean) =>
    http.post<Task>(`/api/tasks/${id}/toggle`, { enabled }).then((r) => r.data),
  run: (id: number, force = true) =>
    http.post(`/api/tasks/${id}/run`, { force }).then((r) => r.data),
  previewSchedule: (payload: Record<string, string>) =>
    http.post('/api/schedule/preview', payload).then((r) => r.data),
  templates: () => http.get<TaskTemplate[]>('/api/templates').then((r) => r.data),
  createTemplate: (payload: Record<string, any>) =>
    http.post<TaskTemplate>('/api/templates', payload).then((r) => r.data),
  updateTemplate: (id: number, payload: Record<string, any>) =>
    http.put<TaskTemplate>(`/api/templates/${id}`, payload).then((r) => r.data),
  removeTemplate: (id: number) => http.delete(`/api/templates/${id}`).then((r) => r.data)
}

export const recordApi = {
  list: (params: Record<string, any>) =>
    http
      .get('/api/records', { params })
      .then((r) => r.data as { total: number; page: number; page_size: number; items: RecordItem[] }),
  stats: (days = 30) => http.get<StatsData>('/api/records/stats', { params: { days } }).then((r) => r.data),
  /** 删除 N 天以前的记录 */
  clear: (days = 30) =>
    http.delete('/api/records', { params: { scope: 'before', days } }).then((r) => r.data),
  /** 只删除选中的记录 */
  removeSelected: (ids: number[]) =>
    http
      .delete('/api/records', { params: { scope: 'ids', ids: ids.join(',') } })
      .then((r) => r.data),
  /** 清空全部记录 */
  clearAll: () => http.delete('/api/records', { params: { scope: 'all' } }).then((r) => r.data),
  exportUrl: (params: Record<string, any>) => {
    const search = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') search.append(k, String(v))
    })
    return `/api/records/export?${search.toString()}`
  }
}

export const notifyApi = {
  types: () =>
    http
      .get('/api/notify/types')
      .then((r) => r.data as { types: Record<string, ChannelTypeMeta>; events: string[] }),
  list: () => http.get<NotifyChannel[]>('/api/notify').then((r) => r.data),
  create: (payload: Record<string, any>) =>
    http.post<NotifyChannel>('/api/notify', payload).then((r) => r.data),
  update: (id: number, payload: Record<string, any>) =>
    http.put<NotifyChannel>(`/api/notify/${id}`, payload).then((r) => r.data),
  remove: (id: number) => http.delete(`/api/notify/${id}`).then((r) => r.data),
  test: (payload: Record<string, any>) => http.post('/api/notify/test', payload).then((r) => r.data),
  testSaved: (id: number) => http.post(`/api/notify/${id}/test`).then((r) => r.data)
}

export const systemApi = {
  info: () => http.get<SystemInfo>('/api/system/info').then((r) => r.data),
  settings: () => http.get('/api/system/settings').then((r) => r.data.settings),
  saveSettings: (payload: Record<string, any>) =>
    http.put('/api/system/settings', payload).then((r) => r.data),
  logs: (params: Record<string, any>) => http.get('/api/system/logs', { params }).then((r) => r.data),
  scheduler: () => http.get('/api/system/scheduler').then((r) => r.data),
  rebuild: () => http.post('/api/system/scheduler/rebuild').then((r) => r.data),
  catchUp: () => http.post('/api/system/catch-up').then((r) => r.data),
  backupUrl: () => '/api/system/backup'
}

export function logsSocketUrl(token = ''): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  // 同源握手会自动携带 Cookie，token 参数仅作为兜底
  const query = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${proto}://${location.host}/ws/logs${query}`
}

export default http
