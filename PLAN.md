# TG 自动签到面板 · 开发 Plan

> 项目代号：`tg-checkin-panel`
> 目标：一个 Docker 单容器部署的 Telegram 自动签到服务，带精美 Web 管理界面、可视化定时任务、多渠道详细推送。
> 文档版本：v1.0 ｜ 状态：待评审

---

## ✅ 实施状态（已按本文档完成）

已确认的技术选择：**Vue3 + Naive UI** ｜ 推送先做 **Telegram** ｜ AI 识图**仅预留接口** ｜ 用户**已有 api_id/api_hash**。

M0 → M7 全部完成，代码位于本目录。验证情况：

| 验证项 | 结果 |
|---|---|
| 后端冒烟测试 `python backend/tests/smoke.py` | **61 / 61 通过** |
| 前端生产构建 `npm run build` | **通过**（4655 个模块） |
| 前端静态托管 + SPA 路由回退 | 通过（含未知 `/api` 返回 404、目录穿越拦截） |
| 真实 Telegram 登录 / 签到 | **未验证**（需你的 api_id、手机号与可用代理） |
| Docker 镜像构建 | **未验证**（本机未安装 Docker，构建逻辑按标准多阶段写法） |

已修复的实现期问题：非法 cron 预览未拦截、APScheduler 运行中 `configure()` 会抛异常、
SQLite 时区混存导致比较错乱、`<script setup>` 不能导出共享常量。

---

## 0. 先说一个必须先讲清的坑（决定整个技术路线）

> **Bot 不能给 Bot 发消息。** Telegram 官方 Bot API 明确规定机器人之间无法互相通信。
> 所以「用 Bot API 定时给某个签到机器人发 `/checkin`」这条路**走不通**。

因此所有同类项目（下面 6 个）走的都是同一条路：

**用你自己的 Telegram 个人号（MTProto 协议 / Telethon / Pyrogram）登录，以"真人用户"身份向目标机器人发送签到消息。**

这意味着：

| 项 | 说明 |
|---|---|
| 需要 `api_id` / `api_hash` | 在 https://my.telegram.org/apps 申请（免费） |
| 需要手机号 + 验证码登录一次 | 之后 session 持久化，无需重复登录 |
| 国内网络需代理 | 必须支持 SOCKS5 / HTTP 代理，容器内走 `host.docker.internal` |
| 有账号风控风险 | 需要随机延迟、频率控制、避开敏感时段来降低风险（**建议用备用号**） |

**另一个概念要区分开**（很多教程混在一起）：

- **签到通道** —— 用*个人号*session，向*目标机器人*发消息（不能换成 Bot）
- **推送通道** —— 用*你自己的通知 Bot* 的 token，向你自己的 chat_id 发通知（可以是 Bot）

本项目的两个通道是独立的，配置里要分开。

---

## 1. 参考项目盘点（现成方案调研结果）

按参考价值排序：

### ⭐ 1.1 `amchii/tg-signer` —— 首选参考本体
最成熟、生态最完整的方案，本项目主要借鉴对象。

| 维度 | 情况 |
|---|---|
| 技术栈 | Python 3.10+ / **Pyrogram** / NiceGUI / Pydantic / SQLite / `uv` |
| 交付形态 | CLI + WebUI + Docker（`ghcr.io/amchii/tg-signer:*-webui`） |
| 核心能力 | 每日定时 + 随机误差签到、按文本点击键盘按钮、AI 图片识别答题、动作流、消息监控、自动化规则引擎（trigger→filter→handler） |
| 调度 | 进程内计划调度器（`serve` 模式，支持"账号 × 任务 × 时刻"计划表）+ 任务内 `sign_at` / crontab |
| 存储 | `data.sqlite3` 存签到记录（旧版 JSON 自动迁移） |
| 稳定性设计 | **`_call_telegram_api()` 全局 API 串行化 + 最小 0.35s 间隔 + FloodWait 自动重试**；Client 单例 + 引用计数，多任务共享连接 |
| 通知 | Server酱、UDP 转发、HTTP Webhook |
| 可借鉴 | 客户端单例池与 FloodWait 处理、动作流抽象、配置版本迁移（V1/V2→V3）、SQLite 记录库 |
| 可改进 | WebUI 是 NiceGUI 写的 JSON 编辑器，**不够好看也不够直观**；无多渠道推送；无任务模板 |

- 仓库：https://github.com/amchii/tg-signer
- 深度解析：https://deepwiki.com/amchii/tg-signer

### ⭐ 1.2 `ssfun/tg-sign-plus`（原 xuanhen2013）—— 前端参考标杆
**前端做得最好**的一个，前后端分离，界面现代化。

| 维度 | 情况 |
|---|---|
| 技术栈 | **FastAPI** 后端 + **Next.js** 前端 + JWT + 2FA/TOTP + Docker |
| 核心能力 | Cron 定时签到、多账号多群组、随机延迟、发文本/骰子/点按钮、AI 图片识别选选项、自动解计算题、消息监控转发（UDP/HTTP）、Server酱推送 |
| 可借鉴 | **前后端分离架构、JWT+2FA 鉴权、可视化任务配置、CLI 工具、导入导出、低内存部署参数** |
| 可改进 | Next.js 前端对单容器部署偏重（构建产物体积大）；导航信息密度一般 |

### 1.3 `Micah123321/tg-signer` —— 调度改造参考
就是 1.1 的增强 fork。关键差异：**计划表时刻作为 serve 调度的唯一时间源**，调度触发时强制 `force_rerun` 忽略任务内时间门禁，避免"双定时"冲突。这个设计值得抄。

### 1.4 `bamzest/telegram-auto-checkin` —— Go 单二进制路线
| 维度 | 情况 |
|---|---|
| 技术栈 | **Go** + Docker 多架构镜像，单二进制 |
| 亮点 | 多账号、手机号/二维码登录、2FA、并发 worker 池、Cron + 间隔双调度、SOCKS5、中英双语 i18n、主日志 + 任务分离日志 |
| 可借鉴 | **二维码登录**（比手动输验证码体验好太多）、任务级独立日志、多架构镜像构建方式（`buildx`） |
| 可改进 | 纯配置文件驱动（YAML），**没有 Web 界面**，改配置要改文件重启 |

### 1.5 `MoonTV-hash/TgAutoCheckin` —— 重试策略参考
Telethon + Docker，亮点是**失败后每小时自动重试，直到正则匹配到成功关键词（"签到成功/获得/积分"）为止**，并带 `list_groups.py` 自动列出你加入的群组 ID。这个"以结果关键词判定成功、不成功就重试"的思路要抄。

### 1.6 `Zhun-ye/telegram-checkin-bot` —— Bot 内管理路线
Telethon + APScheduler，**完全通过一个管理 Bot 在 Telegram 里管理**（聊天命令增删任务），支持 6 字段 Cron（含秒）、`100s/36h` 间隔表达式、**任务模板**（改模板同步所有引用任务）、多账号。适合没有 Web 的场景，但交互效率低——本项目保留"任务模板"这个亮点。

### 参考项目能力矩阵

| 能力 | tg-signer | tg-sign-plus | Go-checkin | TgAutoCheckin | 本项目 |
|---|:---:|:---:|:---:|:---:|:---:|
| Docker 部署 | ✅ | ✅ | ✅ | ✅ | ✅ 单容器 |
| 个人号 MTProto | ✅ | ✅ | ✅ | ✅ | ✅ |
| 多账号 | ✅ | ✅ | ✅ | ❌ | ✅ |
| 定时调度 | ✅ Cron | ✅ Cron | ✅ Cron+间隔 | ✅ 定点 | ✅ Cron+间隔+定点 |
| 随机延迟防封 | ✅ | ✅ | ✅ | ❌ | ✅ |
| 点按钮 / 骰子 | ✅ | ✅ | ✅ | ❌ | ✅ |
| AI 识图答题 | ✅ | ✅ | ❌ | ❌ | ✅ 预留 |
| Web 界面 | ⚠️ 朴素 | ✅ 精美 | ❌ | ❌ | ✅ 精美 |
| 可视化动作流编辑 | ❌ JSON | ⚠️ 表单 | ❌ | ❌ | ✅ **拖拽卡片** |
| 任务模板复用 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 多渠道推送 | ⚠️ 少 | ⚠️ Server酱 | ❌ | ❌ | ✅ **9 种** |
| 结果关键词判定+重试 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 二维码登录 | ❌ | ❌ | ✅ | ❌ | ✅ |
| Session 加密落盘 | ❌ | ⚠️ | ❌ | ❌ | ✅ |

---

## 2. 本项目的差异化定位

一句话：**tg-signer 的能力上限 + tg-sign-plus 的界面水准 + 自己的可视化动作流和详细推送。**

1. **精美 Web UI** —— Vue 3 + Naive UI，亮/暗双主题，仪表盘带 ECharts 签到热力图与成功率统计
2. **可视化动作流编辑器** —— 不写 JSON，拖拽卡片：发文本 → 等回复 → 命中关键词 → 点按钮 → 判定结果
3. **详细推送** —— 9 种渠道，富文本卡片，含签到结果/耗时/下次时间/错误摘要，支持静默时段与合并降噪
4. **任务模板** —— 一处改，批量任务同步
5. **二维码登录 + 手机号登录** 双模式，支持 2FA
6. **Session 加密落盘**（Fernet），密钥独立于数据卷
7. **补跑机制** —— 容器重启/宕机错过时间，启动后检测当日未成功任务并按策略补跑

---

## 3. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 运行时 | Python 3.12-slim | 生态最全，镜像小 |
| TG 客户端 | **Telethon**（async） | 签到类项目事实标准，Session 持久化简单，`FloodWaitError` 自带 `seconds`；二维码登录支持好 |
| Web 框架 | **FastAPI** + Uvicorn | 异步、自动 OpenAPI、WebSocket 原生支持 |
| 调度 | **APScheduler 3.10**（AsyncIOScheduler） | Cron + interval + date 三合一；任务定义落库、启动时重建，不依赖 jobstore 持久化（更可控） |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite | 类型友好 |
| 数据库 | **SQLite** | 单容器零依赖，够用；预留切 Postgres 的 abstract 层 |
| 校验/配置 | Pydantic v2 + pydantic-settings | 动作流 schema 严格校验 |
| 鉴权 | PyJWT + bcrypt | 单管理员账号，JWT 存 HttpOnly Cookie |
| 加密 | cryptography (Fernet) | Session / 渠道密钥字段加密 |
| 日志 | loguru + 自研 ring buffer → WebSocket 推送 | 前端实时日志 |
| 前端 | **Vue 3 + Vite + TypeScript + Naive UI + Pinia + ECharts** | Naive UI 视觉干净、暗色好看、组件全 |
| 打包 | 根目录多阶段 Dockerfile | stage1 node 构建前端 → stage2 python 运行时，前端产物由 FastAPI 静态托管（**单容器 + 单端口，无跨域无 Nginx**） |

---

## 4. 目录结构

```
tg-checkin-panel/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                  # FastAPI 入口、静态资源托管、生命周期钩子
│  │  ├─ settings.py              # pydantic-settings 读 env
│  │  ├─ db.py                    # engine / session / init_db
│  │  ├─ models.py                # ORM 模型
│  │  ├─ schemas.py               # 请求/响应 DTO
│  │  ├─ security.py              # 登录、JWT、Fernet 加解密、限流
│  │  ├─ api/
│  │  │  ├─ auth.py               # 登录/登出/改密
│  │  │  ├─ accounts.py           # 账号 CRUD、登录状态机、拉取机器人/群组列表
│  │  │  ├─ tasks.py              # 任务 CRUD、手动执行、启停、模板
│  │  │  ├─ records.py            # 签到记录查询、统计
│  │  │  ├─ notify.py             # 推送渠道 CRUD、测试推送
│  │  │  ├─ system.py             # 系统设置、日志、版本、备份
│  │  │  └─ ws.py                 # WebSocket：实时日志 + 执行状态推送
│  │  ├─ core/
│  │  │  ├─ client_pool.py        # Telethon 客户端单例池 + 引用计数 + 串行化 + FloodWait 重试
│  │  │  ├─ login.py              # 手机号/验证码/2FA/二维码 登录状态机
│  │  │  ├─ actions.py            # 动作流执行器（各类 step handler）
│  │  │  ├─ runner.py             # 单次任务编排：执行→解析→判定→记录→推送
│  │  │  ├─ scheduler.py          # APScheduler 封装，任务增删改同步
│  │  │  ├─ notifier.py           # 推送渠道适配器 + 消息模板渲染
│  │  │  └─ ai.py                 # OpenAI 兼容视觉/文本能力（识图答题，可选）
│  │  └─ utils/                   # 时间、cron 解析、脱敏、文本提取
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ views/                   # Dashboard / Accounts / Tasks / TaskEditor / Records / Notify / Settings / Login
│  │  ├─ components/              # ActionFlowEditor / CronInput / RecordTable / StatCards / LogConsole
│  │  ├─ api/  stores/  router/  styles/
│  │  └─ main.ts
│  ├─ package.json
│  └─ vite.config.ts
├─ data/                          # 挂载卷（运行时生成）
│  ├─ app.db
│  ├─ sessions/                   # *.session（加密配置）
│  └─ logs/
├─ deploy/
│  ├─ docker-compose.yml
│  └─ .env.example
├─ Dockerfile                     # 多阶段
└─ README.md
```

---

## 5. 数据模型

```
accounts                          # TG 账号
  id, name, phone(脱敏), api_id, api_hash(加密), session_path,
  proxy, status(offline/online/need_code/need_2fa/error),
  last_login_at, last_active_at, is_active, created_at

tasks                             # 签到任务
  id, name, account_id(FK), template_id(FK, nullable), remark,
  targets(JSON)                   # [{"chat":"@bot","thread_id":null}]
  action_flow(JSON)               # 动作流步骤数组
  schedule_type                   # cron | daily | interval
  schedule_value                  # "0 8 * * *" | "08:00:00" | "12h"
  random_delay_sec                # ±秒，模拟真人
  timezone, timeout_sec
  success_rule(JSON)              # {"mode":"contains","keywords":["签到成功","获得","积分"]}
  retry_policy(JSON)              # {"max":3,"interval":3600,"until_success":true}
  catch_up                        # 启动补跑：true/false
  notify_channel_ids(JSON), notify_on(JSON)   # ["success","fail","retry"]
  enabled, last_run_at, next_run_at, last_status, created_at, updated_at

task_templates                    # 任务模板（批量复用）
  id, name, action_flow(JSON), success_rule(JSON), retry_policy(JSON), created_at

records                           # 签到记录
  id, task_id, account_id, target, run_at, trigger(manual/schedule/retry/catchup),
  status(success/fail/skipped/timeout), attempt, duration_ms,
  matched_keyword, reply_snippet, reward_text, error, created_at

notify_channels
  id, type(telegram/serverchan/bark/wecom/dingtalk/feishu/gotify/webhook/email),
  name, config(JSON, 加密), enabled, on_events(JSON), quiet_hours, created_at
  # 事件类型 all / success / fail / retry / auth_expired / scheduler_error

settings                          # KV：时区、全局代理、重试默认值、UI 语言、推送模板
audit_logs                        # 操作审计（谁改了什么配置）
```

---

## 6. 动作流设计（核心亮点）

任务执行 = 顺序跑一串步骤，每步是一个 JSON 对象，前端渲染成可拖拽卡片。

**步骤类型：**

| type | 参数 | 说明 |
|---|---|---|
| `send_text` | `text`, `delay_after`, `delete_after` | 发送文本，如 `/checkin` |
| `send_dice` | `emoji`, `wait_result` | 发送骰子/飞镖表情 |
| `click_button` | `text` 或 `index` | 按文本/序号点击键盘按钮 |
| `wait_reply` | `timeout`, `match{mode,keyword}` | 等待目标回复，`mode` 取 `contains/regex/exact` |
| `ai_choose` | `prompt`, `options` | 截图/图片交大模型选选项（识图签到） |
| `condition` | `if`, `op`, `value`, `then`(`continue`/`stop`/`fail`) | 分支判定，如"回复含'已签到'则 stop" |
| `sleep` | `seconds` | 显式等待 |
| `extract` | `regex`, `as` | 从回复中提取积分/奖励，供推送使用 |

**示例配置：**

```json
[
  { "type": "send_text", "text": "/checkin", "delay_after": 2 },
  { "type": "wait_reply", "timeout": 25, "match": { "mode": "contains", "keyword": "签到" } },
  { "type": "click_button", "text": "签到" },
  { "type": "wait_reply", "timeout": 25, "match": { "mode": "regex", "keyword": "(签到成功|获得|积分[+＋]?\\d+)" } },
  { "type": "extract", "regex": "积分[+＋]?(\\d+)", "as": "points" },
  { "type": "condition", "if": "{last_reply}", "op": "contains", "value": "已签到", "then": "stop" }
]
```

**执行器要点：**
- 每步执行前检查 `task.timeout_sec` 总超时
- 每步结果写入临时上下文，供 `condition` / `extract` 引用（`{last_reply}`、`{points}`）
- 命中 `success_rule` → 立即判定成功并结束
- 未命中 → 按 `retry_policy` 挂重试（`until_success` 模式下每小时重试到成功为止，抄 TgAutoCheckin）

---

## 7. 调度设计

基于 APScheduler `AsyncIOScheduler`，**任务定义存库，启动时全量重建 job**（不用 jobstore，避免与 DB 双写不一致）。

| 能力 | 实现 |
|---|---|
| Cron | 5 字段标准 + 6 字段含秒（前端带可视化 cron 构造器 + 下次执行时间预览） |
| 每日定点 | 等价 `cron(hour, minute, second)` 快捷方式 |
| 间隔 | 支持 `30m` / `12h` / `1d` 写法 |
| 随机延迟 | 触发时 `delay = random(-N, +N)` 秒后再执行，`N` 任务级可配 |
| 时区 | 容器 `TZ` 为全局默认，任务级可覆盖（如跨区站点） |
| 并发控制 | 全局并发上限；**同账号串行**（防 FloodWait）；同任务不重入（`max_instances=1`） |
| 错过补跑 | 启动时扫描"今日应有但未成功"的任务，按 `catch_up` 策略立即补跑一次 |
| 重试 | 失败按 `retry_policy` 挂一次性 job；`until_success` 则每小时一次直到成功 |
| 手动执行 | API 触发 `force_rerun`，忽略"今日已成功"判断（抄 Micah fork 的做法） |
| 双重保险 | 任务内 `sign_at` 仅 CLI 场景使用，Web 调度唯一时间源，避免双定时 |

---

## 8. 推送设计（详细推送）

**事件类型：** `success` / `fail` / `retry` / `auth_expired` / `scheduler_error`

**消息模板（结构化字段，各渠道渲染各自格式）：**

```
【签到成功】每日签到
账号：main (+86****8899)
目标：@XXXBot
耗时：6.4s ｜ 第 1 次尝试
结果：签到成功，积分 +12
下次：09-14 08:00:00 (Asia/Shanghai)
```

失败时附：失败步骤、错误类型（FloodWait/超时/未命中关键词）、错误摘要（截断 300 字）

**渠道适配器（统一接口 `send(title, fields, level) -> ok/err`）：**

| 渠道 | 渲染方式 |
|---|---|
| Telegram Bot | HTML/MarkdownV2 消息卡片，支持静默发送 `disable_notification` |
| Server 酱 | `sctapi.ftqq.com`，title + markdown desp |
| Bark | 标题/正文/分组/图标/声音，支持 `level=critical` |
| 企业微信机器人 | `markdown` 消息 |
| 钉钉机器人 | `markdown` + 加签 |
| 飞书机器人 | 交互式卡片（富文本） |
| Gotify | title/message/priority |
| 通用 Webhook | POST JSON 原样投递，可自定义 Header |
| 邮件 | SMTP + HTML 模板 |

**降噪设计：**
- 每渠道独立订阅事件（比如"失败推 TG，成功推 Bark"）
- **静默时段**：如 23:00–07:00 只推失败
- **合并抑制**：同一任务连续失败 N 次只推 1 条，恢复时补推 1 条"已恢复"
- 推送自身失败 → 重试 3 次 → 降级写入系统日志并在 WebUI 标红

**测试推送**：渠道配置页有"发送测试消息"按钮，即时反馈结果。

---

## 9. 前端页面设计

| 页面 | 内容 |
|---|---|
| 登录 | 单管理员登录，支持"记住我"、改密 |
| 仪表盘 | 今日成功/失败/待执行卡片、近 30 天签到热力图（ECharts）、成功率环形图、账号在线状态、下次执行倒计时 |
| 账号管理 | 账号列表（状态灯）、新增账号向导（api_id/hash → 手机号 或 二维码 → 验证码 → 2FA）、拉取该账号的机器人与群组列表供选择、登出/删除 session |
| 任务管理 | 任务列表（启停开关、下次执行时间、最近状态徽标）、筛选、批量启停、从模板创建 |
| 任务编辑 | 基础信息 + **可视化动作流编辑器**（左侧步骤卡片列表可拖拽排序，右侧步骤参数面板）+ 调度配置（cron 可视化构造器）+ 成功规则 + 重试策略 + 推送订阅 + "立即执行一次"试跑 |
| 任务模板 | 模板 CRUD，编辑模板时提示影响 N 个引用任务 |
| 签到记录 | 表格（时间/任务/账号/目标/状态/耗时/结果摘要）、筛选、导出 CSV、点开看完整回复原文 |
| 推送设置 | 渠道卡片列表、新增渠道（动态表单，按渠道类型渲染不同字段）、测试推送、事件订阅勾选、静默时段 |
| 实时日志 | WebSocket 流式日志，等级过滤、关键词搜索、自动滚动、下载 |
| 系统设置 | 时区、全局代理、默认重试、数据备份/恢复（下载 app.db）、主题切换、修改密码、版本信息 |

UI 细节：Naive UI 亮/暗双主题、响应式（手机也能管）、骨架屏、操作 toast 反馈、危险操作二次确认。

---

## 10. Docker 部署

**根目录多阶段 Dockerfile：**

```dockerfile
# ---- stage 1: 构建前端 ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build            # → /web/dist

# ---- stage 2: Python 运行时 ----
FROM python:3.12-slim
ENV TZ=Asia/Shanghai PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./static
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml：**

```yaml
services:
  tg-checkin-panel:
    build: .
    image: tg-checkin-panel:latest
    container_name: tg-checkin-panel
    restart: unless-stopped
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data          # 数据库 / session / 日志
    environment:
      - TZ=Asia/Shanghai
      - ADMIN_USERNAME=admin
      - ADMIN_PASSWORD=change-me-please
      - SECRET_KEY=随机长字符串
      - MASTER_KEY=Fernet 密钥（不填则首次启动自动生成到 data/.master_key）
      - TG_PROXY=socks5://host.docker.internal:7890   # 国内必需
    extra_hosts:
      - "host.docker.internal:host-gateway"   # Linux 下代理回宿主机
```

**部署流程：**
```bash
cd deploy
cp .env.example .env        # 改密码、密钥、代理
docker compose up -d --build
# 浏览器打开 http://<host>:8000
```

---

## 11. 安全与风控

**安全**
- WebUI 强制登录，JWT 存 HttpOnly Cookie；登录失败限流（5 次/IP/5min）
- Session 与渠道密钥用 Fernet 加密落盘，`MASTER_KEY` 来自 env 或自动生成于数据卷
- 密码 bcrypt 哈希，不落明文
- 容器内不暴露 session 文件，日志中手机号/token 全部脱敏
- 首次启动若用默认密码，强制跳转改密页

**风控（降低被封概率）**
- 签到时间加随机抖动（默认 ±300s）
- 同账号全局串行 + API 最小间隔 0.35s + FloodWait 指数退避（抄 tg-signer）
- 单次签到步骤数上限、总超时上限
- 失败不用高频重试（默认 1 小时间隔）
- README 明确风险提示，建议使用备用号

---

## 12. 开发里程碑

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **M0** 骨架 | 项目结构、Dockerfile、compose、FastAPI 起来、前端空壳能访问 | 容器跑起来，浏览器看到登录页 |
| **M1** 账号 | Telethon 客户端池、手机号/验证码/2FA 登录、二维码登录、session 持久化、拉取机器人与群组列表 | 能登录一个账号并在页面看到会话状态 |
| **M2** 引擎 | 动作流执行器（全 8 种步骤）、成功规则判定、FloodWait 重试、手动单次执行 | 手动点一下能真签到成功并看到回复解析结果 |
| **M3** 调度 | 任务 CRUD 落库、APScheduler 重建、随机延迟、并发控制、重试、补跑、记录落库 | 配一个"每天 8:00"的任务，到点自动执行并记录 |
| **M4** 接口 | 全量 REST API + JWT + 限流 + WebSocket 实时日志 | 接口自测全通，前端能实时看日志 |
| **M5** 前端 | 登录/仪表盘/账号/任务列表+动作流编辑器/记录/推送设置/日志/系统设置 | 全部页面可用，亮暗主题正常，手机端可操作 |
| **M6** 推送 | 9 渠道适配器、事件订阅、静默时段、合并降噪、测试推送 | 每种渠道都能收到测试消息并格式正确 |
| **M7** 交付 | 多阶段构建优化、compose、README（含 api_id 申请图文步骤）、真机联调截图 | 从零到跑通全流程文档可复现 |

**验证方式（针对你偏好的"真跑"）**
- M2 阶段：用一个小号 + 任意一个真实签到 Bot 做端到端试跑，录屏/截图留存
- M3 阶段：把 cron 临时设为 2 分钟后，验证真实触发与记录写入
- M6 阶段：每个渠道实际收到消息的截图

---

## 13. 待你确认的决策项

1. **前端技术栈**：Vue 3 + Naive UI（推荐，轻、暗色好看）/ 或 React + Ant Design（生态更大）
2. **部署目标**：群晖 NAS / 自有服务器 / 本地 Windows Docker？（影响镜像架构与代理配置说明）
3. **推送渠道**：默认全做 9 种，还是先做你最常用的几种（如 Telegram + Bark + 企业微信）？
4. **是否需要 AI 识图答题**（`ai_choose` 步骤，需要 OpenAI 兼容 API Key）：现在做 / 预留接口后续补
5. **签到目标**：是固定的某个机器人，还是需要通用多目标？（默认按通用多目标设计）
6. **是否已有 `api_id` / `api_hash`**：没有的话我在 README 里写详细申请步骤

---

## 14. 风险提示

- 自动化操作 Telegram 账号**存在被限制/封号风险**，建议使用**备用账号**，不要用主号
- 国内运行必须能访问 Telegram，需要可用代理
- 项目仅供个人学习与自用，请遵守 Telegram 服务条款与目标机器人的使用规则
