from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, not_found
from app.models import Board, BoardColumn, BoardMember, Card, Event, Role, User
from app.positions import keys_after
from app.realtime.events import publish
from app.schemas import BoardOut, BoardSummary, ColumnOut, MemberOut
from app.services.access import board_for, membership, require_owner
from app.services.views import cards_out, dump

DEFAULT_COLUMNS = ("Нужно сделать", "В работе", "Готово")
MAX_MEMBERS = 50


async def create_board(session: AsyncSession, user: User, title: str) -> Board:
    board = Board(title=title, created_by=user.id)
    session.add(board)
    await session.flush()
    session.add(BoardMember(board_id=board.id, user_id=user.id, role=Role.owner))
    for name, position in zip(DEFAULT_COLUMNS, keys_after(None, len(DEFAULT_COLUMNS)), strict=True):
        session.add(BoardColumn(board_id=board.id, title=name, position=position))
    await session.commit()
    return board


async def list_boards(session: AsyncSession, user: User) -> list[BoardSummary]:
    members = (select(func.count()).where(BoardMember.board_id == Board.id)
               .correlate(Board).scalar_subquery())
    cards = select(func.count()).where(Card.board_id == Board.id).correlate(Board).scalar_subquery()
    rows = await session.execute(
        select(Board, BoardMember.role, members, cards)
        .join(BoardMember, BoardMember.board_id == Board.id)
        .where(BoardMember.user_id == user.id)
        .order_by(Board.created_at.desc(), Board.id.desc()))
    return [BoardSummary(id=b.id, title=b.title, role=role, members=m, cards=c) for b, role, m, c in rows]


async def board_snapshot(session: AsyncSession, board_id: int, user: User) -> BoardOut:
    """Доска целиком. last_event_id берётся до чтения данных: всё, что изменится после,
    клиент получит по WebSocket, начиная с этого номера, — без дыры между загрузкой и подпиской."""
    me = await membership(session, board_id, user)
    last_event_id = await session.scalar(
        select(func.coalesce(func.max(Event.id), 0)).where(Event.board_id == board_id))
    board = await session.get(Board, board_id)
    members = (await session.scalars(
        select(BoardMember).where(BoardMember.board_id == board_id)
        .order_by(BoardMember.joined_at, BoardMember.user_id))).all()
    columns = (await session.scalars(
        select(BoardColumn).where(BoardColumn.board_id == board_id)
        .order_by(BoardColumn.position, BoardColumn.id))).all()
    return BoardOut(id=board.id, title=board.title, role=me.role,
                    members=[MemberOut.model_validate(m) for m in members],
                    columns=[ColumnOut.model_validate(c) for c in columns],
                    cards=await cards_out(session, Card.board_id == board_id),
                    last_event_id=last_event_id or 0)


async def rename_board(session: AsyncSession, board_id: int, user: User, title: str,
                       client_id: str | None) -> Board:
    await require_owner(session, board_id, user)
    board = await board_for(session, board_id, user, lock=True)
    old, board.title = board.title, title
    await publish(session, board_id, "board.updated", {"title": title}, actor=user, client_id=client_id,
                  activity=("board.renamed", f"Доска переименована: «{old}» → «{title}»"))
    await session.commit()
    return board


async def delete_board(session: AsyncSession, board_id: int, user: User, client_id: str | None) -> None:
    await require_owner(session, board_id, user)
    await session.execute(delete(Board).where(Board.id == board_id))
    # Событие без FK на доску: его получат все, кто сейчас на доске, и их отключит
    await publish(session, board_id, "board.deleted", {}, actor=user, client_id=client_id)
    await session.commit()


async def add_member(session: AsyncSession, board_id: int, user: User, email: str,
                     client_id: str | None) -> BoardMember:
    await require_owner(session, board_id, user)
    await board_for(session, board_id, user, lock=True)  # участников добавляют по очереди — лимит не обойти
    invited = await session.scalar(select(User).where(User.email == email))
    if invited is None:
        raise AppError(404, "user_not_found",
                       "Пользователь с таким email не зарегистрирован — попросите его сначала создать аккаунт")
    count = await session.scalar(select(func.count()).where(BoardMember.board_id == board_id))
    if count >= MAX_MEMBERS:
        raise AppError(409, "members_limit", f"На доске уже {MAX_MEMBERS} участников — это максимум")
    member = BoardMember(board_id=board_id, user_id=invited.id, role=Role.member)
    session.add(member)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise AppError(409, "already_member", "Этот человек уже участник доски") from None
    await session.refresh(member, ["user"])
    await publish(session, board_id, "member.added", dump(MemberOut.model_validate(member)), actor=user,
                  client_id=client_id, activity=("member.added", f"Новый участник: {invited.name}"))
    await session.commit()
    return member


async def remove_member(session: AsyncSession, board_id: int, user: User, member_id: int,
                        client_id: str | None) -> None:
    """Владелец удаляет участника, или участник уходит сам."""
    me = await membership(session, board_id, user)
    if member_id != user.id and me.role != Role.owner:
        raise AppError(403, "owner_only", "Удалять участников может только владелец доски")
    target = await session.scalar(select(BoardMember).where(
        BoardMember.board_id == board_id, BoardMember.user_id == member_id).with_for_update(of=BoardMember))
    if target is None:
        raise not_found("Участник")
    if target.role == Role.owner:
        raise AppError(409, "owner_cannot_leave", "Владелец не может покинуть доску — её можно только удалить")
    name = target.user.name
    await session.delete(target)
    # Карточки ушедшего остаются на доске, но без исполнителя
    unassigned = (await session.scalars(
        update(Card).where(Card.board_id == board_id, Card.assignee_id == member_id)
        .values(assignee_id=None, version=Card.version + 1).returning(Card.id))).all()
    message = f"{name} покидает доску" if member_id == user.id else f"{name} больше не участник доски"
    await publish(session, board_id, "member.removed", {"user_id": member_id, "unassigned": list(unassigned)},
                  actor=user, client_id=client_id, activity=("member.removed", message))
    await session.commit()
