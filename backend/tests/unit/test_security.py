import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import Settings
from app.errors import AppError
from app.security import (
    LINK_TTL_SECONDS,
    create_token,
    hash_password,
    hash_password_async,
    signed_url,
    user_id_from_token,
    verify_password,
    verify_password_async,
    verify_signature,
)

pytestmark = pytest.mark.unit
SECRET = "test-secret-that-is-long-enough-32b"


def test_password_hash_is_salted_and_verifiable():
    first, second = hash_password("пароль-123"), hash_password("пароль-123")
    assert first != second  # соль: одинаковые пароли — разные хеши
    assert verify_password("пароль-123", first)
    assert not verify_password("пароль-124", first)
    assert not verify_password("пароль-123", "испорченный хеш")


async def test_password_hashing_does_not_block_event_loop(monkeypatch):
    """scrypt идёт в отдельном потоке: пока он считает, цикл событий отвечает остальным."""
    import app.security as security

    loop_thread = threading.get_ident()
    threads = []
    real_scrypt = security.hashlib.scrypt

    def slow_scrypt(*args, **kwargs):
        threads.append(threading.get_ident())
        time.sleep(0.2)  # «тяжёлый» хеш
        return real_scrypt(*args, **kwargs)

    monkeypatch.setattr(security.hashlib, "scrypt", slow_scrypt)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    stored = await hash_password_async("пароль-123")
    assert await verify_password_async("пароль-123", stored)
    task.cancel()
    assert loop_thread not in threads, "scrypt не выполнялся в потоке цикла событий"
    assert ticks >= 10, "пока считался хеш, цикл событий продолжал работать"


def test_token_roundtrip():
    assert user_id_from_token(create_token(42)) == 42


def test_expired_token():
    token = create_token(1, now=datetime.now(UTC) - timedelta(days=2))
    with pytest.raises(AppError) as error:
        user_id_from_token(token)
    assert error.value.code == "token_expired"


@pytest.mark.parametrize("token", [
    jwt.encode({"sub": "1"}, key=None, algorithm="none"),          # без подписи
    jwt.encode({"sub": "1"}, "чужой-секрет-длиной-больше-32-байт", algorithm="HS256"),
    jwt.encode({"sub": "abc"}, SECRET, algorithm="HS256"),
    jwt.encode({"sub": "99999999999"}, SECRET, algorithm="HS256"),  # больше int4 — не уронит запрос в БД
    jwt.encode({}, SECRET, algorithm="HS256"),
    "не-токен",
])
def test_forged_or_broken_tokens_are_rejected(token):
    with pytest.raises(AppError) as error:
        user_id_from_token(token)
    assert error.value.status == 401


def _parts(url: str) -> tuple[str, int, str]:
    path, query = url.split("?")
    params = dict(p.split("=") for p in query.split("&"))
    return path, int(params["expires"]), params["sig"]


def test_signed_url_is_valid_for_its_path_only():
    path, expires, sig = _parts(signed_url("/attachments/5/file"))
    assert verify_signature(path, expires, sig)
    assert not verify_signature("/attachments/6/file", expires, sig)    # подпись от другого файла
    assert not verify_signature(path, expires + 3600, sig)               # продлить срок нельзя
    assert not verify_signature(path, expires, sig[:-2] + "AA")


def test_signed_url_expires():
    issued = datetime.now(UTC) - timedelta(seconds=LINK_TTL_SECONDS + 1)
    path, expires, sig = _parts(signed_url("/attachments/5/file", now=issued))
    assert not verify_signature(path, expires, sig)


@pytest.mark.parametrize(("given", "expected"), [
    ("postgresql://u:p@ep.neon.tech/db?sslmode=require", "postgresql+psycopg://u:p@ep.neon.tech/db?sslmode=require"),
    ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("postgresql+psycopg://u:p@localhost/db", "postgresql+psycopg://u:p@localhost/db"),
])
def test_database_url_from_hosting_uses_psycopg(given, expected):
    assert Settings(database_url=given).database_url == expected


def test_cors_origins_are_split_and_trimmed():
    assert Settings(cors_origins=" https://a.app , https://b.app,").cors_origin_list == ["https://a.app",
                                                                                         "https://b.app"]


@pytest.mark.parametrize(("given", "expected"), [
    # Neon: пул (-pooler) не пропускает LISTEN — для подписки на события подключаемся напрямую
    ("postgresql+psycopg://u:p@ep-fancy-night-b92e5d3k-pooler.c-7.eu-central-1.aws.neon.tech/birge?sslmode=require",
     "postgresql://u:p@ep-fancy-night-b92e5d3k.c-7.eu-central-1.aws.neon.tech/birge?sslmode=require"),
    ("postgresql+psycopg://birge:birge@localhost:5432/birge", "postgresql://birge:birge@localhost:5432/birge"),
])
def test_listen_connection_bypasses_pooler(given, expected):
    from app.db import listen_dsn

    assert listen_dsn(given) == expected


@pytest.mark.parametrize("secret", ["dev-secret-change-me-in-production-32b", "short-but-not-default"])
def test_production_refuses_default_or_short_jwt_secret(secret):
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret=secret)


def test_production_accepts_real_secret_and_dev_keeps_default():
    assert Settings(environment="production", jwt_secret="x" * 40).environment == "production"
    dev = Settings(environment="development", jwt_secret="dev-secret-change-me-in-production-32b")
    assert dev.jwt_secret.startswith("dev-"), "локально и в тестах значение по умолчанию работает"
