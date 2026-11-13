import enum
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Ключи позиций сравниваются побайтно — см. app/positions.py
Position = String(255, collation="C")


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda members: [m.value for m in members])


class Role(enum.StrEnum):
    owner = "owner"
    member = "member"


class ThumbnailStatus(enum.StrEnum):
    none = "none"        # не картинка — превью не бывает
    pending = "pending"  # задача на превью в очереди
    ready = "ready"
    failed = "failed"


class ExportStatus(enum.StrEnum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _now() -> Mapped[datetime]:
    # Значение ставит и Python (оно сразу доступно после flush, без лишнего запроса), и БД — для вставок в обход ORM
    return mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _now()


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()


class BoardMember(Base):
    __tablename__ = "board_members"

    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "board_role"))
    joined_at: Mapped[datetime] = _now()

    user: Mapped[User] = relationship(lazy="joined", innerjoin=True)


class BoardColumn(Base):
    __tablename__ = "columns"
    __table_args__ = (Index("ix_columns_board_position", "board_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(40))
    position: Mapped[str] = mapped_column(Position)


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        Index("ix_cards_column_position", "column_id", "position"),
        Index("ix_cards_board", "board_id"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    column_id: Mapped[int] = mapped_column(ForeignKey("columns.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[str] = mapped_column(Position)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date)
    # Оптимистическая блокировка: правка приходит с версией, которую видел человек.
    # Если карточку уже изменили — 409, а не молчаливая перезапись чужой правки
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_card", "card_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_card", "card_id"),
        CheckConstraint("size > 0", name="size_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    thumbnail: Mapped[ThumbnailStatus] = mapped_column(_enum(ThumbnailStatus, "thumbnail_status"))
    created_at: Mapped[datetime] = _now()


class AttachmentBlob(Base):
    """Содержимое файла — отдельно от описания: список вложений не тянет мегабайты из базы."""

    __tablename__ = "attachment_blobs"

    attachment_id: Mapped[int] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    thumbnail: Mapped[bytes | None] = mapped_column(LargeBinary)


class Activity(Base):
    __tablename__ = "activity"
    __table_args__ = (Index("ix_activity_board_id", "board_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = _now()


class Event(Base):
    """Журнал событий доски для WebSocket.

    Событие пишется в той же транзакции, что и изменение, а pg_notify срабатывает только после
    коммита — клиенты не узнают об изменении, которое потом откатилось, и не пропустят то,
    что сохранилось. По журналу клиент после обрыва связи догоняет пропущенное.
    """

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_board_id", "board_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_id: Mapped[int] = mapped_column(Integer)  # без FK: событие «доска удалена» переживает доску
    type: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[int | None] = mapped_column(Integer)
    client_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[ExportStatus] = mapped_column(_enum(ExportStatus, "export_status"))
    filename: Mapped[str | None] = mapped_column(String(255))
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    """Очередь фоновых задач прямо в PostgreSQL: SELECT … FOR UPDATE SKIP LOCKED
    раздаёт задачи обработчикам так, что одну задачу не возьмут двое."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_ready", "run_at", postgresql_where="status = 'queued'"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus, "job_status"), default=JobStatus.queued)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_at: Mapped[datetime] = _now()
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
