"""WebSocket доски: /ws/boards/{id}.

Протокол:
1. Клиент подключается и первым сообщением в течение 5 секунд присылает
   {"type": "auth", "token": "...", "last_event_id": 123}.
   Токен — в сообщении, а не в адресе: адреса попадают в логи серверов и прокси.
2. Сервер отвечает {"type": "ready", "presence": [id...]} и досылает события после last_event_id.
3. Дальше сервер присылает события доски и {"type": "presence"}; клиент может слать {"type": "ping"}.

Коды закрытия: 4400 — неверное сообщение, 4401 — нет входа, 4404 — нет доступа к доске или её удалили,
4403 — участника удалили с доски.
"""
import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import settings
from app.db import SessionLocal
from app.errors import AppError
from app.realtime.hub import Client, Hub
from app.security import load_user
from app.services.access import membership

router = APIRouter()


class AuthMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern="^auth$")
    token: str = Field(max_length=2000)
    last_event_id: int = Field(0, ge=0)


async def _reject(websocket: WebSocket, code: int, error: str, message: str) -> None:
    with contextlib.suppress(Exception):
        await websocket.send_json({"type": "error", "code": error, "message": message})
        await websocket.close(code)


@router.websocket("/ws/boards/{board_id}")
async def board_socket(websocket: WebSocket, board_id: int) -> None:
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=settings.ws_auth_timeout_seconds)
        auth = AuthMessage.model_validate_json(raw)
    except TimeoutError:
        return await _reject(websocket, 4401, "auth_timeout", "Не пришло сообщение авторизации")
    except (ValidationError, ValueError, KeyError):
        return await _reject(websocket, 4400, "bad_message", "Первым сообщением ожидается авторизация")
    except WebSocketDisconnect:
        return None

    try:
        async with SessionLocal() as session:
            user = await load_user(session, auth.token)
            await membership(session, board_id, user)
    except AppError as error:
        code = 4401 if error.status == 401 else 4404
        return await _reject(websocket, code, error.code, error.message)

    hub: Hub = websocket.app.state.hub
    client = Client(websocket=websocket, user_id=user.id, board_id=board_id)
    await hub.join(client)
    try:
        await client.send({"type": "ready", "user_id": user.id, "presence": hub.presence(board_id)})
        await hub.resume(client, auth.last_event_id)
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                message = None
            if isinstance(message, dict) and message.get("type") == "ping":
                await client.send({"type": "pong"})
            else:
                await client.send({"type": "error", "code": "bad_message", "message": "Неизвестное сообщение"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await hub.leave(client)
