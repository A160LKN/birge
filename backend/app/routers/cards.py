from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import AppError
from app.models import User
from app.routers.deps import ClientId, PathId
from app.schemas import AttachmentOut, CardDetail, CardIn, CardOut, CardPatch, CommentIn, CommentOut, MoveCardIn
from app.security import current_user, load_user, verify_signature
from app.services import cards, files
from app.services.access import card_for
from app.services.views import card_out

router = APIRouter(tags=["Карточки"])


@router.post("/cards", response_model=CardOut, status_code=status.HTTP_201_CREATED)
async def create_card(data: CardIn, client_id: ClientId = None, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    return await cards.create_card(session, user, data, client_id)


@router.get("/cards/{card_id}", response_model=CardDetail)
async def get_card(card_id: PathId, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    card = await card_for(session, card_id, user)
    summary = await card_out(session, card.id)
    return CardDetail(**summary.model_dump(), created_at=card.created_at, created_by=card.created_by,
                      comment_list=await cards.card_comments(session, card.id),
                      attachment_list=await files.card_attachments(session, card.id))


@router.patch("/cards/{card_id}", response_model=CardOut,
              responses={409: {"description": "Карточку уже изменили: в error.details.current — новая версия"}})
async def update_card(card_id: PathId, patch: CardPatch, client_id: ClientId = None,
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await cards.update_card(session, card_id, user, patch, client_id)


@router.post("/cards/{card_id}/move", response_model=CardOut)
async def move_card(card_id: PathId, data: MoveCardIn, client_id: ClientId = None,
                    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await cards.move_card(session, card_id, user, data, client_id)


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(card_id: PathId, client_id: ClientId = None, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    await cards.delete_card(session, card_id, user, client_id)


@router.post("/cards/{card_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED,
             tags=["Комментарии"])
async def add_comment(card_id: PathId, data: CommentIn, client_id: ClientId = None,
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await cards.add_comment(session, card_id, user, data.body, client_id)


# ---------- Вложения ----------

@router.post("/cards/{card_id}/attachments", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED,
             tags=["Вложения"])
async def upload(card_id: PathId, file: UploadFile = File(...), client_id: ClientId = None,
                 user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """До 5 МБ: картинки (PNG, JPEG, GIF, WEBP), PDF, TXT, CSV, MD. Для картинок в фоне готовится превью."""
    return await files.add_attachment(session, card_id, user, file, client_id)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Вложения"])
async def delete_attachment(attachment_id: PathId, client_id: ClientId = None, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    await files.delete_attachment(session, attachment_id, user, client_id)


_optional_bearer = HTTPBearer(auto_error=False)


async def _serve(request: Request, attachment_id: int, thumbnail: bool, expires: int | None, sig: str | None,
                 credentials: HTTPAuthorizationCredentials | None, session: AsyncSession) -> Response:
    """Файл отдаётся по подписанной ссылке (для тегов <img>) или по токену."""
    if expires is not None and sig is not None:
        if not verify_signature(request.url.path, expires, sig):
            raise AppError(403, "link_expired", "Ссылка на файл устарела — обновите страницу")
    elif credentials is not None:
        await files.attachment_for(session, attachment_id, await load_user(session, credentials.credentials))
    else:
        raise AppError(401, "unauthorized", "Нужна подписанная ссылка или токен")
    attachment, data = await files.blob(session, attachment_id, thumbnail)
    content_type = "image/webp" if thumbnail else attachment.content_type
    # Картинки показываем в браузере, остальное — только скачиванием. nosniff и sandbox:
    # браузер не станет угадывать тип и не выполнит скрипты, даже если файл окажется не тем, чем назван
    inline = thumbnail or attachment.content_type in files.IMAGE_TYPES
    headers = {"Content-Disposition": files.content_disposition(attachment.filename, inline),
               "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "default-src 'none'; sandbox",
               "Cache-Control": "private, max-age=3600"}
    return Response(data, media_type=content_type, headers=headers)


@router.get("/attachments/{attachment_id}/file", tags=["Вложения"], response_class=Response)
async def download(request: Request, attachment_id: PathId, expires: int | None = Query(None),
                   sig: str | None = Query(None, max_length=64),
                   credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
                   session: AsyncSession = Depends(get_session)):
    return await _serve(request, attachment_id, False, expires, sig, credentials, session)


@router.get("/attachments/{attachment_id}/thumbnail", tags=["Вложения"], response_class=Response)
async def thumbnail(request: Request, attachment_id: PathId, expires: int | None = Query(None),
                    sig: str | None = Query(None, max_length=64),
                    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
                    session: AsyncSession = Depends(get_session)):
    return await _serve(request, attachment_id, True, expires, sig, credentials, session)
