# ---------- 阶段 1：构建前端 ----------
FROM node:26-alpine AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN npm run build


# ---------- 阶段 2：Python 运行时 ----------
FROM python:3.12-slim

# CI 会传入真实版本号（= git tag）；本地构建时留空则读 VERSION 文件
ARG APP_VERSION=""
ARG VCS_REF="unknown"
ARG BUILD_DATE=""
ARG IMAGE_SOURCE="https://github.com/FUJIWARESHINE/tg-checkin-panel"

LABEL org.opencontainers.image.title="TG 自动签到面板" \
      org.opencontainers.image.description="Telegram 自动签到 + 可视化 Web 面板（单容器部署）" \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT"

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    APP_VERSION=${APP_VERSION}

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

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=6s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
