<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSpace,
  NTag,
  NInputNumber,
  NEmpty,
  type DataTableColumns
} from 'naive-ui'
import { accountApi, extractError, type Account, type DialogItem } from '@/api'
import { feedback } from '@/utils/feedback'
import { accountStatusMeta, formatTime } from '@/utils/format'
import AccountLoginModal from '@/components/AccountLoginModal.vue'

const accounts = ref<Account[]>([])
const loading = ref(false)

const createShow = ref(false)
const creating = ref(false)
const form = ref({ name: '', phone: '', api_id: null as number | null, api_hash: '', proxy: '' })

const loginShow = ref(false)
const loginTarget = ref<Account | null>(null)

const dialogsShow = ref(false)
const dialogs = ref<DialogItem[]>([])
const dialogsLoading = ref(false)
const dialogsTitle = ref('')

async function load() {
  loading.value = true
  try {
    accounts.value = await accountApi.list()
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { name: '', phone: '', api_id: null, api_hash: '', proxy: '' }
  createShow.value = true
}

async function submitCreate() {
  if (!form.value.name || !form.value.api_id || !form.value.api_hash) {
    feedback.warn('名称、api_id、api_hash 为必填项')
    return
  }
  creating.value = true
  try {
    const created = await accountApi.create({
      name: form.value.name.trim(),
      phone: form.value.phone.trim(),
      api_id: Number(form.value.api_id),
      api_hash: form.value.api_hash.trim(),
      proxy: form.value.proxy.trim()
    })
    feedback.ok('账号已创建，请继续登录授权')
    createShow.value = false
    await load()
    loginTarget.value = created
    loginShow.value = true
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    creating.value = false
  }
}

function openLogin(row: Account) {
  loginTarget.value = row
  loginShow.value = true
}

async function check(row: Account) {
  try {
    const res = await accountApi.check(row.id)
    feedback.ok(res.message || '连接正常')
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    load()
  }
}

async function logoutAccount(row: Account) {
  const ok = await feedback.confirm({
    title: '登出账号',
    content: `将清除「${row.name}」的本地会话文件，需要重新登录。确定继续？`,
    positiveText: '登出'
  })
  if (!ok) return
  try {
    await accountApi.logout(row.id)
    feedback.ok('已登出')
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    load()
  }
}

async function removeAccount(row: Account) {
  const ok = await feedback.confirm({
    title: '删除账号',
    content: `删除后不可恢复（该账号下不能存在任务）。确定删除「${row.name}」？`,
    positiveText: '删除'
  })
  if (!ok) return
  try {
    await accountApi.remove(row.id)
    feedback.ok('账号已删除')
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    load()
  }
}

async function openDialogs(row: Account) {
  dialogsShow.value = true
  dialogsLoading.value = true
  dialogsTitle.value = row.name
  dialogs.value = []
  try {
    dialogs.value = await accountApi.dialogs(row.id)
  } catch (error) {
    feedback.error(extractError(error))
  } finally {
    dialogsLoading.value = false
  }
}

function copyToClipboard(text: string) {
  navigator.clipboard
    ?.writeText(text)
    .then(() => feedback.ok(`已复制：${text}`))
    .catch(() => feedback.warn('复制失败，请手动选择'))
}

const columns: DataTableColumns<Account> = [
  { title: '名称', key: 'name', minWidth: 120, ellipsis: { tooltip: true } },
  { title: '手机号', key: 'phone', width: 130 },
  { title: 'API ID', key: 'api_id', width: 100 },
  {
    title: '代理',
    key: 'proxy',
    width: 150,
    ellipsis: { tooltip: true },
    render: (row) => row.proxy || '全局默认'
  },
  {
    title: '状态',
    key: 'status',
    width: 118,
    render: (row) => {
      const meta = accountStatusMeta(row.status)
      return h(NTag, { type: meta.type, size: 'small', round: true, bordered: false }, {
        default: () => meta.label
      })
    }
  },
  {
    title: '会话',
    key: 'has_session',
    width: 88,
    render: (row) =>
      h(NTag, { type: row.has_session ? 'success' : 'warning', size: 'small', bordered: false }, {
        default: () => (row.has_session ? '已保存' : '无')
      })
  },
  { title: '最近活跃', key: 'last_active_at', width: 165, render: (row) => formatTime(row.last_active_at) },
  {
    title: '操作',
    key: 'actions',
    width: 300,
    render: (row) =>
      h(NSpace, { size: 6, wrap: false }, {
        default: () => [
          h(
            NButton,
            { size: 'tiny', type: 'primary', onClick: () => openLogin(row) },
            { default: () => (row.has_session ? '重新登录' : '登录') }
          ),
          h(NButton, { size: 'tiny', onClick: () => check(row) }, { default: () => '检测' }),
          h(NButton, { size: 'tiny', onClick: () => openDialogs(row) }, { default: () => '会话' }),
          h(NButton, { size: 'tiny', onClick: () => logoutAccount(row) }, { default: () => '登出' }),
          h(
            NButton,
            { size: 'tiny', type: 'error', quaternary: true, onClick: () => removeAccount(row) },
            { default: () => '删除' }
          )
        ]
      })
  }
]

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">账号管理</h2>
        <p class="page-desc">
          登录你自己的 Telegram 个人号（不是 Bot）。签到由个人号发起，这是 Telegram 的限制。
        </p>
      </div>
      <n-space>
        <n-button :loading="loading" @click="load">刷新</n-button>
        <n-button type="primary" @click="openCreate">新增账号</n-button>
      </n-space>
    </div>

    <n-alert type="info" :show-icon="true">
      <b>api_id / api_hash</b> 需在
      <a href="https://my.telegram.org/apps" target="_blank" rel="noreferrer">my.telegram.org</a>
      申请；国内网络需配置代理（可在「系统设置」里填全局代理，或在此处给单个账号单独配置）。
    </n-alert>

    <n-card class="soft-card" size="small">
      <n-data-table
        v-if="accounts.length"
        :columns="columns"
        :data="accounts"
        :bordered="false"
        :loading="loading"
        size="small"
        :row-key="(row: Account) => row.id"
        :scroll-x="1200"
      />
      <div v-else class="empty-hint">
        还没有账号。点击右上角「新增账号」，填入 api_id / api_hash 后完成登录授权。
      </div>
    </n-card>

    <n-modal
      v-model:show="createShow"
      preset="card"
      title="新增 Telegram 账号"
      style="max-width: 540px; width: 92vw"
      :bordered="false"
    >
      <n-form label-placement="top">
        <n-form-item label="账号名称（自定义，便于区分）">
          <n-input v-model:value="form.name" placeholder="例如：主号 / 小号" />
        </n-form-item>
        <n-form-item label="API ID">
          <n-input-number v-model:value="form.api_id" placeholder="12345678" style="width: 100%" />
        </n-form-item>
        <n-form-item label="API Hash">
          <n-input v-model:value="form.api_hash" placeholder="从 my.telegram.org 复制" />
        </n-form-item>
        <n-form-item label="手机号（可留空，登录时再填）">
          <n-input v-model:value="form.phone" placeholder="+8613800000000" />
        </n-form-item>
        <n-form-item label="独立代理（可留空，使用全局代理）">
          <n-input v-model:value="form.proxy" placeholder="socks5://127.0.0.1:7890" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="createShow = false">取消</n-button>
          <n-button type="primary" :loading="creating" @click="submitCreate">创建并去登录</n-button>
        </n-space>
      </template>
    </n-modal>

    <account-login-modal v-model:show="loginShow" :account="loginTarget" @success="load" />

    <n-drawer v-model:show="dialogsShow" :width="520" placement="right">
      <n-drawer-content :title="`${dialogsTitle} · 会话列表`" closable>
        <p style="font-size: 12px; opacity: 0.6; margin-top: 0">
          点击任意条目复制 @用户名 或 ID，可直接粘贴到任务的「签到目标」里。
        </p>
        <n-empty
          v-if="!dialogsLoading && !dialogs.length"
          description="没有拉到会话，请先登录并确认账号可用"
          style="margin-top: 40px"
        />
        <n-space vertical :size="8">
          <n-card
            v-for="item in dialogs"
            :key="item.id"
            size="small"
            hoverable
            style="cursor: pointer"
            @click="copyToClipboard(item.username)"
          >
            <n-space align="center" justify="space-between">
              <span style="font-size: 13px">{{ item.title }}</span>
              <n-space :size="6">
                <n-tag size="tiny" :bordered="false" :type="item.is_bot ? 'info' : 'default'">
                  {{ item.is_bot ? '机器人' : item.kind }}
                </n-tag>
                <span class="mono" style="opacity: 0.7">{{ item.username }}</span>
              </n-space>
            </n-space>
          </n-card>
        </n-space>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>
