"""Фоновые задачи: превью картинок и выгрузка доски в CSV."""
import asyncio
import csv
import io
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs.worker import PermanentJobError, handler
from app.models import (
    Attachment,
    AttachmentBlob,
    Board,
    BoardColumn,
    Card,
    Comment,
    Export,
    ExportStatus,
    ThumbnailStatus,
    User,
    utcnow,
)
from app.realtime.events import publish
from app.schemas import ExportOut
from app.services.files import safe_filename
from app.services.views import attachment_out, card_out, dump

THUMBNAIL_SIZE = (480, 480)
Image.MAX_IMAGE_PIXELS = 40_000_000  # «бомба» 50000×50000 пикселей не съест память сервера


def make_thumbnail(data: bytes) -> bytes:
    """Уменьшенная копия в WEBP. Поворот по EXIF — фото с телефона не лягут на бок."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(THUMBNAIL_SIZE)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            out = io.BytesIO()
            image.save(out, format="WEBP", quality=80)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise PermanentJobError(f"Не удалось сделать превью: {exc}") from exc


async def _thumbnail_failed(session: AsyncSession, payload: dict[str, Any], _: str) -> None:
    attachment = await session.get(Attachment, payload["attachment_id"])
    if attachment is None:
        return
    attachment.thumbnail = ThumbnailStatus.failed
    card = await session.get(Card, attachment.card_id)
    await publish(session, card.board_id, "attachment.updated", dump(attachment_out(attachment)))


@handler("thumbnail", on_failure=_thumbnail_failed)
async def thumbnail(session: AsyncSession, payload: dict[str, Any]) -> None:
    attachment = await session.get(Attachment, payload["attachment_id"], with_for_update=True)
    if attachment is None:
        return  # вложение удалили, пока задача ждала очереди, — делать нечего
    stored = await session.get(AttachmentBlob, attachment.id)
    # Pillow работает с процессором — в отдельном потоке, чтобы не останавливать ответы API
    stored.thumbnail = await asyncio.to_thread(make_thumbnail, stored.data)
    attachment.thumbnail = ThumbnailStatus.ready
    card = await session.get(Card, attachment.card_id)
    await session.flush()
    await publish(session, card.board_id, "attachment.updated", dump(attachment_out(attachment)))
    # Обложка карточки могла появиться — карточку тоже обновим у всех
    await publish(session, card.board_id, "card.updated", dump(await card_out(session, card.id)))


# ---------- Выгрузка доски ----------

CSV_HEADER = ["Колонка", "Карточка", "Описание", "Исполнитель", "Срок", "Комментариев", "Файлов", "Изменена"]


async def board_csv(session: AsyncSession, board_id: int) -> bytes:
    comments = select(func.count()).where(Comment.card_id == Card.id).correlate(Card).scalar_subquery()
    files = select(func.count()).where(Attachment.card_id == Card.id).correlate(Card).scalar_subquery()
    rows = await session.execute(
        select(BoardColumn.title, Card, User.name, comments, files)
        .join(Card, Card.column_id == BoardColumn.id)
        .outerjoin(User, User.id == Card.assignee_id)
        .where(BoardColumn.board_id == board_id)
        .order_by(BoardColumn.position, BoardColumn.id, Card.position, Card.id))
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")  # «;» — Excel с русской локалью откроет без мастера импорта
    writer.writerow(CSV_HEADER)
    for column, card, assignee, n_comments, n_files in rows:
        writer.writerow([column, _cell(card.title), _cell(card.description), assignee or "",
                         card.due_date.strftime("%d.%m.%Y") if card.due_date else "", n_comments, n_files,
                         card.updated_at.astimezone(ZoneInfo(settings.timezone)).strftime("%d.%m.%Y %H:%M")])
    return ("﻿" + out.getvalue()).encode("utf-8")  # BOM: Excel поймёт, что это UTF-8


def _cell(value: str) -> str:
    """Защита от CSV-инъекции: ячейка «=HYPERLINK(…)» в Excel стала бы формулой."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


async def _export_failed(session: AsyncSession, payload: dict[str, Any], _: str) -> None:
    export = await session.get(Export, payload["export_id"])
    if export is None:
        return
    export.status = ExportStatus.failed
    export.finished_at = utcnow()
    await publish(session, export.board_id, "export.updated", dump(ExportOut.model_validate(export)))


@handler("export", on_failure=_export_failed)
async def export(session: AsyncSession, payload: dict[str, Any]) -> None:
    item = await session.get(Export, payload["export_id"], with_for_update=True)
    if item is None:
        return
    board = await session.get(Board, item.board_id)
    item.data = await board_csv(session, item.board_id)
    item.filename = safe_filename(f"{board.title[:60]} — {utcnow():%Y-%m-%d}.csv")
    item.status = ExportStatus.ready
    item.finished_at = utcnow()
    await session.flush()
    await publish(session, item.board_id, "export.updated", dump(ExportOut.model_validate(item)))
