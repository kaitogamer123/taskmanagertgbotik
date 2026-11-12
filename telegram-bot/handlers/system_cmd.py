"""Системные команды: отмена текущего шага (/cancel) и ручной пулл с GitHub (/update)."""
from __future__ import annotations

import asyncio
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import OWNER_IDS
from database.db_manager import UserDB
from database.settings_repo import is_timezone_configured
from keyboards.reply import main_reply_keyboard
from services.auto_pull import check_and_pull_updates, restart_bot_process

router = Router(name="system_cmd")


@router.message(Command("update", "pull"))
async def cmd_update(message: Message, bot: Bot) -> None:
    if not message.from_user or message.from_user.id not in OWNER_IDS:
        await message.answer("⛔ Эта команда доступна только владельцу бота.")
        return

    status_msg = await message.answer("🔄 Проверяю обновления на GitHub (`git pull`)...")
    res = await check_and_pull_updates(force_pull=True)
    if res.updated:
        await status_msg.edit_text(
            f"🚀 <b>Обновление установлено!</b>\n"
            f"Коммит: <code>{html.escape(res.old_commit)}</code> → "
            f"<code>{html.escape(res.new_commit)}</code>\n\n"
            f"♻️ Перезапускаю процесс бота..."
        )
        asyncio.create_task(restart_bot_process(bot))
    else:
        await status_msg.edit_text(
            f"ℹ️ <b>Статус обновления:</b>\n{html.escape(res.message)}"
        )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db: UserDB) -> None:
    if not is_timezone_configured(db):
        await message.answer(
            "Сначала укажи, пожалуйста, какой у тебя сейчас час (от 0 до 23) 🕐"
        )
        return
    await state.clear()
    await message.answer(
        "Действие отменено 👌", reply_markup=main_reply_keyboard()
    )


@router.callback_query(F.data == "cancel_flow")
async def cb_cancel_flow(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await callback.answer("Отменено")
    if not is_timezone_configured(db):
        return
    await state.clear()
    if callback.message:
        await callback.message.answer(
            "Действие отменено 👌", reply_markup=main_reply_keyboard()
        )
