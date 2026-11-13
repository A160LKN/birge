from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import AppError
from app.jobs.queue import enqueue
from app.models import Activity, Export, ExportStatus, User
from app.routers.deps import ClientId, PathId
from app.schemas import (
    ActivityOut,
    BoardIn,
    BoardOut,
    BoardSummary,
    ColumnIn,
    ColumnOut,
    ExportOut,
    MemberIn,
    MemberOut,
    MoveColumnIn,
)
from app.security import current_user
from app.services import boards, cards
from app.services.access import membership
from app.services.files import content_disposition

router = APIRouter(tags=["Доски"])


@router.get("/boards", response_model=list[BoardSummary])
async def list_boards(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await boards.list_boards(session, user)


@router.post("/boards", response_model=BoardOut, status_code=status.HTTP_201_CREATED)
async def create_board(data: BoardIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    board = await boards.create_board(session, user, data.title)
    return await boards.board_snapshot(session, board.id, user)


@router.get("/boards/{board_id}", response_model=BoardOut)
async def get_board(board_id: PathId, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    return await boards.board_snapshot(session, board_id, user)


@router.patch("/boards/{board_id}", response_model=BoardSummary)
async def rename_board(board_id: PathId, data: BoardIn, client_id: ClientId = None,
                       user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await boards.rename_board(session, board_id, user, data.title, client_id)
    return next(b for b in await boards.list_boards(session, user) if b.id == board_id)


@router.delete("/boards/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board(board_id: PathId, client_id: ClientId = None, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    await boards.delete_board(session, board_id, user, client_id)


# ---------- Участники ----------

@router.post("/boards/{board_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED,
             tags=["Участники"])
async def add_member(board_id: PathId, data: MemberIn, client_id: ClientId = None,
                     user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await boards.add_member(session, board_id, user, data.email, client_id)


@router.delete("/boards/{board_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Участники"])
async def remove_member(board_id: PathId, user_id: PathId, client_id: ClientId = None,
                        user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await boards.remove_member(session, board_id, user, user_id, client_id)


# ---------- Колонки ----------

@router.post("/boards/{board_id}/columns", response_model=ColumnOut, status_code=status.HTTP_201_CREATED,
             tags=["Колонки"])
async def create_column(board_id: PathId, data: ColumnIn, client_id: ClientId = None,
                        user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await cards.create_column(session, board_id, user, data.title, client_id)


@router.patch("/columns/{column_id}", response_model=ColumnOut, tags=["Колонки"])
async def rename_column(column_id: PathId, data: ColumnIn, client_id: ClientId = None,
                        user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await cards.rename_column(session, column_id, user, data.title, client_id)


@router.post("/columns/{column_id}/move", response_model=ColumnOut, tags=["Колонки"])
async def move_column(column_id: PathId, data: MoveColumnIn, client_id: ClientId = None,
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await cards.move_column(session, column_id, user, data.after_id, client_id)


@router.delete("/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Колонки"])
async def delete_column(column_id: PathId, client_id: ClientId = None, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    await cards.delete_column(session, column_id, user, client_id)


# ---------- Лента действий ----------

@router.get("/boards/{board_id}/activity", response_model=list[ActivityOut], tags=["Лента действий"])
async def activity(board_id: PathId, before: int | None = Query(None, ge=1, description="Для подгрузки: id < before"),
                   limit: int = Query(30, ge=1, le=100), user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    await membership(session, board_id, user)
    query = select(Activity, User).outerjoin(User, User.id == Activity.actor_id).where(Activity.board_id == board_id)
    if before is not None:
        query = query.where(Activity.id < before)
    rows = await session.execute(query.order_by(Activity.id.desc()).limit(limit))
    return [ActivityOut(id=a.id, actor=u, kind=a.kind, message=a.message, created_at=a.created_at) for a, u in rows]


# ---------- Выгрузка ----------

@router.post("/boards/{board_id}/exports", response_model=ExportOut, status_code=status.HTTP_202_ACCEPTED,
             tags=["Выгрузка"])
async def request_export(board_id: PathId, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    """Выгрузка готовится в фоне: ответ сразу, а о готовности придёт событие export.updated."""
    await membership(session, board_id, user)
    item = Export(board_id=board_id, requested_by=user.id, status=ExportStatus.pending)
    session.add(item)
    await session.flush()
    await enqueue(session, "export", {"export_id": item.id})
    await session.commit()
    return item


async def _export_for(session: AsyncSession, export_id: int, user: User) -> Export:
    item = await session.get(Export, export_id)
    if item is None or item.requested_by != user.id:
        raise AppError(404, "not_found", "Выгрузка не найдена")
    await membership(session, item.board_id, user)
    return item


@router.get("/exports/{export_id}", response_model=ExportOut, tags=["Выгрузка"])
async def get_export(export_id: PathId, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    return await _export_for(session, export_id, user)


@router.get("/exports/{export_id}/download", tags=["Выгрузка"], response_class=Response)
async def download_export(export_id: PathId, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    item = await _export_for(session, export_id, user)
    if item.status != ExportStatus.ready:
        raise AppError(409, "export_not_ready", "Выгрузка ещё не готова")
    await session.refresh(item, ["data"])
    return Response(item.data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": content_disposition(item.filename, inline=False),
                             "X-Content-Type-Options": "nosniff"})
