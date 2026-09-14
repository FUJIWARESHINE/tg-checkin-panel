export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const diff = Date.now() - date.getTime()
  const abs = Math.abs(diff)
  const suffix = diff >= 0 ? '前' : '后'
  if (abs < 60_000) return `${Math.max(1, Math.round(abs / 1000))} 秒${suffix}`
  if (abs < 3_600_000) return `${Math.round(abs / 60_000)} 分钟${suffix}`
  if (abs < 86_400_000) return `${Math.round(abs / 3_600_000)} 小时${suffix}`
  return `${Math.round(abs / 86_400_000)} 天${suffix}`
}

export function formatDuration(ms: number | null | undefined): string {
  if (!ms || ms < 0) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export function statusTagType(status: string): 'success' | 'error' | 'warning' | 'default' {
  if (status === 'success') return 'success'
  if (status === 'fail') return 'error'
  if (status === 'skipped') return 'warning'
  return 'default'
}

export function triggerLabel(trigger: string): string {
  return (
    {
      manual: '手动',
      schedule: '定时',
      retry: '重试',
      catchup: '补跑'
    }[trigger] ?? trigger
  )
}

export function accountStatusMeta(status: string): {
  label: string
  type: 'success' | 'error' | 'warning' | 'default' | 'info'
} {
  switch (status) {
    case 'online':
      return { label: '在线', type: 'success' }
    case 'need_login':
      return { label: '需重新登录', type: 'error' }
    case 'need_code':
      return { label: '待验证码', type: 'warning' }
    case 'error':
      return { label: '异常', type: 'error' }
    default:
      return { label: '离线', type: 'default' }
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}
