from typing import Annotated

from fastapi import Header, Path

from app.schemas import MAX_ID

# Ключ вкладки браузера: клиент узнаёт свои же изменения в потоке событий и не применяет их дважды
ClientId = Annotated[str | None, Header(alias="X-Client-Id", max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
PathId = Annotated[int, Path(ge=1, le=MAX_ID)]
