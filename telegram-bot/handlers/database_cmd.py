from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from database.db_manager import UserDB

router = Router(name="database_cmd")


@router.message(Command("database"))
async def cmd_database(message: Message, db: UserDB) -> None:
    file = FSInputFile(db.path, filename=db.path.name)
    await message.answer_document(
        file,
        caption=(
            "Вот твоя база данных со всеми планами 📂\n"
            "Это обычный файл SQLite — его можно открыть любой программой, "
            "которая умеет работать с .db файлами (например, DB Browser for SQLite)."
        ),
    )
