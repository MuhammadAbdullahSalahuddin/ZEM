# ---- Stage 1: build the dashboard ----
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- Stage 2: the ZEM service ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    ZEM_DB=/data/zem.db

RUN pip install --no-cache-dir uv \
    && useradd --create-home --uid 10001 zem \
    && mkdir -p /app /data && chown zem /app /data

WORKDIR /app
USER zem

COPY --chown=zem pyproject.toml uv.lock README.md LICENSE ./
COPY --chown=zem src ./src
RUN uv sync --frozen --no-dev

COPY --chown=zem config ./config
COPY --chown=zem policies ./policies
COPY --chown=zem demo ./demo
COPY --chown=zem tests/fixtures ./tests/fixtures
COPY --from=web --chown=zem /web/dist ./web/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["zem", "serve", "--host", "0.0.0.0", "--port", "8000"]
