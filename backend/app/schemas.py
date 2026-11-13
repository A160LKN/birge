import re
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import ExportStatus, Role, ThumbnailStatus

MAX_ID = 2_147_483_647
Id = Annotated[int, Field(ge=1, le=MAX_ID)]
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _not_blank(value: str) -> str:
    if not value:
        raise ValueError("Не может быть пустым")
    return value


def Text(max_length: int, *, blank: bool = False):  # noqa: N802 — фабрика типа, читается как тип
    base = Annotated[str, StringConstraints(strip_whitespace=True, max_length=max_length)]
    return base if blank else Annotated[base, AfterValidator(_not_blank)]


class Strict(BaseModel):
    """Лишние поля во входных данных — ошибка, а не тихое игнорирование опечатки."""

    model_config = ConfigDict(extra="forbid")


class Out(BaseModel):
    # Поля со значением по умолчанию в ответе есть всегда — в схеме для фронтенда они обязательные
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


# ---------- Пользователи ----------

def _email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not _EMAIL.match(value):
        raise ValueError("Неверный формат email")
    return value


Email = Annotated[str, AfterValidator(_email)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class RegisterIn(Strict):
    email: Email
    name: Text(60)
    password: Password


class LoginIn(Strict):
    email: Email
    password: Annotated[str, StringConstraints(max_length=128)]


class UserOut(Out):
    id: int
    email: str
    name: str


class TokenOut(Out):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — тип токена, а не пароль
    user: UserOut


# ---------- Доски ----------

class BoardIn(Strict):
    title: Text(80)


class BoardSummary(Out):
    id: int
    title: str
    role: Role
    members: int
    cards: int


class MemberIn(Strict):
    email: Email


class MemberOut(Out):
    user: UserOut
    role: Role


class ColumnIn(Strict):
    title: Text(40)


class ColumnOut(Out):
    id: int
    title: str
    position: str


class MoveColumnIn(Strict):
    after_id: Id | None = Field(None, description="Колонка, после которой встать; null — в начало")


class CardIn(Strict):
    column_id: Id
    title: Text(200)
    description: Text(5000, blank=True) = ""


class CardPatch(Strict):
    """Меняются только переданные поля. version — версия карточки, которую видел человек."""

    version: Annotated[int, Field(ge=1, le=MAX_ID)]
    title: Text(200) | None = None
    description: Text(5000, blank=True) | None = None
    assignee_id: Id | None = None
    due_date: date | None = None

    @field_validator("title", "description")
    @classmethod
    def no_null_for_text(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Не может быть null")
        return value


class MoveCardIn(Strict):
    column_id: Id
    after_id: Id | None = Field(None, description="Карточка, после которой встать; null — наверх колонки")


class CardOut(Out):
    id: int
    column_id: int
    title: str
    description: str
    position: str
    assignee_id: int | None
    due_date: date | None
    version: int
    comments: int = 0
    attachments: int = 0
    cover_url: str | None = Field(None, description="Превью первой картинки-вложения — обложка карточки")
    updated_at: datetime


class BoardOut(Out):
    id: int
    title: str
    role: Role
    members: list[MemberOut]
    columns: list[ColumnOut]
    cards: list[CardOut]
    last_event_id: int = Field(description="С этого события подписываться на WebSocket — ничего не потеряется")


# ---------- Карточка подробно ----------

class CommentIn(Strict):
    body: Text(2000)


class CommentOut(Out):
    id: int
    card_id: int
    author: UserOut | None
    body: str
    created_at: datetime


class AttachmentOut(Out):
    id: int
    card_id: int
    filename: str
    content_type: str
    size: int
    thumbnail: ThumbnailStatus
    uploader_id: int | None
    created_at: datetime
    url: str = Field(description="Подписанная ссылка на файл, действует час")
    thumbnail_url: str | None = None


class CardDetail(CardOut):
    created_at: datetime
    created_by: int | None
    comment_list: list[CommentOut]
    attachment_list: list[AttachmentOut]


class ActivityOut(Out):
    id: int
    actor: UserOut | None
    kind: str
    message: str
    created_at: datetime


class ExportOut(Out):
    id: int
    board_id: int
    status: ExportStatus
    filename: str | None
    created_at: datetime
    finished_at: datetime | None
