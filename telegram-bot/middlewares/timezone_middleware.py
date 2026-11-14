"""
Миддлварь первичной настройки часового пояса.
Если пользователь ещё не настроил пояс, бот предлагает выбрать город/IANA-зону;
есть резервный режим «по текущему часу».
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from config import OWNER_IDS
from database.db_manager import UserDB
from database.settings_repo import is_timezone_configured
from keyboards.inline import timezone_picker_keyboard
from keyboards.reply import MAIN_MENU_BUTTONS
from states import TimezoneStates

FIRST_TIME_PROMPT = (
    "👋 Привет! Я бот-органайзер для твоих планов 🗓\n\n"
    "Перед началом работы выбери свой <b>город или часовой пояс</b>, "
    "чтобы «сегодня/завтра» и напоминания работали точно по твоему времени.\n\n"
    "Если нужного города нет — нажми «⌨️ Другой город» и напиши "
    "название (например, <code>Москва</code> или <code>Europe/Moscow</code>)."
)

_ZONE_STATES = {
    TimezoneStates.waiting_zone.state,
    TimezoneStates.waiting_zone_name.state,
    TimezoneStates.waiting_hour.state,
}
_ZONE_CALLBACKS = ("tz_hour:", "tz_set:", "tz_other", "tz_hour_mode")


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

        # Справку можно читать даже до настройки пояса
        if isinstance(event, Message) and event.text:
            command = event.text.strip().lower().split("@", 1)[0]
            if command in {"/help", "/guide"}:
                return await handler(event, data)

        # Системные команды владельца доступны до настройки пояса
        if isinstance(event, Message) and event.text and user.id in OWNER_IDS:
            command = event.text.strip().lower().split("@", 1)[0]
            if command in {
                "/update",
                "/status",
                "/restart",
                "/backup",
                "/broadcast",
            }:
                return await handler(event, data)

        current_state = await state.get_state()

        if current_state in _ZONE_STATES:
            if isinstance(event, CallbackQuery):
                if (event.data or "").startswith(_ZONE_CALLBACKS):
                    return await handler(event, data)
            elif isinstance(event, Message):
                text = (event.text or "").strip()
                if text.lower().startswith("/start"):
                    pass  # покажем выбор пояса заново
                elif text.startswith("/"):
                    return await handler(event, data)
                elif text not in MAIN_MENU_BUTTONS:
                    return await handler(event, data)

        await state.set_state(TimezoneStates.waiting_zone)
        await state.update_data(first_setup=True)

        reply_markup = timezone_picker_keyboard(allow_cancel=False)
        if isinstance(event, Message):
            await event.answer(FIRST_TIME_PROMPT, reply_markup=reply_markup)
        elif isinstance(event, CallbackQuery):
            await event.answer()
            if event.message:
                await event.message.answer(
                    FIRST_TIME_PROMPT, reply_markup=reply_markup
                )
        return None
