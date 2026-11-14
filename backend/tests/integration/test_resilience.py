"""Устойчивость: обработчик задач просыпается сразу, рассылка переживает обрыв соединения с БД."""
import asyncio

import pytest
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.jobs.queue import enqueue
from app.jobs.worker import HANDLERS, Handler, worker_loop
from app.realtime import hub as hub_module
from tests.conftest import connect, receive_type, sync_engine

pytestmark = pytest.mark.integration


async def test_worker_wakes_up_on_notify_without_waiting_for_poll(db_session, monkeypatch):
    """Опрос раз в 30 секунд, а задача выполняется за доли секунды — её будит pg_notify."""
    monkeypatch.setattr(settings, "worker_poll_seconds", 30)
    done = asyncio.Event()

    async def work(session, payload):
        done.set()

    monkeypatch.setitem(HANDLERS, "wake", Handler(work))
    stop = asyncio.Event()
    worker = asyncio.create_task(worker_loop(SessionLocal, stop))
    await asyncio.sleep(0.3)  # обработчик подключился и слушает
    try:
        await enqueue(db_session, "wake", {})
        await db_session.commit()
        await asyncio.wait_for(done.wait(), timeout=3)
    finally:
        stop.set()
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker


def _kill_listener() -> int:
    with sync_engine.begin() as conn:
        return conn.execute(text(
            "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
            "WHERE query = 'LISTEN board_events' AND datname = current_database() "
            "AND pid <> pg_backend_pid()")).scalar()


@pytest.mark.api
def test_events_survive_lost_listen_connection(alice, bob, team, monkeypatch):
    """База оборвала соединение LISTEN (рестарт, сеть). Событие, случившееся без слушателя,
    не теряется: после переподключения сервер сам дочитывает журнал и досылает его клиентам."""
    monkeypatch.setattr(hub_module, "RECONNECT_DELAY", 0.2)
    last = bob.get(f"/boards/{team['id']}").json()["last_event_id"]
    with connect(bob, team["id"], last_event_id=last) as ws:
        assert _kill_listener() == 1
        alice.card(team["columns"][0]["id"], "Создана во время обрыва")
        event = receive_type(ws, "card.created", timeout=5)
        assert event["data"]["title"] == "Создана во время обрыва"
