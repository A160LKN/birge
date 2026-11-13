"""Рассылка событий по WebSocket.

Один процесс держит одно соединение LISTEN board_events. Пришло уведомление «доска:событие» —
если на этой доске есть подключённые клиенты этого процесса, событие читается из журнала и
отправляется им. Так работает и при нескольких процессах API: каждый слушает PostgreSQL сам.

Присутствие («кто сейчас на доске») считается в пределах процесса — на бесплатном хостинге он один.
"""
import asyncio
import contextlib
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import psycopg
from fastapi import WebSocket
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import listen_dsn
from app.models import Event
from app.realtime.events import CHANNEL, envelope

log = logging.getLogger("birge.hub")

SEND_TIMEOUT = 5.0     # клиент не принял сообщение за 5 секунд — отключаем, чтобы не тормозил остальных
RESUME_LIMIT = 500     # пропустил больше — проще перезагрузить доску целиком
CLOSE_REMOVED = 4403   # участника удалили с доски
CLOSE_DELETED = 4404   # доску удалили
RECONNECT_DELAY = 2.0  # пауза перед переподключением LISTEN после обрыва


@dataclass(eq=False)
class Client:
    websocket: WebSocket
    user_id: int
    board_id: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Номера уже отправленных событий: при догонялке и живой рассылке одновременно ничего не придёт дважды.
    # Множество, а не «последний номер»: транзакции коммитятся не строго в порядке номеров
    sent: deque[int] = field(default_factory=lambda: deque(maxlen=1000))

    async def send(self, message: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(self.websocket.send_text(json.dumps(message, ensure_ascii=False)), SEND_TIMEOUT)
            return True
        except Exception:  # noqa: BLE001 — разорванное или зависшее соединение
            return False

    async def deliver(self, event: Event) -> bool:
        async with self.lock:
            if event.id in self.sent:
                return True
            self.sent.append(event.id)
            return await self.send(envelope(event))


class Hub:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self.factory = factory
        self.rooms: dict[int, set[Client]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    # ---------- Подключения ----------

    def presence(self, board_id: int) -> list[int]:
        return sorted({client.user_id for client in self.rooms.get(board_id, ())})

    async def join(self, client: Client) -> None:
        before = self.presence(client.board_id)
        self.rooms[client.board_id].add(client)
        if self.presence(client.board_id) != before:
            await self._broadcast_presence(client.board_id, exclude=client)

    async def leave(self, client: Client) -> None:
        room = self.rooms.get(client.board_id)
        if room is None or client not in room:
            return
        room.discard(client)
        if not room:
            del self.rooms[client.board_id]
        if client.user_id not in self.presence(client.board_id):
            await self._broadcast_presence(client.board_id)

    async def _broadcast_presence(self, board_id: int, exclude: Client | None = None) -> None:
        message = {"type": "presence", "users": self.presence(board_id)}
        clients = [c for c in self.rooms.get(board_id, ()) if c is not exclude]
        await asyncio.gather(*(c.send(message) for c in clients))

    async def resume(self, client: Client, last_event_id: int) -> None:
        """Отправить события, пропущенные с last_event_id. Слишком много или журнал уже очищен — resync."""
        async with self.factory() as session:
            oldest = await session.scalar(select(func.min(Event.id)))
            events = (await session.scalars(
                select(Event).where(Event.board_id == client.board_id, Event.id > last_event_id)
                .order_by(Event.id).limit(RESUME_LIMIT + 1))).all()
        if len(events) > RESUME_LIMIT or (oldest is not None and last_event_id < oldest - 1 and last_event_id > 0):
            await client.send({"type": "resync"})
            return
        for event in events:
            if not await client.deliver(event):
                return

    # ---------- Рассылка ----------

    async def dispatch(self, board_id: int, event_id: int) -> None:
        clients = list(self.rooms.get(board_id, ()))
        if not clients:
            return  # на этой доске у процесса никого — даже не читаем событие
        async with self.factory() as session:
            event = await session.get(Event, event_id)
        if event is None:
            return
        results = await asyncio.gather(*(c.deliver(event) for c in clients))
        for client, ok in zip(clients, results, strict=True):
            if not ok:
                await self._drop(client, 1011)
        if event.type == "member.removed":
            for client in [c for c in clients if c.user_id == event.data.get("user_id")]:
                await self._drop(client, CLOSE_REMOVED)
        elif event.type == "board.deleted":
            for client in clients:
                await self._drop(client, CLOSE_DELETED)

    async def _drop(self, client: Client, code: int) -> None:
        await self.leave(client)
        with contextlib.suppress(Exception):
            await client.websocket.close(code)

    # ---------- Прослушивание PostgreSQL ----------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen())
        # Ждём LISTEN: события, которые произойдут после старта, не потеряются
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._ready.wait(), timeout=10)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        for client in [c for room in self.rooms.values() for c in room]:
            with contextlib.suppress(Exception):
                await client.websocket.close(1012)  # сервер перезапускается — клиент переподключится
        self.rooms.clear()

    async def _listen(self) -> None:
        first = True
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(listen_dsn(), autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self._ready.set()
                    if not first:
                        await self._catch_up()  # пока не слушали, могли пропустить события
                    first = False
                    async for notify in conn.notifies():
                        board_id, _, event_id = notify.payload.partition(":")
                        try:
                            await self.dispatch(int(board_id), int(event_id))
                        except Exception:
                            log.exception("Не удалось разослать событие %s", notify.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Соединение LISTEN оборвалось, переподключение")
                await asyncio.sleep(RECONNECT_DELAY)

    async def _catch_up(self) -> None:
        for clients in list(self.rooms.values()):
            for client in list(clients):
                last = max(client.sent, default=0)
                await self.resume(client, last)
