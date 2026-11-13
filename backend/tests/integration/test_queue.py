"""Очередь фоновых задач на настоящем PostgreSQL."""
import asyncio
from collections import Counter
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.db import SessionLocal
from app.jobs.queue import enqueue
from app.jobs.worker import HANDLERS, Handler, PermanentJobError, drain, run_one
from app.models import Job, JobStatus, utcnow

pytestmark = pytest.mark.integration


@pytest.fixture
def register(monkeypatch):
    """Временный обработчик задач для теста."""
    def add(kind, run, on_failure=None):
        monkeypatch.setitem(HANDLERS, kind, Handler(run, on_failure))
    return add


async def _jobs(session) -> list[Job]:
    session.expire_all()
    return list((await session.scalars(select(Job).order_by(Job.id))).all())


async def test_five_workers_run_each_job_exactly_once(db_session, register):
    """30 задач, 5 обработчиков одновременно, у каждого своё соединение с БД.
    Без SKIP LOCKED обработчики либо ждали бы друг друга, либо выполняли одну задачу дважды."""
    runs: Counter[int] = Counter()

    async def slow(session, payload):
        runs[payload["n"]] += 1
        await asyncio.sleep(0.01)  # задача «работает» — в это время другие обработчики берут следующие

    register("slow", slow)
    for n in range(30):
        await enqueue(db_session, "slow", {"n": n})
    await db_session.commit()

    done = await asyncio.gather(*(drain(SessionLocal) for _ in range(5)))

    assert sum(done) == 30
    assert runs == Counter(range(30))  # каждая ровно один раз
    assert max(done) < 30  # работу действительно разделили, а не один сделал всё
    assert {job.status for job in await _jobs(db_session)} == {JobStatus.done}


async def test_failed_job_is_retried_with_growing_pause(db_session, register):
    calls = []

    async def flaky(session, payload):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("внешний сервис недоступен")

    register("flaky", flaky)
    await enqueue(db_session, "flaky", {})
    await db_session.commit()

    assert await run_one(SessionLocal)
    (job,) = await _jobs(db_session)
    assert job.status == JobStatus.queued and job.attempts == 1
    assert "ConnectionError" in job.last_error
    pause = job.run_at - utcnow()
    assert timedelta(seconds=1) < pause <= timedelta(seconds=2)

    assert not await run_one(SessionLocal)  # пауза ещё не прошла — задачу не берут

    for _ in range(2):  # «проматываем время» и даём ещё две попытки
        await db_session.execute(update(Job).values(run_at=utcnow()))
        await db_session.commit()
        assert await run_one(SessionLocal)

    (job,) = await _jobs(db_session)
    assert job.status == JobStatus.done and job.attempts == 3 and job.last_error is None


async def test_job_fails_after_last_attempt_and_reports(db_session, register):
    failures = []

    async def broken(session, payload):
        raise RuntimeError("сломано")

    async def on_failure(session, payload, error):
        failures.append((payload, error))

    register("broken", broken, on_failure)
    await enqueue(db_session, "broken", {"x": 1}, max_attempts=2)
    await db_session.commit()

    await run_one(SessionLocal)
    await db_session.execute(update(Job).values(run_at=utcnow()))
    await db_session.commit()
    await run_one(SessionLocal)

    (job,) = await _jobs(db_session)
    assert job.status == JobStatus.failed and job.attempts == 2
    assert failures == [({"x": 1}, "RuntimeError: сломано")]


async def test_permanent_error_is_not_retried(db_session, register):
    async def hopeless(session, payload):
        raise PermanentJobError("это не картинка")

    register("hopeless", hopeless)
    await enqueue(db_session, "hopeless", {})
    await db_session.commit()
    await run_one(SessionLocal)
    (job,) = await _jobs(db_session)
    assert job.status == JobStatus.failed and job.attempts == 1


async def test_unknown_job_kind_fails_instead_of_looping(db_session):
    await enqueue(db_session, "no-such-kind", {})
    await db_session.commit()
    await run_one(SessionLocal)
    (job,) = await _jobs(db_session)
    assert job.status == JobStatus.failed and "Неизвестный вид" in job.last_error


async def test_work_is_rolled_back_when_job_fails(db_session, register):
    """Работа задачи и отметка «выполнена» — одна транзакция: упала задача — её изменения откатились."""
    async def half_done(session, payload):
        await enqueue(session, "side-effect", {})  # любое изменение в БД
        raise RuntimeError("упала на середине")

    register("half", half_done)
    await enqueue(db_session, "half", {}, max_attempts=1)
    await db_session.commit()
    await run_one(SessionLocal)
    assert [j.kind for j in await _jobs(db_session)] == ["half"]


async def test_stuck_job_is_picked_up_again(db_session, register):
    """Обработчик упал посреди задачи (сервер перезапустили) — задача не должна висеть вечно."""
    runs = []

    async def work(session, payload):
        runs.append(1)

    register("work", work)
    job = await enqueue(db_session, "work", {})
    await db_session.commit()
    await db_session.execute(update(Job).where(Job.id == job.id).values(
        status=JobStatus.running, attempts=1, locked_at=utcnow() - timedelta(minutes=10)))
    await db_session.commit()

    assert await run_one(SessionLocal)
    (job,) = await _jobs(db_session)
    assert runs == [1] and job.status == JobStatus.done and job.attempts == 2


async def test_running_job_is_not_taken_twice(db_session, register):
    async def work(session, payload):
        pass

    register("work", work)
    job = await enqueue(db_session, "work", {})
    await db_session.commit()
    await db_session.execute(update(Job).where(Job.id == job.id).values(
        status=JobStatus.running, attempts=1, locked_at=utcnow()))
    await db_session.commit()
    assert not await run_one(SessionLocal)  # свежая блокировка — задачу выполняет кто-то другой


async def test_job_from_rolled_back_transaction_does_not_exist(db_session):
    """Задача ставится в той же транзакции, что и данные: откат — и задачи нет."""
    await enqueue(db_session, "thumbnail", {"attachment_id": 1})
    await db_session.rollback()
    assert await _jobs(db_session) == []
