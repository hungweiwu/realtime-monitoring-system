#!/bin/sh
set -e

alembic upgrade head
python -m app.seed

# exec 讓 uvicorn 取代 shell 成為 PID 1，才收得到 docker stop 的 SIGTERM 並執行 lifespan 關機流程
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
