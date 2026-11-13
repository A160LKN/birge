"""Постановка фоновых задач в очередь."""
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job

CHANNEL = "jobs"


async def enqueue(session: AsyncSession, kind: str, payload: dict[str, Any], *,
                  run_at: datetime | None = None, max_attempts: int = 3) -> Job:
    """Задача сохранится вместе с остальной транзакцией: нет данных — нет и задачи, и наоборот.
    pg_notify будит обработчик сразу после коммита, не дожидаясь очередного опроса."""
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts)
    if run_at is not None:
        job.run_at = run_at
    session.add(job)
    await session.flush()
    await session.execute(select(func.pg_notify(CHANNEL, str(job.id))))
    return job
