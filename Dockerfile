# Render (Docker) — 种子视频已随仓库提交，构建自包含、无需外网拉取。
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# ffmpeg + Playwright Chromium 运行所需的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libxshmfence1 libx11-6 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY . /app/

# 构建期把 12 个种子视频 + 封面 + videos.json 烤进镜像
RUN python fetch_seeds.py

EXPOSE 7860
CMD ["python", "server.py"]
