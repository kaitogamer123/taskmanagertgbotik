"""Обратная связь: сообщение владельцу бота."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import OWNER_IDS
from keyboards.reply import BTN_FEEDBACK, MAIN_MENU_BUTTONS, main_reply_keyboard
from states import FeedbackStates

router = Router(name="feedback")


@router.message(Command("feedback", ignore_case=True))
@router.message(F.text == BTN_FEEDBACK)
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(FeedbackStates.waiting_text)
    await message.answer(
        "💬 Напиши сообщение для владельца бота. /cancel — отмена."
    )


@router.message(
    StateFilter(FeedbackStates.waiting_text),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_feedback(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Сообщение не может быть пустым.")
        return
    if len(text) > 3000:
        await message.answer("Слишком длинное сообщение, максимум 3000 символов.")
        return

    user = message.from_user
    username = f"@{user.username}" if user and user.username else "без username"
    header = (
        "💬 <b>Обратная связь</b>\n"
        f"👤 <code>{user.id if user else 0}</code> ({html.escape(username)})\n\n"
    )
    for owner in OWNER_IDS:
        try:
            await bot.send_message(owner, header + html.escape(text))
        except Exception:  # noqa: BLE001
            pass

    await state.clear()
    await message.answer(
        "Спасибо! Передал сообщение владельцу.", reply_markup=main_reply_keyboard()
    )
