# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv
# 與 backend 相同：禁止 uv 下載 Python，venv 指向映像內的直譯器，複製到 runtime 才能用
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app.py ./
COPY utils ./utils
COPY views ./views
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8501
# exec 形式：streamlit 為 PID 1，直接收到 SIGTERM
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
