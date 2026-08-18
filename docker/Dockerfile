# SEOAgents application container
FROM python:3.11-slim

# Node.js for Lighthouse subprocess audits (optional but recommended)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg chromium \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_PATH=/usr/bin/chromium \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY seoagents ./seoagents
# dojocore 是联邦框架层，pyproject 的 packages.find 已包含它，但此前漏了这行
# COPY —— 构建时目录不在镜像里，setuptools 就注册不到，editable finder 里
# 只有 seoagents。运行时靠 compose 的 PYTHONPATH=/app + working_dir 撑着，
# 换个 cwd 就 ModuleNotFoundError。见 issue #18。
COPY dojocore ./dojocore
COPY config ./config

RUN pip install --no-cache-dir -e ".[google,trends,mcp]"

EXPOSE 8765
CMD ["seoagents", "dashboard", "--host", "0.0.0.0", "--port", "8765"]
