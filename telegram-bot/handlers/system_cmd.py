"""Системные команды: /cancel, /status, /restart, /update и ручной пулл с GitHub."""
from __future__ import annotations

import asyncio
import html
import sys
import time
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from config import (
    AUTO_PULL_ENABLED,
    AUTO_PULL_INTERVAL,
    BASE_DIR,
    BOT_VERSION,
    NOTIFIER_POLL_INTERVAL,
    OWNER_IDS,
    PLANES_USER_DIR,
)
from database.db_manager import UserDB, iter_all_user_ids
from database.settings_repo import is_timezone_configured
from keyboards.reply import main_reply_keyboard
from services.auto_pull import (
    check_and_pull_updates,
    find_git_root,
    restart_bot_process,
)

router = Router(name="system_cmd")

STARTED_AT = time.monotonic()


def _fmt_uptime(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    parts.append(f"{minutes} мин")
    return " ".join(parts)


def _is_owner(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in OWNER_IDS)


@router.message(Command("status"))
async def cmd_status(message: Message, bot: Bot) -> None:
    if not _is_owner(message):
        await message.answer("⛔ Эта команда доступна только владельцу бота.")
        return

    users = len(list(iter_all_user_ids()))
    db_bytes = sum(
        p.stat().st_size for p in PLANES_USER_DIR.glob("*.db") if p.is_file()
    )
    git_root = await find_git_root()
    await message.answer(
        "🤖 <b>TaskMNGR</b>\n"
        f"Версия: <code>{html.escape(BOT_VERSION)}</code>\n"
        f"Аптайм: {_fmt_uptime(time.monotonic() - STARTED_AT)}\n"
        f"Пользователей: {users}\n"
        f"Базы: {db_bytes / 1024 / 1024:.2f} МБ\n"
        f"Уведомления: каждые {NOTIFIER_POLL_INTERVAL} сек.\n"
        f"Автопулл: {'вкл' if AUTO_PULL_ENABLED else 'выкл'} "
        f"({AUTO_PULL_INTERVAL} сек., git: {'есть' if git_root else 'нет'})\n"
        f"Python: {sys.version.split()[0]}\n"
        f"Папка: <code>{html.escape(str(BASE_DIR))}</code>"
    )


@router.message(Command("restart"))
async def cmd_restart(message: Message, bot: Bot) -> None:
    if not _is_owner(message):
        await message.answer("⛔ Эта команда доступна только владельцу бота.")
        return
    await message.answer("♻️ Перезапускаю бота...")
    asyncio.create_task(restart_bot_process(bot))


@router.message(Command("backup"))
async def cmd_backup(message: Message) -> None:
    if not _is_owner(message):
        await message.answer("⛔ Эта команда доступна только владельцу бота.")
        return

    status_msg = await message.answer("💾 Делаю бэкап баз...")
    script = BASE_DIR / "backup.sh"
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(script),
            cwd=str(BASE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except Exception as exc:  # noqa: BLE001
        await status_msg.edit_text(f"❌ Не удалось запустить бэкап: {exc}")
        return

    if proc.returncode != 0:
        error_text = stderr.decode("utf-8", errors="replace")[-1000:]
        await status_msg.edit_text(
            f"❌ Бэкап не удался:\n<code>{html.escape(error_text)}</code>"
        )
        return

    output = stdout.decode("utf-8", errors="replace").strip().splitlines()
    backup_path = Path(output[-1]) if output else None
    if backup_path is None or not backup_path.exists():
        await status_msg.edit_text("❌ Бэкап создан, но файл не найден.")
        return

    size_mb = backup_path.stat().st_size / 1024 / 1024
    if size_mb <= 45:
        await message.answer_document(
            FSInputFile(backup_path, filename=backup_path.name),
            caption=f"💾 Бэкап баз: <code>{html.escape(backup_path.name)}</code> "
            f"({size_mb:.1f} МБ)",
        )
        try:
            await status_msg.delete()
        except Exception:  # noqa: BLE001
            pass
    else:
        await status_msg.edit_text(
            f"✅ Бэкап создан: <code>{html.escape(str(backup_path))}</code> "
            f"({size_mb:.1f} МБ). Файл слишком большой для отправки в чат."
        )


@router.message(Command("update", "pull"))
async def cmd_update(message: Message, bot: Bot) -> None:
    if not _is_owner(message):
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
            f"ℹ️ <b>Статус обновления:</b>\n{html.escape(res.message)}\n\n"
            "Если сервер без git-репозитория — используй <b>/restart</b> "
            "или деплой через <code>TaskMNGR.bat</code>."
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
