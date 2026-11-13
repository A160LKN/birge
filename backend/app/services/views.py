"""Сборка ответов API из строк БД: счётчики, обложки, подписанные ссылки."""
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, Card, Comment, ThumbnailStatus
from app.schemas import AttachmentOut, CardOut
from app.security import signed_url


def attachment_out(attachment: Attachment) -> AttachmentOut:
    thumb = (signed_url(f"/attachments/{attachment.id}/thumbnail")
             if attachment.thumbnail == ThumbnailStatus.ready else None)
    return AttachmentOut(id=attachment.id, card_id=attachment.card_id, filename=attachment.filename,
                         content_type=attachment.content_type, size=attachment.size,
                         thumbnail=attachment.thumbnail, uploader_id=attachment.uploader_id,
                         created_at=attachment.created_at, url=signed_url(f"/attachments/{attachment.id}/file"),
                         thumbnail_url=thumb)


async def cards_out(session: AsyncSession, *conditions: ColumnElement[bool]) -> list[CardOut]:
    comments = select(func.count()).where(Comment.card_id == Card.id).correlate(Card).scalar_subquery()
    attachments = select(func.count()).where(Attachment.card_id == Card.id).correlate(Card).scalar_subquery()
    cover = (select(Attachment.id)
             .where(Attachment.card_id == Card.id, Attachment.thumbnail == ThumbnailStatus.ready)
             .order_by(Attachment.id).limit(1).correlate(Card).scalar_subquery())
    rows = await session.execute(
        select(Card, comments, attachments, cover).where(*conditions).order_by(Card.position, Card.id))
    return [
        CardOut.model_validate(card).model_copy(update={
            "comments": n_comments, "attachments": n_attachments,
            "cover_url": signed_url(f"/attachments/{cover_id}/thumbnail") if cover_id else None})
        for card, n_comments, n_attachments, cover_id in rows
    ]


async def card_out(session: AsyncSession, card_id: int) -> CardOut:
    (card,) = await cards_out(session, Card.id == card_id)
    return card


def dump(model: Any) -> dict[str, Any]:
    """Pydantic-модель → JSON-совместимый словарь для журнала событий."""
    return model.model_dump(mode="json")
