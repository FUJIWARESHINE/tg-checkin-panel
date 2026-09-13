# TG 自动签到面板（tg-checkin-panel）

[![Docker 镜像构建与发布](https://github.com/FUJIWARSHINE/tg-checkin-panel/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/FUJIWARSHINE/tg-checkin-panel/actions/workflows/docker-publish.yml)
[![CI 代码校验](https://github.com/FUJIWARSHINE/tg-checkin-panel/actions/workflows/ci.yml/badge.svg)](https://github.com/FUJIWARSHINE/tg-checkin-panel/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/FUJIWARSHINE/tg-checkin-panel?label=version&color=green)](https://github.com/FUJIWARSHINE/tg-checkin-panel/releases)
[![GHCR](https://img.shields.io/badge/ghcr.io-tg--checkin--panel-blue?logo=docker)](https://github.com/FUJIWARSHINE/tg-checkin-panel/pkgs/container/tg-checkin-panel)

一个 Docker 单容器部署的 **Telegram 自动签到服务**：每天定时用你的个人号给目标机器人发送签到消息，
带精美 Web 管理界面、可视化拖拽的动作流编辑器、灵活的定时调度和详细的推送通知。

> 参考并改进了 6 个开源方案（amchii/tg-signer、ssfun/tg-sign-plus、Micah123321/tg-signer、
> bamzest/telegram-auto-checkin、MoonTV-hash/TgAutoCheckin、Zhun-ye/telegram-checkin-bot）。

---

## ⚠️ 先读这段：一个必须知道的前提

**Telegram 禁止 Bot 给 Bot 发消息。**

所以「用 Bot API 定时给签到机器人发 `/checkin`」这条路**走不通**。所有同类项目（包括本项目）
走的都是同一条路：

> 用**你自己的 Telegram 个人号**（MTProto 协议，通过 Telethon）登录，以**真人用户身份**向目标机器人发送签到消息。

这意味着你需要：

| 需要什么 | 怎么获得 |
|---|---|
| `api_id` / `api_hash` | 到 https://my.telegram.org/apps 免费申请（见下方图文步骤） |
| 一个能收验证码的手机号 | 登录时用一次，之后 session 持久化，不用重复登录 |
| 能访问 Telegram 的网络 | 国内需要代理，支持 `socks5://` / `socks4://` / `http://` |

**另外两个概念要分清：**

- **签到通道** = 你的个人号 → 目标机器人（只能是个人号，不能是 Bot）
- **推送通道** = 你自己的通知 Bot → 你自己（这个可以用 Bot）

本项目两者相互独立，配置时别填错地方。

> ⚠️ 风控提示：自动化操作 Telegram 账号**存在被限制或封号的风险**。强烈建议使用**备用号**，
> 不要用主号。项目已内置随机延迟、API 串行化、FloodWait 退避等降风险措施，但无法完全消除风险。
> 本项目仅供个人学习与自用，请遵守 Telegram 服务条款与目标机器人的使用规则。

---

## ✨ 功能一览

- 🐳 **单容器 Docker 部署** —— 前端已内嵌，一个镜像一个端口，不需要 Nginx
- 👥 **多账号** —— 手机号 / 验证码 / 两步验证 / **二维码** 四种登录方式
- ⏰ **灵活调度** —— 标准 Cron（5 或 6 字段）、每天定点、固定间隔（`30m` / `12h` / `1d`）
- 🎲 **随机延迟** —— 模拟真人行为，降低风控概率（任务级可配）
- 🧩 **可视化动作流编辑器** —— 拖拽卡片编排，不写 JSON
- 🎯 **结果判定** —— 按关键词 / 正则判断签到是否真的成功
- 🔁 **失败重试** —— 按次数上限，或"重试到成功为止"
- ⏪ **错过后补跑** —— 容器重启或宕机错过时间，启动后自动补跑
- 📊 **精美 Web 界面** —— 亮/暗双主题、仪表盘、ECharts 趋势图、实时日志（WebSocket）
- 📣 **多渠道详细推送** —— Telegram Bot / Server酱 / Bark / 企业微信 / 钉钉 / 飞书 / Gotify / Webhook / 邮件
- 🔐 **安全** —— 管理员登录 + 登录限流、Session 与密钥 Fernet 加密落盘、日志脱敏
- 🧠 **AI 识图答题** —— 预留接口，遇到图片验证码/选择题可交给多模态模型（可选）

---

## 🚀 快速开始

### 1. 申请 api_id / api_hash

1. 打开 https://my.telegram.org/apps ，用**你的手机号**登录（会收到 Telegram 内的验证码）
2. 点击 **API development tools**
3. 填写任意 App title 和 Short name（例如 `checkin` / `checkin`），Platform 选 `Desktop`
4. 提交后页面会显示：

   - `App api_id` —— 一串数字，例如 `1234567`
   - `App api_hash` —— 一串 32 位十六进制字符

   把这两个值记下来，等下要用。

### 2. 准备通知 Bot（可选，但推荐）

1. 在 Telegram 里搜索 **@BotFather**，发送 `/newbot`，按提示创建，拿到 **Bot Token**（形如 `123456:ABC-DEF...`）
2. 搜索 **@userinfobot**，给发它任意消息，它会返回你的 **Chat ID**（一串数字）
3. **重要**：先给刚建的 Bot 发一条任意消息（比如 `/start`），否则 Bot 无法主动给你推送

### 3. 启动容器

两种方式任选。

**方式 A：直接用自动构建好的镜像（推荐，无需本地编译）**

```bash
mkdir tg-checkin-panel && cd tg-checkin-panel

# 下载编排文件与环境变量模板
curl -O https://raw.githubusercontent.com/FUJIWARSHINE/tg-checkin-panel/main/docker-compose.ghcr.yml
curl -o .env https://raw.githubusercontent.com/FUJIWARSHINE/tg-checkin-panel/main/.env.example

# 编辑 .env：至少改 ADMIN_PASSWORD 和 TG_PROXY

docker compose -f docker-compose.ghcr.yml up -d
```

**方式 B：从源码构建**

```bash
git clone https://github.com/FUJIWARSHINE/tg-checkin-panel.git
cd tg-checkin-panel

# 复制并修改环境变量
cp .env.example .env
# 编辑 .env：至少改 ADMIN_PASSWORD 和 TG_PROXY

docker compose up -d --build
```

打开浏览器访问 `http://<你的服务器IP>:8000`，用 `.env` 里的账号密码登录。

### 4. 首次配置（在 Web 界面里）

1. **系统设置** → 修改默认密码；确认「全局代理」已填对（国内必填）
2. **账号管理** → 新增账号，填入 `api_id` / `api_hash` → 用手机号或扫码完成登录授权
3. **推送设置** → 新增一个 Telegram Bot 渠道，填入 Bot Token 和 Chat ID → 点「测试推送」确认收到
4. **签到任务** → 新建任务：
   - 选择账号
   - 填签到目标（点「从会话列表选择」可列出你所有机器人和群组）
   - 用可视化编辑器拖出动作流（默认已给出一个可用的模板）
   - 设调度（例如 `0 8 * * *` 表示每天 08:00）、随机延迟、成功关键词
   - 勾选推送渠道与事件
5. 点「保存并立即执行」验证一次 → 去「签到记录」看结果

---

## 🧩 动作流支持的步骤

| 步骤 | 作用 | 关键参数 |
|---|---|---|
| **发送文本** | 发送 `/checkin` 之类的指令 | `text`（支持变量）、`delay_after`、`delete_after` |
| **发送骰子** | 发送 🎲 等随机表情 | `emoji`、`wait_result` |
| **点击按钮** | 点击回复上的键盘按钮 | `text`（按钮文字）或 `index` |
| **等待回复** | 等目标回复，可按关键词过滤 | `timeout`、`match.mode`、`match.keyword` |
| **AI 识图答题** | 把图片交大模型选答案（需开启 AI） | `prompt`、`options`、`click` |
| **条件分支** | 命中条件则结束 / 判成功 / 判失败 | `if`、`op`、`value`、`then` |
| **等待** | 显式等待若干秒 | `seconds` |
| **正则提取** | 从回复里提取积分等数值 | `regex`、`as`、`group` |

**可用变量**：`{last_reply}` 最近收到的回复、`{date}` 今天日期、`{task}` 任务名、`{target}` 目标。
用「正则提取」定义的自定义变量（如 `reward_text`）会被后续步骤和推送消息引用。

### 一个典型签到流程（默认模板）

```json
[
  { "type": "send_text", "text": "/checkin", "delay_after": 2 },
  { "type": "wait_reply", "timeout": 25, "match": { "mode": "contains", "keyword": "签到" } },
  { "type": "click_button", "text": "签到", "delay_after": 1 },
  { "type": "wait_reply", "timeout": 25, "match": { "mode": "regex", "keyword": "签到成功|已签到|获得|积分" } },
  { "type": "extract", "regex": "积分[+＋]?(\\d+)", "as": "reward_text" },
  { "type": "condition", "if": "{last_reply}", "op": "contains", "value": "已签到", "then": "stop" }
]
```

---

## ⚙️ 调度写法

| 类型 | 写法示例 | 含义 |
|---|---|---|
| Cron（5 字段） | `0 8 * * *` | 每天 08:00 |
| Cron（6 字段，含秒） | `30 0 8 * * *` | 每天 08:00:30 |
| 每天定点 | `08:00` 或 `08:00:30` | 每天 8 点（可在任务里单独指定时区） |
| 固定间隔 | `30m` / `12h` / `1d` | 每 30 分钟 / 12 小时 / 1 天 |

编辑界面会实时显示**接下来的执行时间**，填错会立刻报错。

另外：

- **随机延迟** `±N 秒`：触发后在 0~N 秒内随机延迟执行（默认 300 秒）
- **补跑**：勾选后，容器启动时若发现"今天本该签到但没成功"，会自动补跑一次
- **重试**：失败后按配置间隔重试；勾选「重试到成功为止」则一直重试（有硬上限保护）

---

## 🐳 部署说明

### 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `ADMIN_USERNAME` | 管理端用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理端密码（**务必修改**） | `admin123` |
| `SECRET_KEY` | JWT 签名密钥，留空自动生成到 `data/.jwt_secret` | 空 |
| `MASTER_KEY` | Fernet 加密密钥，留空自动生成到 `data/.master_key` | 空 |
| `TZ` | 容器时区 | `Asia/Shanghai` |
| `TG_PROXY` | 全局 Telegram 代理 | 空 |
| `DEBUG` | 调试模式（输出更多日志） | `false` |

### 代理怎么填

| 部署环境 | 代理地址写法 |
|---|---|
| Docker Desktop (Windows / macOS) | `socks5://host.docker.internal:7890` |
| Linux 宿主机 | `socks5://172.17.0.1:7890` 或宿主机内网 IP |
| 代理在另一个容器 | `socks5://<容器名>:1080` |

compose 里已加 `extra_hosts: host.docker.internal:host-gateway`，Linux 上也能直接用这个域名。

### 数据持久化

所有状态都在挂载卷 `./data` 里：

```
data/
├── app.db                 # SQLite：账号/任务/记录/推送渠道
├── sessions/              # Telegram 会话文件（*.session）
├── logs/app.log           # 运行日志
├── .master_key            # Fernet 加密密钥（自动生成）
├── .jwt_secret            # JWT 密钥（自动生成）
└── .admin.json            # 管理员账号（bcrypt 哈希）
```

> 备份：直接在「系统设置」里点「下载数据库备份」，或者整个 `data/` 目录拷走即可。
> 注意 `data/` 含敏感信息，**不要提交到公开仓库**。

### 常用命令

```bash
docker compose up -d --build     # 构建并启动
docker compose logs -f           # 看日志
docker compose restart           # 重启
docker compose down              # 停止
docker compose up -d --build --force-recreate   # 改代码后重建
```

---

## 🔄 镜像与自动发布

镜像发布在 GitHub Container Registry（GHCR），**无需配置任何 Secret**，靠仓库自带的 `GITHUB_TOKEN` 推送。

```bash
docker pull ghcr.io/fujiwarshine/tg-checkin-panel:latest
```

### 标签规则

| 触发条件 | 生成的镜像标签 | 说明 |
|---|---|---|
| 推送 tag `v1.2.3` | `1.2.3`、`1.2`、`1`、`latest` | **正式发版**，同时自动创建 GitHub Release |
| 推送到 `main` 分支 | `edge`、`sha-xxxxxxx` | 最新开发版，不动 `latest` |
| 手动运行工作流 | `edge`、`sha-xxxxxxx` | 可勾选是否推送 |

镜像同时支持 `linux/amd64` 与 `linux/arm64`（群晖 / 树莓派 / Apple Silicon 可直接用）。

### 发新版本（三步）

```bash
# 1. 改版本号（两处保持一致：VERSION 文件 + CHANGELOG）
echo "1.1.0" > VERSION
# 顺手在 CHANGELOG.md 顶部加一节 [1.1.0]

# 2. 提交
git add VERSION CHANGELOG.md
git commit -m "chore(release): v1.1.0"
git push

# 3. 打 tag 并推送 —— 这一步自动触发镜像构建与发布
git tag v1.1.0
git push origin v1.1.0
```

推完 tag 后，GitHub Actions 会自动：

1. **校验** —— 检查 `VERSION` 文件与 tag 是否一致、跑后端冒烟测试、构建前端（任一失败则不出镜像）
2. **构建** —— 多架构镜像推送到 GHCR，打上 `1.1.0` / `1.1` / `1` / `latest`
3. **发布** —— 创建 GitHub Release，附自动生成的变更说明

进度和结果都在仓库的 **Actions** 页查看。

> 忘了改 `VERSION` 就直接打 tag 会**卡在第一关**并给出明确报错，不会产出版本号错乱的镜像。

### 在服务器上更新到新版本

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

`./data` 卷不动，账号、任务、签到记录都不会丢。

### 本地构建多架构镜像（可选）

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg APP_VERSION=1.1.0 \
  -t tg-checkin-panel:1.1.0 .
```

---

## 🛠 本地开发

```bash
# 后端
cd backend
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -r requirements.txt
set DATA_DIR=./data && set ADMIN_PASSWORD=admin123  # Windows
uvicorn app.main:app --reload --port 8000

# 前端（另开一个终端）
cd frontend
npm install
npm run dev        # http://localhost:5173 ，已配置 /api 与 /ws 代理到 8000
```

前端构建产物会自动被后端托管：

```bash
cd frontend && npm run build     # 输出到 frontend/dist
```

Docker 镜像里是多阶段构建（Node 构建前端 → Python 运行时拷贝 `dist` 到 `/app/static`），
所以本地只需 `docker compose up -d --build`。

### 冒烟测试

不依赖真实 Telegram 网络，验证建库、鉴权、任务 CRUD、调度校验、推送渠道、加密往返等：

```bash
python backend/tests/smoke.py
```

---

## 📁 项目结构

```
TG自动签到面板/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口、生命周期、静态资源托管
│   │   ├── settings.py        # 环境变量配置
│   │   ├── models.py          # ORM：账号/任务/模板/记录/推送渠道
│   │   ├── schemas.py         # 请求响应 DTO（含动作流与 cron 校验）
│   │   ├── security.py        # bcrypt / JWT / Fernet 加密 / 登录限流
│   │   ├── runtime_config.py  # Web 端可改的运行设置
│   │   ├── admin_store.py     # 管理员账号存储
│   │   ├── logging_setup.py   # 日志环形缓冲 + WebSocket 广播
│   │   ├── api/               # auth / accounts / tasks / records / notify / system / ws
│   │   └── core/
│   │       ├── client_pool.py # Telethon 客户端池：单例 + 串行化 + FloodWait 重试
│   │       ├── login.py       # 手机号 / 验证码 / 2FA / 二维码 登录状态机
│   │       ├── actions.py     # 8 种动作流步骤执行器
│   │       ├── runner.py      # 单次执行编排：跑流程 → 判定 → 落库 → 推送 → 重试
│   │       ├── scheduler.py   # APScheduler 封装、随机延迟、补跑
│   │       ├── notifier.py    # 9 种推送渠道适配器 + 静默/合并降噪
│   │       └── ai.py          # AI 识图（预留）
│   └── tests/smoke.py         # 冒烟测试（61 项）
├── frontend/                  # Vue 3 + Vite + TS + Naive UI + ECharts
├── .github/
│   ├── workflows/
│   │   ├── docker-publish.yml # tag 触发：多架构构建 + 推 GHCR + 创建 Release
│   │   └── ci.yml             # PR 触发：后端冒烟 + 前端构建
│   └── dependabot.yml         # 依赖自动更新
├── Dockerfile                 # 多阶段构建
├── docker-compose.yml         # 源码构建部署
├── docker-compose.ghcr.yml    # 直接拉取官方镜像部署
├── VERSION                    # 版本号（发版时改这里）
├── CHANGELOG.md
├── .env.example
└── README.md
```

---

## ❓ 常见问题

**Q：登录时收不到验证码？**
A：Telegram 的验证码默认发到**已登录的 Telegram 客户端**里（不是短信）。如果登录不上，可在
账号登录弹窗里重试，或在其他设备上先退出多余会话。

**Q：提示 `Connection to Telegram failed`？**
A：网络不通。检查「系统设置」里的全局代理，确认容器内能访问 Telegram。
可以在容器里执行 `curl -x socks5://host.docker.internal:7890 https://api.telegram.org` 验证。

**Q：签到失败但机器人其实回复了？**
A：多半是**成功关键词**没覆盖到。到「签到记录」点开详情，看「完整回复」原文，
把实际出现的词（比如"您今天已经签到过了"）加进任务的成功关键词里。

**Q：能同时用几个账号、几个任务？**
A：都可以。同一账号的 API 调用会自动串行化（防 FloodWait），全局并发可在「系统设置」里调。

**Q：任务到点没执行？**
A：① 看「系统设置」里调度器是否"运行中"；② 确认任务已启用；③ 看「实时日志」有没有报错；
④ 时区是否设对。可点「立即补跑未完成任务」。

**Q：怎么升级？**
A：用官方镜像的话拉一下就行：

```bash
docker compose -f docker-compose.ghcr.yml pull && docker compose -f docker-compose.ghcr.yml up -d
```

源码构建的话 `git pull` 后 `docker compose up -d --build`。`data/` 卷不动，数据不会丢。

---

## 📄 License

MIT License，详见 [LICENSE](LICENSE)。

仅供个人学习与自用。使用者需自行承担使用风险，包括但不限于 Telegram 账号被限制的风险。
请遵守 Telegram 服务条款与目标机器人的使用规则。
