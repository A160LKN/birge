"""Обработчик очереди фоновых задач.

Задачу забирает запрос UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED): строки, которые уже
взял другой обработчик, пропускаются, поэтому одну задачу не выполнят дважды, а обработчики
не ждут друг друга. Работа задачи и отметка «выполнена» коммитятся вместе.
Если обработчик упал посреди задачи, она остаётся «running» и через job_lock_timeout её
заберёт другой. Ошибка — повтор с растущей паузой; после max_attempts — «failed».
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import psycopg
from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db import listen_dsn
from app.jobs.queue import CHANNEL
from app.models import Event, Job, JobStatus, utcnow

log = logging.getLogger("birge.worker")

Payload = dict[str, Any]


class PermanentJobError(Exception):
    """Повторять бессмысленно: например, файл — не картинка. Задача сразу «failed»."""


@dataclass(frozen=True)
class Handler:
    run: Callable[[AsyncSession, Payload], Awaitable[None]]
    # Вызывается, когда попытки кончились: пометить объект сломанным и сообщить людям
    on_failure: Callable[[AsyncSession, Payload, str], Awaitable[None]] | None = None


HANDLERS: dict[str, Handler] = {}


def handler(kind: str, on_failure: Callable[[AsyncSession, Payload, str], Awaitable[None]] | None = None):
    def register(fn: Callable[[AsyncSession, Payload], Awaitable[None]]):
        HANDLERS[kind] = Handler(fn, on_failure)
        return fn
    return register


_CLAIM = text("""
    UPDATE jobs SET status = 'running', attempts = attempts + 1, locked_at = now()
    WHERE id = (
        SELECT id FROM jobs
        WHERE (status = 'queued' AND run_at <= now())
           OR (status = 'running' AND locked_at < now() - make_interval(secs => :lock_timeout))
        ORDER BY run_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, payload, attempts, max_attempts
""")


def backoff(attempt: int) -> timedelta:
    """Пауза перед повтором: 2 с, 8 с, 32 с… — сбой у внешнего ресурса успеет пройти."""
    return timedelta(seconds=2 * 4 ** (attempt - 1))


async def run_one(factory: async_sessionmaker[AsyncSession]) -> bool:
    """Выполнить одну готовую задачу. False — очередь пуста."""
    async with factory() as session:
        row = (await session.execute(_CLAIM, {"lock_timeout": settings.job_lock_timeout_seconds})).first()
        await session.commit()
    if row is None:
        return False

    job_id, kind, payload, attempts, max_attempts = row
    task = HANDLERS.get(kind)
    try:
        if task is None:
            raise PermanentJobError(f"Неизвестный вид задачи: {kind}")
        async with factory() as session:
            await task.run(session, payload)
            await session.execute(update(Job).where(Job.id == job_id).values(
                status=JobStatus.done, finished_at=utcnow(), locked_at=None, last_error=None))
            await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — любая ошибка задачи не должна ронять обработчик
        error = f"{type(exc).__name__}: {exc}"[:2000]
        final = isinstance(exc, PermanentJobError) or attempts >= max_attempts
        log.warning("Задача %s (%s), попытка %s/%s: %s", job_id, kind, attempts, max_attempts, error)
        async with factory() as session:
            if final:
                await session.execute(update(Job).where(Job.id == job_id).values(
                    status=JobStatus.failed, finished_at=utcnow(), locked_at=None, last_error=error))
                if task is not None and task.on_failure is not None:
                    await task.on_failure(session, payload, error)
            else:
                await session.execute(update(Job).where(Job.id == job_id).values(
                    status=JobStatus.queued, run_at=utcnow() + backoff(attempts), locked_at=None,
                    last_error=error))
            await session.commit()
        return True


async def drain(factory: async_sessionmaker[AsyncSession], limit: int = 100) -> int:
    """Выполнить все готовые задачи. Возвращает, сколько обработано."""
    done = 0
    while done < limit and await run_one(factory):
        done += 1
    return done


async def cleanup_events(factory: async_sessionmaker[AsyncSession]) -> int:
    """Журнал событий нужен только чтобы догнать пропущенное после обрыва связи — старое удаляем."""
    async with factory() as session:
        result = await session.execute(delete(Event).where(
            Event.created_at < utcnow() - timedelta(hours=settings.event_retention_hours)))
        await session.commit()
        return result.rowcount


async def worker_loop(factory: async_sessionmaker[AsyncSession], stop: asyncio.Event) -> None:
    """Работает рядом с API. Просыпается по pg_notify и на всякий случай — раз в worker_poll_seconds."""
    from app.jobs import tasks  # noqa: F401 — регистрирует обработчики

    last_cleanup = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        try:
            async with await psycopg.AsyncConnection.connect(listen_dsn(), autocommit=True) as conn:
                await conn.execute(f"LISTEN {CHANNEL}")
                while not stop.is_set():
                    await drain(factory)
                    if loop.time() - last_cleanup > 3600:
                        await cleanup_events(factory)
                        last_cleanup = loop.time()
                    async for _ in conn.notifies(timeout=settings.worker_poll_seconds, stop_after=1):
                        pass
        except asyncio.CancelledError:
            raise
        except Exception:  # соединение с БД оборвалось — подождём и подключимся заново
            log.exception("Обработчик задач: ошибка, перезапуск через 5 с")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass
