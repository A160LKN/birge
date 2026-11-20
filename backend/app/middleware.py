"""Заголовки безопасности, ID запроса, журнал запросов, лимит размера тела, единый ответ на 500."""
import json
import logging
import secrets
import time

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings

log = logging.getLogger("birge.http")
# Самый большой законный запрос — загрузка вложения (до max_upload_bytes) плюс поля формы
MAX_BODY = settings.max_upload_bytes + 64 * 1024

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
# API отдаёт только JSON: ему не нужны ни скрипты, ни стили. Страница /docs грузит Swagger UI с CDN.
API_CSP = "default-src 'none'; frame-ancestors 'none'"
DOCS_CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "connect-src 'self'; frame-ancestors 'none'")


TOO_LARGE = {"error": {"code": "payload_too_large", "message": "Слишком большой запрос"}}


class BodyTooLarge(HTTPException):
    """Наследник HTTPException: FastAPI пропускает его как есть, а не превращает в 400 «ошибка разбора тела»."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail="payload_too_large")


async def body_too_large_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(TOO_LARGE, status_code=413)


class BodyLimitMiddleware:
    """Лимит размера тела для запросов без Content-Length.

    Заголовок Content-Length проверяет HttpMiddleware ещё до чтения тела. Но клиент может прислать тело
    кусками (Transfer-Encoding: chunked) без этого заголовка — тогда разбор формы записал бы на диск
    файл любого размера, и read_limited отклонил бы его, только когда место уже занято. Здесь байты
    считаются по мере чтения, и запрос обрывается, как только лимит превышен.
    """

    def __init__(self, app: ASGIApp, limit: int | None = None) -> None:
        self.app, self.limit = app, limit or MAX_BODY

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise BodyTooLarge()
            return message

        await self.app(scope, limited, send)


class HttpMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        # Чужой ID принимаем, только если он короткий и безопасный — он попадает в журнал
        safe = 0 < len(incoming) <= 64 and incoming.replace("-", "").isascii() and incoming.replace("-", "").isalnum()
        request_id = incoming if safe else secrets.token_hex(8)
        request.state.request_id = request_id
        started = time.perf_counter()

        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY:
            response: Response = JSONResponse(TOO_LARGE, status_code=413)
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Подробности — только в журнал; клиент получает код и ID, по которому ошибку можно найти
                log.exception("unhandled error", extra={"request_id": request_id})
                response = JSONResponse({"error": {"code": "internal_error", "message": "Внутренняя ошибка сервера",
                                                   "request_id": request_id}}, status_code=500)

        response.headers["X-Request-ID"] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        docs = request.url.path in ("/docs", "/redoc") or request.url.path.startswith("/docs/")
        response.headers.setdefault("Content-Security-Policy", DOCS_CSP if docs else API_CSP)
        if request.url.path != "/health":  # проверки здоровья раз в несколько секунд засоряли бы журнал
            log.info(json.dumps({
                "request_id": request_id, "method": request.method, "path": request.url.path,
                "status": response.status_code, "ms": round((time.perf_counter() - started) * 1000, 1),
            }))
        return response
