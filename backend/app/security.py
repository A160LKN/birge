"""Пароли и JWT-токены."""
import asyncio
import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.errors import AppError
from app.models import User

# scrypt из стандартной библиотеки: медленный по задумке, с солью — подбор пароля дорогой
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
MAX_ID = 2_147_483_647


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


# scrypt занимает процессор на десятки миллисекунд. Вызванный прямо в async-обработчике, он
# останавливает весь цикл событий: ответы API и рассылку WebSocket всех досок. Поток входов
# с разными email превратился бы в отказ в обслуживании. Поэтому в async-коде — только эти обёртки.

async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, stored: str) -> bool:
    return await asyncio.to_thread(verify_password, password, stored)


def create_token(user_id: int, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=settings.jwt_ttl_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def user_id_from_token(token: str) -> int:
    """id пользователя из токена или AppError 401. Общая проверка для HTTP и WebSocket."""
    try:
        # algorithms задан явно: токен с alg=none или другим алгоритмом не пройдёт
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "Срок действия входа истёк — войдите заново") from None
    except jwt.PyJWTError:
        raise AppError(401, "invalid_token", "Неверный токен") from None
    sub = payload.get("sub")
    if not (isinstance(sub, str) and sub.isdigit() and 0 < int(sub) <= MAX_ID):
        raise AppError(401, "invalid_token", "Неверный токен")
    return int(sub)


async def load_user(session: AsyncSession, token: str) -> User:
    user = await session.get(User, user_id_from_token(token))
    if user is None:  # пользователь удалён, а токен ещё жив
        raise AppError(401, "invalid_token", "Неверный токен")
    return user


_bearer = HTTPBearer(auto_error=False)


async def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
                       session: AsyncSession = Depends(get_session)) -> User:
    if credentials is None:
        raise AppError(401, "unauthorized", "Нужна авторизация: передайте токен в заголовке Authorization: Bearer")
    return await load_user(session, credentials.credentials)


# ---------- Подписанные ссылки на файлы ----------
# Браузер грузит картинку тегом <img> и не может добавить заголовок Authorization.
# Поэтому API выдаёт ссылку с подписью и сроком действия: подделать или продлить её нельзя.

LINK_TTL_SECONDS = 3600


def _signature(path: str, expires: int) -> str:
    digest = hmac.new(settings.jwt_secret.encode(), f"{path}|{expires}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode()


def signed_url(path: str, now: datetime | None = None) -> str:
    expires = int((now or datetime.now(UTC)).timestamp()) + LINK_TTL_SECONDS
    return f"{path}?expires={expires}&sig={_signature(path, expires)}"


def verify_signature(path: str, expires: int, sig: str, now: datetime | None = None) -> bool:
    if expires < (now or datetime.now(UTC)).timestamp():
        return False
    return hmac.compare_digest(_signature(path, expires), sig)
