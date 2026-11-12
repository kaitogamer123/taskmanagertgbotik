"""
Миддлварь первичной настройки времени.
Если пользователь ещё ни разу не указал свой текущий час (`timezone_configured == 0`),
бот в самом начале работы спрашивает, сколько у него сейчас времени (достаточно часа),
чтобы определить его часовой пояс.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from config import OWNER_IDS
from database.db_manager import UserDB
from database.settings_repo import is_timezone_configured
from keyboards.inline import hour_picker_keyboard
from states import TimezoneStates

FIRST_TIME_PROMPT = (
    "👋 Привет! Я бот-органайзер для твоих планов 🗓\n\n"
    "Перед началом работы давай узнаем твой часовой пояс, чтобы задачи, "
    "«сегодня/завтра» и все напоминания работали точно по твоему времени ⏰\n\n"
    "🕐 <b>Сколько у тебя сейчас времени?</b>\n"
    "Достаточно написать или нажать кнопку ниже, <b>какой у тебя сейчас час</b> "
    "(от <code>0</code> до <code>23</code>, например <code>15</code> или <code>15:30</code>):"
)


class TimezoneGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        db: UserDB | None = data.get("db")
        state: FSMContext | None = data.get("state")
        user: User | None = data.get("event_from_user")

        if db is None or state is None or user is None or user.is_bot:
            return await handler(event, data)

        if is_timezone_configured(db):
            return await handler(event, data)

        # Разрешаем системную команду /update владельцу даже до настройки пояса
        if (
            isinstance(event, Message)
            and event.text
            and event.text.strip().lower().startswith("/update")
            and user.id in OWNER_IDS
        ):
            return await handler(event, data)

        current_state = await state.get_state()

        if current_state == TimezoneStates.waiting_hour.state:
            if isinstance(event, CallbackQuery) and (event.data or "").startswith("tz_hour:"):
                return await handler(event, data)
            if isinstance(event, Message) and not (
                event.text and event.text.strip().lower().startswith("/start")
            ):
                return await handler(event, data)

        await state.set_state(TimezoneStates.waiting_hour)
        await state.update_data(first_setup=True)

        if isinstance(event, Message):
            await event.answer(
                FIRST_TIME_PROMPT,
                reply_markup=hour_picker_keyboard(allow_cancel=False),
            )
        elif isinstance(event, CallbackQuery):
            await event.answer()
            if event.message:
                await event.message.answer(
                    FIRST_TIME_PROMPT,
                    reply_markup=hour_picker_keyboard(allow_cancel=False),
                )
        return None
