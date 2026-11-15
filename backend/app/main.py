import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal, engine, get_session
from app.errors import AppError, PoolTimeout, app_error_handler, overload_handler
from app.jobs.worker import worker_loop
from app.middleware import HttpMiddleware
from app.realtime import ws
from app.realtime.hub import Hub
from app.routers import auth, boards, cards

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    hub = Hub(SessionLocal)
    app.state.hub = hub
    await hub.start()
    stop = asyncio.Event()
    worker = asyncio.create_task(worker_loop(SessionLocal, stop)) if settings.worker_enabled else None
    try:
        yield
    finally:
        stop.set()
        if worker is not None:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        await hub.stop()
        await engine.dispose()


app = FastAPI(
    title="Бірге API",
    version="1.0.0",
    description="Доска задач для команды: карточки в реальном времени, вложения, фоновые задачи.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["Authorization", "Content-Type", "X-Client-Id"],
                   expose_headers=["Content-Disposition", "X-Request-ID", "Retry-After"])
app.add_middleware(HttpMiddleware)  # заголовки безопасности, ID запроса, журнал, лимит размера тела
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(PoolTimeout, overload_handler)
app.include_router(auth.router)
app.include_router(boards.router)
app.include_router(cards.router)
app.include_router(ws.router)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/health", tags=["Служебное"])
async def health(session: AsyncSession = Depends(get_session)):
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
