#!/bin/sh
# Старт контейнера: миграции, демо-данные, сервер. Фоновые задачи работают в том же процессе.
# Один процесс uvicorn: WebSocket-присутствие и обработчик задач рассчитаны на один экземпляр
# (события между несколькими процессами всё равно доходят — через LISTEN/NOTIFY).
set -e
alembic upgrade head
python -m app.seed
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
