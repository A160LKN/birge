"""Права доступа к доскам.

Чужая доска для постороннего — 404, а не 403: так по номерам нельзя узнать, какие доски существуют.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, not_found
from app.models import Board, BoardColumn, BoardMember, Card, Role, User


async def membership(session: AsyncSession, board_id: int, user: User) -> BoardMember:
    member = await session.scalar(
        select(BoardMember).where(BoardMember.board_id == board_id, BoardMember.user_id == user.id))
    if member is None:
        raise not_found("Доска")
    return member


async def require_owner(session: AsyncSession, board_id: int, user: User) -> BoardMember:
    member = await membership(session, board_id, user)
    if member.role != Role.owner:
        raise AppError(403, "owner_only", "Это может сделать только владелец доски")
    return member


async def board_for(session: AsyncSession, board_id: int, user: User, *, lock: bool = False) -> Board:
    await membership(session, board_id, user)
    query = select(Board).where(Board.id == board_id)
    board = await session.scalar(query.with_for_update() if lock else query)
    if board is None:  # pragma: no cover — участник без доски невозможен из-за каскадного удаления
        raise not_found("Доска")
    return board


async def card_for(session: AsyncSession, card_id: int, user: User, *, lock: bool = False) -> Card:
    query = select(Card).where(Card.id == card_id)
    card = await session.scalar(query.with_for_update() if lock else query)
    if card is None:
        raise not_found("Карточка")
    try:
        await membership(session, card.board_id, user)
    except AppError:
        raise not_found("Карточка") from None
    return card


async def column_for(session: AsyncSession, column_id: int, user: User, *, lock: bool = False,
                     shared: bool = False) -> BoardColumn:
    query = select(BoardColumn).where(BoardColumn.id == column_id)
    if lock:
        query = query.with_for_update()
    elif shared:
        # FOR SHARE: колонку не удалят, пока в неё кладут карточку
        query = query.with_for_update(read=True)
    column = await session.scalar(query)
    if column is None:
        raise not_found("Колонка")
    try:
        await membership(session, column.board_id, user)
    except AppError:
        raise not_found("Колонка") from None
    return column
