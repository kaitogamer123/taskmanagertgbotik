"""Рассылка от владельца всем пользователям."""
from __future__ import annotations

import asyncio
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import OWNER_IDS
from database.db_manager import iter_all_user_ids
from keyboards.reply import MAIN_MENU_BUTTONS
from states import BroadcastStates

router = Router(name="broadcast")


def _is_owner(user) -> bool:
    return bool(user and user.id in OWNER_IDS)


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not _is_owner(message.from_user):
        await message.answer("⛔ Эта команда доступна только владельцу бота.")
        return
    await state.clear()
    await state.set_state(BroadcastStates.waiting_text)
    await message.answer(
        "📣 Пришли текст рассылки (обычный текст, без HTML). /cancel — отмена."
    )


@router.message(
    StateFilter(BroadcastStates.waiting_text),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_broadcast_text(
    message: Message, state: FSMContext
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст не может быть пустым.")
        return
    if len(text) > 4000:
        await message.answer("Слишком длинный текст, максимум 4000 символов.")
        return

    await state.update_data(broadcast_text=text)
    await state.set_state(BroadcastStates.waiting_confirm)
    users_count = len(list(iter_all_user_ids()))

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📣 Отправить", callback_data="bc_send"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel"),
    )
    await message.answer(
        f"Отправить сообщение <b>{users_count}</b> пользователям?\n\n"
        f"{html.escape(text)}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "bc_cancel")
async def cb_broadcast_cancel(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text("Рассылка отменена.")


@router.callback_query(F.data == "bc_send")
async def cb_broadcast_send(
    callback: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    if not _is_owner(callback.from_user):
        await callback.answer("⛔ Только владелец", show_alert=True)
        return

    data = await state.get_data()
    text = data.get("broadcast_text")
    if not text:
        await callback.answer("Текст потерялся, начни заново", show_alert=True)
        await state.clear()
        return

    await state.clear()
    await callback.answer("Рассылаю...")
    if callback.message:
        await callback.message.edit_text("📣 Рассылка идёт...")

    sent = 0
    failed = 0
    for telegram_id in list(iter_all_user_ids()):
        try:
            await bot.send_message(telegram_id, text, parse_mode=None)
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.05)

    if callback.message:
        await callback.message.edit_text(
            f"✅ Отправлено: <b>{sent}</b>\n"
            f"⚠️ Не доставлено: <b>{failed}</b>"
        )
