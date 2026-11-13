"""Колонки, карточки и комментарии."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, not_found
from app.models import BoardColumn, BoardMember, Card, Comment, User, utcnow
from app.positions import key_between
from app.realtime.events import publish
from app.schemas import CardIn, CardOut, CardPatch, ColumnOut, CommentOut, MoveCardIn
from app.services.access import board_for, card_for, column_for
from app.services.views import card_out, dump

MAX_COLUMNS = 12
MAX_CARDS_PER_BOARD = 1000


def _quote(text: str, limit: int = 60) -> str:
    return f"«{text if len(text) <= limit else text[:limit - 1] + '…'}»"


# ---------- Колонки ----------

async def _column_after(session: AsyncSession, board_id: int, after_id: int | None,
                        exclude: int | None = None) -> tuple[str | None, str | None]:
    """Ключи соседей для новой позиции: (после кого, перед кем)."""
    query = select(BoardColumn.id, BoardColumn.position).where(BoardColumn.board_id == board_id)
    if exclude is not None:
        query = query.where(BoardColumn.id != exclude)
    columns = (await session.execute(query.order_by(BoardColumn.position, BoardColumn.id))).all()
    return _neighbours(columns, after_id, "Колонка")


def _neighbours(rows, after_id: int | None, what: str) -> tuple[str | None, str | None]:
    if after_id is None:
        return None, rows[0].position if rows else None
    for i, row in enumerate(rows):
        if row.id == after_id:
            following = rows[i + 1].position if i + 1 < len(rows) else None
            # Два элемента с одинаковым ключом (одновременная вставка в одно место) — встаём после обоих
            while following is not None and following == row.position:
                i += 1
                following = rows[i + 1].position if i + 1 < len(rows) else None
            return row.position, following
    raise AppError(422, "invalid_position", f"{what}, после которой нужно встать, не найдена в этом списке")


async def create_column(session: AsyncSession, board_id: int, user: User, title: str,
                        client_id: str | None) -> BoardColumn:
    await board_for(session, board_id, user, lock=True)  # колонки добавляют по очереди — лимит не обойти
    count = await session.scalar(select(func.count()).where(BoardColumn.board_id == board_id))
    if count >= MAX_COLUMNS:
        raise AppError(409, "columns_limit", f"На доске уже {MAX_COLUMNS} колонок — это максимум")
    last = await session.scalar(select(func.max(BoardColumn.position)).where(BoardColumn.board_id == board_id))
    column = BoardColumn(board_id=board_id, title=title, position=key_between(last, None))
    session.add(column)
    await session.flush()
    await publish(session, board_id, "column.created", dump(ColumnOut.model_validate(column)), actor=user,
                  client_id=client_id, activity=("column.created", f"Новая колонка {_quote(title)}"))
    await session.commit()
    return column


async def rename_column(session: AsyncSession, column_id: int, user: User, title: str,
                        client_id: str | None) -> BoardColumn:
    column = await column_for(session, column_id, user, lock=True)
    old, column.title = column.title, title
    await publish(session, column.board_id, "column.updated", dump(ColumnOut.model_validate(column)),
                  actor=user, client_id=client_id,
                  activity=("column.renamed", f"Колонка {_quote(old)} теперь называется {_quote(title)}"))
    await session.commit()
    return column


async def move_column(session: AsyncSession, column_id: int, user: User, after_id: int | None,
                      client_id: str | None) -> BoardColumn:
    column = await column_for(session, column_id, user, lock=True)
    if after_id == column_id:
        raise AppError(422, "invalid_position", "Колонку нельзя поставить после самой себя")
    before, after = await _column_after(session, column.board_id, after_id, exclude=column_id)
    column.position = key_between(before, after)
    await publish(session, column.board_id, "column.updated", dump(ColumnOut.model_validate(column)),
                  actor=user, client_id=client_id)
    await session.commit()
    return column


async def delete_column(session: AsyncSession, column_id: int, user: User, client_id: str | None) -> None:
    column = await column_for(session, column_id, user, lock=True)
    count = await session.scalar(select(func.count()).where(BoardColumn.board_id == column.board_id))
    if count <= 1:
        raise AppError(409, "last_column", "Это последняя колонка — на доске должна остаться хотя бы одна")
    cards = await session.scalar(select(func.count()).where(Card.column_id == column_id))
    await session.delete(column)  # карточки удалятся каскадом
    note = f" вместе с карточками: {cards}" if cards else ""
    await publish(session, column.board_id, "column.deleted", {"id": column_id}, actor=user, client_id=client_id,
                  activity=("column.deleted", f"Колонка {_quote(column.title)} удалена{note}"))
    await session.commit()


# ---------- Карточки ----------

async def _card_slot(session: AsyncSession, column_id: int, after_id: int | None,
                     exclude: int | None = None) -> str:
    query = select(Card.id, Card.position).where(Card.column_id == column_id)
    if exclude is not None:
        query = query.where(Card.id != exclude)
    rows = (await session.execute(query.order_by(Card.position, Card.id))).all()
    return key_between(*_neighbours(rows, after_id, "Карточка"))


async def _check_assignee(session: AsyncSession, board_id: int, assignee_id: int) -> None:
    member = await session.scalar(select(BoardMember).where(
        BoardMember.board_id == board_id, BoardMember.user_id == assignee_id))
    if member is None:
        raise AppError(422, "not_a_member", "Исполнителем можно назначить только участника доски")


async def create_card(session: AsyncSession, user: User, data: CardIn, client_id: str | None) -> CardOut:
    column = await column_for(session, data.column_id, user, shared=True)
    count = await session.scalar(select(func.count()).where(Card.board_id == column.board_id))
    if count >= MAX_CARDS_PER_BOARD:
        raise AppError(409, "cards_limit", f"На доске уже {MAX_CARDS_PER_BOARD} карточек — это максимум")
    # Новая карточка — внизу колонки
    last = await session.scalar(select(func.max(Card.position)).where(Card.column_id == column.id))
    card = Card(board_id=column.board_id, column_id=column.id, title=data.title, description=data.description,
                position=key_between(last, None), created_by=user.id)
    session.add(card)
    await session.flush()
    out = await card_out(session, card.id)
    await publish(session, column.board_id, "card.created", dump(out), actor=user, client_id=client_id,
                  activity=("card.created", f"Новая карточка {_quote(card.title)} в колонке {_quote(column.title)}"))
    await session.commit()
    return out


async def update_card(session: AsyncSession, card_id: int, user: User, patch: CardPatch,
                      client_id: str | None) -> CardOut:
    card = await card_for(session, card_id, user, lock=True)
    if patch.version != card.version:
        current = await card_out(session, card.id)
        await session.rollback()
        raise AppError(409, "version_conflict",
                       "Карточку уже изменил кто-то другой. Посмотрите новую версию и повторите правку",
                       details={"current": dump(current)})
    changes = patch.model_dump(exclude_unset=True, exclude={"version"})
    if not changes:
        raise AppError(422, "nothing_to_update", "Не передано ни одного поля для изменения")
    if changes.get("assignee_id") is not None:
        await _check_assignee(session, card.board_id, changes["assignee_id"])
    for field, value in changes.items():
        setattr(card, field, value)
    card.version += 1
    card.updated_at = utcnow()
    await session.flush()
    out = await card_out(session, card.id)
    activity = None
    if "assignee_id" in changes:
        assignee = await session.get(User, changes["assignee_id"]) if changes["assignee_id"] else None
        activity = ("card.assigned", f"{_quote(card.title)}: исполнитель — {assignee.name}" if assignee
                    else f"{_quote(card.title)}: исполнитель снят")
    await publish(session, card.board_id, "card.updated", dump(out), actor=user, client_id=client_id,
                  activity=activity)
    await session.commit()
    return out


async def move_card(session: AsyncSession, card_id: int, user: User, data: MoveCardIn,
                    client_id: str | None) -> CardOut:
    card = await card_for(session, card_id, user, lock=True)
    if data.after_id == card_id:
        raise AppError(422, "invalid_position", "Карточку нельзя поставить после самой себя")
    target = await column_for(session, data.column_id, user, shared=True)
    if target.board_id != card.board_id:
        raise not_found("Колонка")
    from_column = card.column_id
    card.position = await _card_slot(session, target.id, data.after_id, exclude=card.id)
    card.column_id = target.id
    card.updated_at = utcnow()
    # Перенос не меняет version: он не конфликтует с правкой текста, и человек, редактирующий
    # описание, не должен получать «карточку изменили», если её просто передвинули
    await session.flush()
    out = await card_out(session, card.id)
    activity = None
    if from_column != target.id:
        activity = ("card.moved", f"{_quote(card.title)} → {_quote(target.title)}")
    await publish(session, card.board_id, "card.moved", dump(out), actor=user, client_id=client_id,
                  activity=activity)
    await session.commit()
    return out


async def delete_card(session: AsyncSession, card_id: int, user: User, client_id: str | None) -> None:
    card = await card_for(session, card_id, user, lock=True)
    await session.delete(card)
    await publish(session, card.board_id, "card.deleted", {"id": card_id, "column_id": card.column_id},
                  actor=user, client_id=client_id,
                  activity=("card.deleted", f"Карточка {_quote(card.title)} удалена"))
    await session.commit()


# ---------- Комментарии ----------

async def add_comment(session: AsyncSession, card_id: int, user: User, body: str,
                      client_id: str | None) -> CommentOut:
    card = await card_for(session, card_id, user)
    comment = Comment(card_id=card.id, author_id=user.id, body=body)
    session.add(comment)
    await session.flush()
    out = CommentOut(id=comment.id, card_id=card.id, author=user, body=body, created_at=comment.created_at)
    await publish(session, card.board_id, "comment.created", dump(out), actor=user, client_id=client_id,
                  activity=("comment.created", f"Комментарий к {_quote(card.title)}"))
    await session.commit()
    return out


async def card_comments(session: AsyncSession, card_id: int) -> list[CommentOut]:
    rows = await session.execute(
        select(Comment, User).outerjoin(User, User.id == Comment.author_id)
        .where(Comment.card_id == card_id).order_by(Comment.id))
    return [CommentOut(id=c.id, card_id=c.card_id, author=u, body=c.body, created_at=c.created_at)
            for c, u in rows]

