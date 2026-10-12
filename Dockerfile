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

# Dependencies first, so editing code does not reinstall everything.
COPY --chown=zem pyproject.toml uv.lock README.md ./
COPY --chown=zem src ./src
RUN uv sync --frozen --no-dev

COPY --chown=zem policies ./policies
COPY --chown=zem demo ./demo

# R1 default: run the 6 scenarios, then print the decision log.
CMD ["sh", "-c", "python demo/run_scenarios.py && zem log"]
