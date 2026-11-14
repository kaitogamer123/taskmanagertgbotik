from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database.db_manager import UserDB
from database.settings_repo import clear_user_blocked
from keyboards.reply import main_reply_keyboard

router = Router(name="start")

WELCOME_TEXT = (
    "Привет! Я бот-органайзер для твоих планов 🗓\n\n"
    "Вот что я умею (пользуйся кнопками внизу или командами):\n"
    "• <b>📅 Мои планы</b> (/MyPlans) — планы на ближайшую неделю или любой день\n"
    "• <b>📋 Дни с задачами</b> (/alldays) — список всех дней, где вообще есть задачи\n"
    "• <b>➕ Новая задача</b> (/NewPlan) — добавить разовую задачу\n"
    "• <b>🔁 Повторяющаяся</b> (/everyN) — добавить повторяющуюся задачу\n"
    "• <b>📝 Заметки</b> (/notes) — папки, текст, чек-листы и файлы\n"
    "• <b>🗑 Удалить задачу</b> — быстрое удаление любых задач\n"
    "• <b>⚙️ Настройка времени</b> (/notify, /changeTime) — настройка часового пояса "
    "и времени утренней/вечерней сводки\n"
    "• /database — скачать файл своей базы данных (.db)\n\n"
    "Также в любой момент можешь просто написать дату (например, <code>19.10</code> "
    "или «в четверг»), и я сразу открою планы на этот день!\n\n"
    "Подробная справка: /help"
)

HELP_TEXT = (
    "📖 <b>Что я умею</b>\n\n"
    "📅 <b>Мои планы</b> — /MyPlans или просто напиши дату.\n"
    "📋 <b>Дни с задачами</b> — /alldays.\n"
    "📆 <b>Календарь</b> — /calendar: месяц с днями, где есть задачи.\n"
    "📤 <b>Экспорт</b> — /export: календарь .ics для Google/Apple Calendar.\n"
    "➕ <b>Новая задача</b> — /NewPlan: дата, время, название, описание, напоминание.\n"
    "⚡ <b>Быстро</b> — /add завтра 10:00-11:00 Созвон.\n"
    "🔁 <b>Повторяющаяся</b> — /everyN: каждый день, каждые N дней, по дням недели, "
    "каждый месяц или год.\n"
    "📝 <b>Заметки</b> — /notes: папки, текст, чек-листы, фото и файлы.\n"
    "📋 <b>Шаблоны</b> — /templates: сохранить заготовку и создать задачу в 1 клик.\n"
    "🔎 <b>Поиск</b> — /find: ищет по задачам и заметкам.\n"
    "📊 <b>Статистика</b> — /stats: сколько выполнено за неделю.\n"
    "💬 <b>Обратная связь</b> — /feedback или кнопка внизу.\n"
    "🗑 <b>Удалить</b> — /delete.\n"
    "⚙️ <b>Настройки</b> — /notify: сводки, пустые сводки, тихие часы, часовой пояс.\n"
    "🌍 <b>Часовой пояс</b> — /changeTime.\n"
    "📂 <b>База данных</b> — /database.\n"
    "❌ <b>Отмена</b> — /cancel.\n\n"
    "💡 <b>Примеры дат:</b> <code>19.10</code>, <code>19.10.2026</code>, «сегодня», "
    "«завтра», «через 3 дня», «в четверг», «на следующей неделе в среду».\n"
    "💡 <b>Примеры времени:</b> <code>14:30</code>, <code>14</code>, «9 вечера», «9:30 утра».\n"
    "💡 <b>Примеры напоминаний:</b> «за 30 минут», «за 1 час 30 минут», «за 2 дня»."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    clear_user_blocked(db)
    await message.answer(WELCOME_TEXT, reply_markup=main_reply_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_reply_keyboard())
