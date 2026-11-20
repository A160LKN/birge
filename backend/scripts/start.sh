#!/bin/sh
# Старт контейнера: миграции, демо-данные, сервер. Фоновые задачи работают в том же процессе.
# Один процесс uvicorn: WebSocket-присутствие и обработчик задач рассчитаны на один экземпляр
# (события между несколькими процессами всё равно доходят — через LISTEN/NOTIFY).
set -e
alembic upgrade head
python -m app.seed
# Без --forwarded-allow-ips='*': с ним uvicorn подменял адрес соединения левым адресом из X-Forwarded-For,
# который присылает сам клиент. Адрес клиента для лимитов определяет app/ratelimit.py:client_ip
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
