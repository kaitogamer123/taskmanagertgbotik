"""
Миддлварь, которая для каждого входящего события:
  1) открывает (или создаёт) персональную базу данных пользователя;
  2) не чаще раза в 5 минут проверяет, не поменялся ли его username,
     и при необходимости переименовывает файл базы;
  3) прокидывает открытое соединение `db` в хендлер через data["db"].
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from database.db_manager import ensure_user_db, maybe_refresh_username


class UserDBMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")

        if user is None or user.is_bot:
            return await handler(event, data)

        db = ensure_user_db(user.id, user.username, user.first_name)
        db = maybe_refresh_username(db, user.id, user.username, user.first_name)
        data["db"] = db

        try:
            return await handler(event, data)
        finally:
            db.close()
