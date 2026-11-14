from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message

from database.db_manager import UserDB

router = Router(name="database_cmd")


@router.message(Command("database", ignore_case=True))
async def cmd_database(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()

    # Отдаём не живой файл, а консистентную копию через SQLite Backup API:
    # если в этот момент планировщик пишет в базу, обычная копия могла бы
    # получиться битой.
    user_id = message.from_user.id if message.from_user else 0
    fd, tmp_name = tempfile.mkstemp(prefix=f"plans_{user_id}_", suffix=".db")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        dest = sqlite3.connect(tmp_path)
        try:
            with dest:
                db.conn.backup(dest)
        finally:
            dest.close()

        await message.answer_document(
            FSInputFile(tmp_path, filename=db.path.name),
            caption=(
                "Вот твоя база данных со всеми планами 📂\n"
                "Это обычный файл SQLite — его можно открыть любой программой, "
                "которая умеет работать с .db файлами (например, DB Browser for SQLite)."
            ),
        )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
