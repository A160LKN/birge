"""Общие фикстуры. Тесты работают с настоящим PostgreSQL — отдельной базой birge_test.

Схема создаётся теми же миграциями Alembic, что и в продакшене. Фоновый обработчик задач
в тестах выключен: задачи запускаются вручную через run_jobs — тест сам решает, когда.
"""
import os

os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL",
                                       "postgresql+psycopg://birge:birge@localhost:5432/birge_test")
os.environ["WORKER_ENABLED"] = "false"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-32b"

import json  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from itertools import count  # noqa: E402
from typing import Any  # noqa: E402

import anyio  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.jobs import tasks  # noqa: E402, F401 — регистрирует обработчики задач
from app.jobs.worker import drain  # noqa: E402
from app.main import app  # noqa: E402

TABLES = ("users, boards, board_members, columns, cards, comments, attachments, attachment_blobs, "
          "activity, events, exports, jobs")
PASSWORD = "secret-pass-123"
_ids = count(1)
sync_engine = create_engine(settings.database_url)


@pytest.fixture(scope="session")
def database():
    # Предохранитель: тесты стирают базу целиком — рабочую базу по ошибке не тронем
    if "test" not in (sync_engine.url.database or ""):
        pytest.exit(f"Тесты запускаются только на базе с «test» в имени, а указана «{sync_engine.url.database}»",
                    returncode=2)
    with sync_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    command.upgrade(Config("alembic.ini"), "head")
    yield sync_engine
    sync_engine.dispose()


@pytest.fixture(autouse=True)
def clean(request, database):
    if request.node.get_closest_marker("unit"):
        yield
        return
    with database.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
async def db_session():
    """Асинхронная сессия для интеграционных тестов. Пул закрывается после теста:
    соединения привязаны к циклу событий, а у каждого асинхронного теста он свой."""
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


# ---------- Помощники ----------

class User:
    def __init__(self, client: TestClient, email: str, name: str):
        self.client, self.email, self.name = client, email, name
        response = client.post("/auth/register", json={"email": email, "name": name, "password": PASSWORD})
        assert response.status_code == 201, response.text
        body = response.json()
        self.id: int = body["user"]["id"]
        self.token: str = body["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def get(self, url: str, **kw):
        return self.client.get(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def post(self, url: str, **kw):
        return self.client.post(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def patch(self, url: str, **kw):
        return self.client.patch(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def delete(self, url: str, **kw):
        return self.client.delete(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def board(self, title: str = "Релиз") -> dict[str, Any]:
        response = self.post("/boards", json={"title": title})
        assert response.status_code == 201, response.text
        return response.json()

    def card(self, column_id: int, title: str = "Задача", **extra) -> dict[str, Any]:
        response = self.post("/cards", json={"column_id": column_id, "title": title, **extra})
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture
def make_user(client):
    def make(name: str = "Айбол", email: str | None = None) -> User:
        return User(client, email or f"user{next(_ids)}@test.kz", name)
    return make


@pytest.fixture
def alice(make_user):
    return make_user("Алия")


@pytest.fixture
def bob(make_user):
    return make_user("Бауыржан")


@pytest.fixture
def team(alice, bob):
    """Доска Алии, Бауыржан — участник."""
    board = alice.board()
    assert alice.post(f"/boards/{board['id']}/members", json={"email": bob.email}).status_code == 201
    return board


@pytest.fixture
def run_jobs(client):
    """Выполнить фоновые задачи в цикле событий приложения — так же, как это делает обработчик."""
    def run() -> int:
        return client.portal.call(drain, SessionLocal)
    return run


# ---------- WebSocket ----------

class Closed(Exception):
    def __init__(self, code: int):
        super().__init__(f"WebSocket закрыт с кодом {code}")
        self.code = code


def receive(ws, timeout: float = 3.0) -> dict[str, Any]:
    """Следующее сообщение с таймаутом: без него упавший тест висел бы вечно.
    _send_rx — внутренняя очередь TestClient, публичного способа задать таймаут нет."""
    async def _receive():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()
    message = ws.portal.call(_receive)
    if message["type"] == "websocket.close":
        raise Closed(message.get("code", 1000))
    return json.loads(message["text"])


def receive_type(ws, type_: str, timeout: float = 3.0) -> dict[str, Any]:
    """Пропустить сообщения других типов (например, presence) до нужного."""
    while True:
        message = receive(ws, timeout)
        if message["type"] == type_:
            return message


def nothing_more(ws, timeout: float = 0.5) -> bool:
    try:
        message = receive(ws, timeout)
    except TimeoutError:
        return True
    raise AssertionError(f"Не ожидали сообщения, а пришло: {message}")


@contextmanager
def connect(user: User, board_id: int, last_event_id: int = 0):
    """Подключиться к доске и пройти авторизацию."""
    with user.client.websocket_connect(f"/ws/boards/{board_id}") as ws:
        ws.send_json({"type": "auth", "token": user.token, "last_event_id": last_event_id})
        ready = receive(ws)
        assert ready["type"] == "ready", ready
        ws.ready = ready
        yield ws
