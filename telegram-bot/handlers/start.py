from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.reply import main_reply_keyboard

router = Router(name="start")

WELCOME_TEXT = (
    "Привет! Я бот-органайзер для твоих планов 🗓\n\n"
    "Вот что я умею (пользуйся кнопками внизу или командами):\n"
    "• <b>📅 Мои планы</b> (/MyPlans) — планы на ближайшую неделю или любой день\n"
    "• <b>📋 Дни с задачами</b> (/alldays) — список всех дней, где вообще есть задачи\n"
    "• <b>➕ Новая задача</b> (/NewPlan) — добавить разовую задачу\n"
    "• <b>🔁 Повторяющаяся</b> (/everyN) — добавить повторяющуюся задачу\n"
    "• <b>🗑 Удалить задачу</b> — быстрое удаление любых задач\n"
    "• <b>⚙️ Настройка времени</b> (/notify, /changeTime) — настройка часового пояса "
    "и времени утренней/вечерней сводки\n"
    "• /database — скачать файл своей базы данных (.db)\n\n"
    "Также в любой момент можешь просто написать дату (например, <code>19.10</code> "
    "или «в четверг»), и я сразу открою планы на этот день!"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_reply_keyboard())
