from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.db import get_session
from app.errors import AppError
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.security import create_token, current_user, hash_password, hash_password_async, verify_password_async

router = APIRouter(prefix="/auth", tags=["Вход"])
_DUMMY_HASH = hash_password("timing-equaliser")


# Самые частые пароли из утечек: их подбирают первыми
COMMON_PASSWORDS = {"12345678", "123456789", "1234567890", "password", "password1", "qwerty123", "qwertyuiop",
                    "11111111", "00000000", "iloveyou", "12341234", "87654321", "qwerty12", "1q2w3e4r", "abc12345"}


def check_password_strength(password: str, email: str) -> None:
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) < 4 or lowered in (email, email.split("@")[0]):
        raise AppError(422, "weak_password", "Слишком простой пароль: возьмите длиннее и не из популярных")


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, request: Request, session: AsyncSession = Depends(get_session)):
    ip = ratelimit.client_ip(request)
    ratelimit.registrations.check(ip)
    check_password_strength(data.password, data.email)
    ratelimit.registrations.hit(ip)
    user = User(email=data.email, name=data.name, password_hash=await hash_password_async(data.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:  # уникальность проверяет БД — без гонки «проверил, потом вставил»
        await session.rollback()
        raise AppError(409, "email_taken", "Пользователь с таким email уже зарегистрирован") from None
    return TokenOut(access_token=create_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, request: Request, session: AsyncSession = Depends(get_session)):
    key = f"{data.email}|{ratelimit.client_ip(request)}"
    ratelimit.failed_logins.check(key)  # защита от подбора пароля
    ratelimit.failed_logins_per_email.check(data.email)
    user = await session.scalar(select(User).where(User.email == data.email))
    # Пароль проверяется и для несуществующего email: по времени ответа не узнать, кто зарегистрирован
    valid = await verify_password_async(data.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid:
        ratelimit.failed_logins.hit(key)
        ratelimit.failed_logins_per_email.hit(data.email)
        raise AppError(401, "invalid_credentials", "Неверный email или пароль")
    ratelimit.failed_logins.reset(key)
    return TokenOut(access_token=create_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user
