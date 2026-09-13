import type { MessageApi, DialogApi, NotificationApi } from 'naive-ui'

let messageApi: MessageApi | null = null
let dialogApi: DialogApi | null = null
let notificationApi: NotificationApi | null = null

export function registerFeedback(apis: {
  message: MessageApi
  dialog: DialogApi
  notification: NotificationApi
}) {
  messageApi = apis.message
  dialogApi = apis.dialog
  notificationApi = apis.notification
}

export const feedback = {
  ok(text: string) {
    messageApi?.success(text)
  },
  info(text: string) {
    messageApi?.info(text)
  },
  warn(text: string) {
    messageApi?.warning(text)
  },
  error(text: string) {
    messageApi?.error(text, { duration: 5000 })
  },
  notify(title: string, content: string) {
    notificationApi?.info({ title, content, duration: 4000 })
  },
  confirm(options: { title: string; content: string; positiveText?: string }) {
    return new Promise<boolean>((resolve) => {
      dialogApi?.warning({
        title: options.title,
        content: options.content,
        positiveText: options.positiveText ?? '确定',
        negativeText: '取消',
        onPositiveClick: () => resolve(true),
        onNegativeClick: () => resolve(false),
        onClose: () => resolve(false),
        onMaskClick: () => resolve(false)
      })
    })
  }
}
