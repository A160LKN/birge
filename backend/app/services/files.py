"""Вложения: проверка файла, хранение, выдача.

Тип файла определяется по содержимому (сигнатуре), а не по тому, что прислал браузер:
Content-Type и расширение подделываются за секунду. Расширение должно совпадать с содержимым —
так HTML или SVG со скриптом не выдать за картинку или текст.
"""
import os
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import AppError, not_found
from app.jobs.queue import enqueue
from app.models import Attachment, AttachmentBlob, ThumbnailStatus, User
from app.realtime.events import publish
from app.schemas import AttachmentOut
from app.services.access import card_for
from app.services.views import attachment_out, dump

MAX_ATTACHMENTS_PER_CARD = 20
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@dataclass(frozen=True)
class Kind:
    content_type: str
    extensions: tuple[str, ...]


PNG = Kind("image/png", (".png",))
JPEG = Kind("image/jpeg", (".jpg", ".jpeg"))
GIF = Kind("image/gif", (".gif",))
WEBP = Kind("image/webp", (".webp",))
PDF = Kind("application/pdf", (".pdf",))
TEXT = {".txt": Kind("text/plain", (".txt",)), ".log": Kind("text/plain", (".log",)),
        ".csv": Kind("text/csv", (".csv",)), ".md": Kind("text/markdown", (".md",))}
ALLOWED = "PNG, JPEG, GIF, WEBP, PDF, TXT, CSV, MD"


def sniff(data: bytes, extension: str) -> Kind:
    """Что это за файл на самом деле. Неизвестное или не совпавшее с расширением — 415."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        kind = PNG
    elif data.startswith(b"\xff\xd8\xff"):
        kind = JPEG
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        kind = GIF
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = WEBP
    elif data.startswith(b"%PDF-"):
        kind = PDF
    elif extension in TEXT and _is_text(data):
        kind = TEXT[extension]
    else:
        raise AppError(415, "unsupported_file",
                       f"Такой файл прикрепить нельзя. Можно: {ALLOWED}")
    if extension not in kind.extensions:
        raise AppError(415, "extension_mismatch",
                       f"Расширение файла не совпадает с содержимым: внутри {kind.content_type}")
    return kind


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]+")


def safe_filename(name: str | None) -> str:
    """Имя без пути и управляющих символов: «../../etc/passwd» станет «passwd»."""
    name = unicodedata.normalize("NFC", os.path.basename((name or "").replace("\\", "/")))
    name = _UNSAFE.sub("_", name).strip(" .")
    if len(name) > 120:
        stem, ext = os.path.splitext(name)
        name = stem[:120 - len(ext)] + ext
    return name or "file"


def content_disposition(filename: str, inline: bool) -> str:
    """Имя файла по RFC 6266: латиница для старых клиентов и UTF-8 для кириллицы."""
    fallback = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


async def read_limited(upload: UploadFile) -> bytes:
    """Читаем не больше лимита + 1 байт: огромный файл не займёт память целиком."""
    data = await upload.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        limit = settings.max_upload_bytes // (1024 * 1024)
        raise AppError(413, "file_too_large", f"Файл больше {limit} МБ")
    if not data:
        raise AppError(422, "empty_file", "Файл пустой")
    return data


async def add_attachment(session: AsyncSession, card_id: int, user: User, upload: UploadFile,
                         client_id: str | None) -> AttachmentOut:
    card = await card_for(session, card_id, user, lock=True)  # лимит вложений не обойти параллельными загрузками
    filename = safe_filename(upload.filename)
    data = await read_limited(upload)
    kind = sniff(data, os.path.splitext(filename)[1].lower())
    count = len((await session.scalars(select(Attachment.id).where(Attachment.card_id == card.id))).all())
    if count >= MAX_ATTACHMENTS_PER_CARD:
        raise AppError(409, "attachments_limit", f"К карточке уже прикреплено {MAX_ATTACHMENTS_PER_CARD} файлов")
    is_image = kind.content_type in IMAGE_TYPES
    attachment = Attachment(card_id=card.id, uploader_id=user.id, filename=filename,
                            content_type=kind.content_type, size=len(data),
                            thumbnail=ThumbnailStatus.pending if is_image else ThumbnailStatus.none)
    session.add(attachment)
    await session.flush()
    session.add(AttachmentBlob(attachment_id=attachment.id, data=data))
    if is_image:
        await enqueue(session, "thumbnail", {"attachment_id": attachment.id})
    out = attachment_out(attachment)
    await publish(session, card.board_id, "attachment.created", dump(out), actor=user, client_id=client_id,
                  activity=("attachment.created", f"Файл «{filename}» прикреплён к «{card.title}»"))
    await session.commit()
    return out


async def card_attachments(session: AsyncSession, card_id: int) -> list[AttachmentOut]:
    rows = await session.scalars(select(Attachment).where(Attachment.card_id == card_id).order_by(Attachment.id))
    return [attachment_out(a) for a in rows]


async def attachment_for(session: AsyncSession, attachment_id: int, user: User) -> Attachment:
    attachment = await session.get(Attachment, attachment_id)
    if attachment is None:
        raise not_found("Вложение")
    try:
        await card_for(session, attachment.card_id, user)
    except AppError:
        raise not_found("Вложение") from None
    return attachment


async def delete_attachment(session: AsyncSession, attachment_id: int, user: User, client_id: str | None) -> None:
    attachment = await attachment_for(session, attachment_id, user)
    card = await card_for(session, attachment.card_id, user)
    await session.delete(attachment)
    await publish(session, card.board_id, "attachment.deleted", {"id": attachment_id, "card_id": card.id},
                  actor=user, client_id=client_id,
                  activity=("attachment.deleted", f"Файл «{attachment.filename}» удалён из «{card.title}»"))
    await session.commit()


async def blob(session: AsyncSession, attachment_id: int, thumbnail: bool) -> tuple[Attachment, bytes]:
    attachment = await session.get(Attachment, attachment_id)
    stored = await session.get(AttachmentBlob, attachment_id)
    if attachment is None or stored is None:
        raise not_found("Вложение")
    if thumbnail:
        if stored.thumbnail is None:
            raise not_found("Превью")
        return attachment, stored.thumbnail
    return attachment, stored.data
