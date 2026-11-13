from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as PoolTimeout


class AppError(Exception):
    """Ошибка бизнес-логики: код для программ, текст — для человека, details — данные для интерфейса."""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    error: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details is not None:
        error["details"] = exc.details
    return JSONResponse(status_code=exc.status, content={"error": error})


async def overload_handler(_: Request, __: PoolTimeout) -> JSONResponse:
    return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                        content={"error": {"code": "overloaded",
                                           "message": "Сервис перегружен — повторите запрос через несколько секунд"}})


def not_found(what: str) -> AppError:
    return AppError(404, "not_found", f"{what} не найдена" if what.endswith("а") else f"{what} не найден")
