# ---------- 阶段 1：构建前端 ----------
# 关键：强制跑在构建机原生架构（BUILDPLATFORM）上，而不是目标架构。
# 前端产物（HTML/JS/CSS）与 CPU 架构无关，没必要在 QEMU 模拟的 arm64 里编译 ——
# 那样做会把 npm ci + vite build 拖慢 3~4 倍（实测 8 分钟 → 25 分钟以上）。
FROM --platform=$BUILDPLATFORM node:22-alpine AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN npm run build


# ---------- 阶段 2：Python 运行时 ----------
# 这个阶段必须跑在目标架构上（pip 要装对应架构的二进制 wheel）。
FROM python:3.12-slim

# CI 会传入真实版本号（= git tag）；本地构建时留空则读 VERSION 文件
ARG APP_VERSION=""
ARG VCS_REF="unknown"
ARG IMAGE_SOURCE="https://github.com/FUJIWARESHINE/tg-checkin-panel"

# 注意：这里只能放「每次构建都相同」的变量。
# APP_VERSION 每次构建都不同（tag 是 1.3.1，main 是 0.0.0-dev.N），
# 一旦写进这个 ENV，它下面的 apt-get / pip install 层会 100% 击穿缓存 ——
# 实测每次都要在 QEMU 里重装依赖，多花 4~5 分钟。它被挪到文件末尾了。
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/app ./app
COPY VERSION ./VERSION
COPY --from=web /web/dist ./static

# 以下两层的内容每次都不同（版本号 / commit / 构建时间），必须放在最后：
# 它们只影响自己这一层，不会让上面的 apt-get、pip install 白跑一遍。
ENV APP_VERSION=${APP_VERSION}

LABEL org.opencontainers.image.title="TG 自动签到面板" \
      org.opencontainers.image.description="Telegram 自动签到 + 可视化 Web 面板（单容器部署）" \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.licenses="MIT"

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=6s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
