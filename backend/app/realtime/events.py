"""Публикация событий доски: запись в журнал + pg_notify в той же транзакции."""
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Activity, Event, User

CHANNEL = "board_events"


async def publish(session: AsyncSession, board_id: int, type_: str, data: dict[str, Any], *,
                  actor: User | None = None, client_id: str | None = None,
                  activity: tuple[str, str] | None = None) -> Event:
    """Событие уйдёт подписчикам только после коммита транзакции — и только если она закоммитится.

    activity=(вид, текст) — заодно запись в ленту действий доски, её получат в том же событии.
    """
    if activity is not None:
        kind, message = activity
        entry = Activity(board_id=board_id, actor_id=actor.id if actor else None, kind=kind, message=message)
        session.add(entry)
        await session.flush()
        data = {**data, "activity": {
            "id": entry.id, "kind": kind, "message": message, "created_at": entry.created_at.isoformat(),
            "actor": {"id": actor.id, "name": actor.name, "email": actor.email} if actor else None}}
    event = Event(board_id=board_id, type=type_, actor_id=actor.id if actor else None,
                  client_id=client_id, data=data)
    session.add(event)
    await session.flush()
    await session.execute(select(func.pg_notify(CHANNEL, f"{board_id}:{event.id}")))
    return event


def envelope(event: Event) -> dict[str, Any]:
    """Как событие выглядит для клиента."""
    return {"type": event.type, "id": event.id, "board_id": event.board_id, "actor_id": event.actor_id,
            "client_id": event.client_id, "data": event.data}
