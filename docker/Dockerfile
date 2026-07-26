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
COPY config ./config

RUN pip install --no-cache-dir -e ".[google,trends]"

EXPOSE 8765
CMD ["seoagents", "dashboard", "--host", "0.0.0.0", "--port", "8765"]
