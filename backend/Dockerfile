# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv
# 禁止 uv 自行下載 Python：venv 必須指向映像內的 /usr/local/bin/python3.12，
# 複製到同基底的 runtime 階段後直譯器路徑才會一致
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 測試用：在 builder 之上補裝 dev 依賴，只給 compose 的 api-test 服務使用
FROM builder AS test
RUN uv sync --frozen
COPY . .
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
CMD ["pytest", "-q"]

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY --chmod=755 entrypoint.sh ./
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
