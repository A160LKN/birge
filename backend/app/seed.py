"""Демо-данные: два аккаунта и доска с карточками, чтобы живой сайт можно было сразу попробовать вдвоём.

Запускается при старте контейнера и ничего не делает, если демо-аккаунт уже есть.
"""
import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Board, BoardColumn, BoardMember, Card, Comment, Role, User, utcnow
from app.positions import keys_after
from app.security import hash_password

DEMO_PASSWORD = "birge-demo"  # noqa: S105 — публичный демо-пароль, указан в README
DEMO = [("aliya@birge.kz", "Алия"), ("bauyrzhan@birge.kz", "Бауыржан")]
CARDS = {
    "Нужно сделать": [("Собрать отзывы первых пользователей", "Пять коротких интервью, вопросы — в комментариях", 1),
                      ("Подключить оплату", "", None),
                      ("Тексты для страницы тарифов", "", 0)],
    "В работе": [("Мобильная вёрстка доски", "Колонки листаются по горизонтали, карточки — на всю ширину", 0),
                 ("Уведомления о сроках", "Фоновая задача раз в час проверяет сроки", 1)],
    "На проверке": [("Экспорт доски в CSV", "Проверить в Excel и Google Таблицах", 1)],
    "Готово": [("Регистрация и вход", "", 0), ("Карточки в реальном времени", "", 1)],
}


async def seed() -> None:
    async with SessionLocal() as session:
        if await session.scalar(select(User).where(User.email == DEMO[0][0])):
            return
        users = [User(email=email, name=name, password_hash=hash_password(DEMO_PASSWORD)) for email, name in DEMO]
        session.add_all(users)
        await session.flush()
        board = Board(title="Запуск Бірге", created_by=users[0].id)
        session.add(board)
        await session.flush()
        session.add_all([BoardMember(board_id=board.id, user_id=users[0].id, role=Role.owner),
                         BoardMember(board_id=board.id, user_id=users[1].id, role=Role.member)])
        today = utcnow().date()
        for (title, cards), column_key in zip(CARDS.items(), keys_after(None, len(CARDS)), strict=True):
            column = BoardColumn(board_id=board.id, title=title, position=column_key)
            session.add(column)
            await session.flush()
            for n, ((card_title, description, assignee), key) in enumerate(
                    zip(cards, keys_after(None, len(cards)), strict=True)):
                card = Card(board_id=board.id, column_id=column.id, title=card_title, description=description,
                            position=key, created_by=users[0].id,
                            assignee_id=users[assignee].id if assignee is not None else None,
                            due_date=today + timedelta(days=3 + n * 4) if title != "Готово" else None)
                session.add(card)
                if n == 0 and title == "Нужно сделать":
                    await session.flush()
                    session.add(Comment(card_id=card.id, author_id=users[1].id,
                                        body="Кого позовём? Я могу договориться с тремя знакомыми командами"))
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
