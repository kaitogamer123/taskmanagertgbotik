"""Простой антиспам по user_id и базовая валидация callback_data."""
from __future__ import annotations

import re
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

_CALLBACK_RE = re.compile(r"^[A-Za-z0-9_:.\-]+$")


class AntispamMiddleware(BaseMiddleware):
    def __init__(
        self, message_interval: float = 0.4, callback_interval: float = 0.25
    ) -> None:
        self.message_interval = message_interval
        self.callback_interval = callback_interval
        self._last_message: Dict[int, float] = {}
        self._last_callback: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        now = time.monotonic()

        if isinstance(event, CallbackQuery):
            if event.data and not _CALLBACK_RE.match(event.data):
                await event.answer("Кнопка устарела", show_alert=True)
                return
            if now - self._last_callback.get(user.id, 0.0) < self.callback_interval:
                await event.answer()
                return
            self._last_callback[user.id] = now
            if len(self._last_callback) > 10000:
                self._last_callback.clear()
        elif isinstance(event, Message):
            if now - self._last_message.get(user.id, 0.0) < self.message_interval:
                return
            self._last_message[user.id] = now
            if len(self._last_message) > 10000:
                self._last_message.clear()

        return await handler(event, data)
