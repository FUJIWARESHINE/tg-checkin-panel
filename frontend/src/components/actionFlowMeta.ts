import type { ActionStep } from '@/api'

export interface FieldDef {
  key: string
  label: string
  type: 'text' | 'textarea' | 'number' | 'switch' | 'select'
  placeholder?: string
  options?: { label: string; value: string }[]
  hint?: string
  step?: number
}

export interface StepMeta {
  label: string
  color: 'blue' | 'green' | 'purple' | 'orange' | 'red' | 'default'
  desc: string
  summary: (step: ActionStep) => string
  fields: FieldDef[]
  preset?: ActionStep
}

export const STEP_META: Record<string, StepMeta> = {
  send_text: {
    label: '发送文本',
    color: 'blue',
    desc: '向目标发送一条文字消息',
    summary: (s) => String(s.text || '（未填写）'),
    preset: { type: 'send_text', text: '/checkin', delay_after: 2 },
    fields: [
      { key: 'text', label: '文本内容', type: 'textarea', placeholder: '/checkin' },
      { key: 'delay_after', label: '发送后等待（秒）', type: 'number', step: 0.5 },
      { key: 'delete_after', label: 'N 秒后撤回该消息', type: 'number', step: 1, hint: '留空则不撤回' }
    ]
  },
  send_dice: {
    label: '发送骰子',
    color: 'purple',
    desc: '发送 🎲 等随机表情，常用于骰子签到',
    summary: (s) => `表情 ${s.emoji || '🎲'}`,
    preset: { type: 'send_dice', emoji: '🎲', delay_after: 2 },
    fields: [
      { key: 'emoji', label: '表情', type: 'text', placeholder: '🎲', hint: '支持 🎲 🎯 🏀 ⚽ 🎳 🎰' },
      { key: 'wait_result', label: '等待结果', type: 'switch' },
      { key: 'delay_after', label: '发送后等待（秒）', type: 'number', step: 0.5 }
    ]
  },
  click_button: {
    label: '点击按钮',
    color: 'green',
    desc: '点击回复消息上的键盘按钮',
    summary: (s) => (s.text ? `按钮「${s.text}」` : `按钮 #${s.index ?? 0}`),
    preset: { type: 'click_button', text: '签到', delay_after: 1 },
    fields: [
      { key: 'text', label: '按钮文字', type: 'text', placeholder: '签到', hint: '与序号二选一，文字优先' },
      { key: 'index', label: '按钮序号（从 0 开始）', type: 'number' },
      { key: 'delay_after', label: '点击后等待（秒）', type: 'number', step: 0.5 }
    ]
  },
  wait_reply: {
    label: '等待回复',
    color: 'orange',
    desc: '等待目标回复，可按关键词过滤',
    summary: (s) => {
      const match = (s.match as any) ?? {}
      return match.keyword ? `${match.mode || 'contains'}: ${match.keyword}` : '任意回复'
    },
    preset: { type: 'wait_reply', timeout: 25, match: { mode: 'contains', keyword: '签到' } },
    fields: [
      { key: 'timeout', label: '超时（秒）', type: 'number' },
      {
        key: 'match.mode',
        label: '匹配方式',
        type: 'select',
        options: [
          { label: '包含关键词', value: 'contains' },
          { label: '正则匹配', value: 'regex' },
          { label: '完全相等', value: 'exact' },
          { label: '任意回复', value: 'all' }
        ]
      },
      { key: 'match.keyword', label: '关键词 / 正则', type: 'text', placeholder: '签到成功|获得|积分' }
    ]
  },
  ai_choose: {
    label: 'AI 识图答题',
    color: 'red',
    desc: '把图片交给大模型选选项（需先在系统设置里开启 AI）',
    summary: (s) => (s.prompt ? String(s.prompt).slice(0, 20) : '识图选答案'),
    preset: { type: 'ai_choose', prompt: '请选出正确的选项', options: ['A', 'B', 'C'], click: true },
    fields: [
      { key: 'prompt', label: '提问', type: 'textarea', placeholder: '请选出正确的选项' },
      { key: 'options', label: '候选选项', type: 'text', placeholder: 'A,B,C', hint: '逗号分隔' },
      { key: 'click', label: '自动点击答案按钮', type: 'switch' },
      { key: 'reply_text', label: '或直接回复文字', type: 'text', placeholder: '可留空' }
    ]
  },
  condition: {
    label: '条件分支',
    color: 'default',
    desc: '按条件提前结束或判定成功/失败',
    summary: (s) => `${s.op || 'contains'}「${s.value || ''}」→ ${s.then || 'continue'}`,
    preset: { type: 'condition', if: '{last_reply}', op: 'contains', value: '已签到', then: 'stop' },
    fields: [
      { key: 'if', label: '取值来源', type: 'text', placeholder: '{last_reply}', hint: '支持 {last_reply} 等变量' },
      {
        key: 'op',
        label: '判断方式',
        type: 'select',
        options: [
          { label: '包含', value: 'contains' },
          { label: '不包含', value: 'not_contains' },
          { label: '正则匹配', value: 'regex' },
          { label: '完全相等', value: 'exact' },
          { label: '为空', value: 'empty' },
          { label: '不为空', value: 'not_empty' }
        ]
      },
      { key: 'value', label: '比较值', type: 'text', placeholder: '已签到' },
      {
        key: 'then',
        label: '命中后动作',
        type: 'select',
        options: [
          { label: '继续执行', value: 'continue' },
          { label: '判定成功并结束', value: 'success' },
          { label: '直接结束（成功）', value: 'stop' },
          { label: '判定失败', value: 'fail' }
        ]
      }
    ]
  },
  sleep: {
    label: '等待',
    color: 'default',
    desc: '显式等待若干秒',
    summary: (s) => `${s.seconds ?? 1} 秒`,
    preset: { type: 'sleep', seconds: 2 },
    fields: [{ key: 'seconds', label: '等待秒数', type: 'number', step: 0.5 }]
  },
  extract: {
    label: '正则提取',
    color: 'green',
    desc: '从回复里提取积分等数值，供推送展示',
    summary: (s) => `${s.as || 'extracted'} = /${s.regex || ''}/`,
    preset: { type: 'extract', regex: '积分[+＋]?(\\d+)', as: 'reward_text' },
    fields: [
      { key: 'regex', label: '正则表达式', type: 'text', placeholder: '积分[+＋]?(\\d+)' },
      {
        key: 'as',
        label: '变量名',
        type: 'text',
        placeholder: 'reward_text',
        hint: '用 reward_text 会自动作为「奖励」推送'
      },
      { key: 'group', label: '捕获组序号', type: 'number' },
      { key: 'from', label: '来源', type: 'text', placeholder: '{last_reply}' }
    ]
  }
}

export const STEP_ORDER = Object.keys(STEP_META)

export function blankStep(type: string): ActionStep {
  const meta = STEP_META[type]
  return JSON.parse(JSON.stringify(meta?.preset ?? { type }))
}

/** 新手友好的默认动作流：发指令 → 等回复 → 判定 */
export function defaultFlow(): ActionStep[] {
  return [
    { type: 'send_text', text: '/checkin', delay_after: 2 },
    { type: 'wait_reply', timeout: 25, match: { mode: 'contains', keyword: '签到' } },
    { type: 'click_button', text: '签到', delay_after: 1 },
    {
      type: 'wait_reply',
      timeout: 25,
      match: { mode: 'regex', keyword: '签到成功|已签到|获得|积分' }
    },
    { type: 'condition', if: '{last_reply}', op: 'contains', value: '已签到', then: 'stop' }
  ]
}
