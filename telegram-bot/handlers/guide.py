"""Полная справка по боту: /help, /guide и кнопка «📖 Помощь»."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.reply import BTN_HELP
from utils.text import MAX_MESSAGE

router = Router(name="guide")

GUIDE_MENU_TEXT = (
    "📖 <b>Справка TaskMNGR</b>\n\n"
    "Выбери раздел — расскажу, как всё работает, с примерами.\n\n"
    "Если нужного не нашёл — напиши владельцу через /feedback."
)

# (ключ, название кнопки, текст раздела)
GUIDE_SECTIONS: list[tuple[str, str, str]] = [
    (
        "start",
        "🚀 Начало",
        "🚀 <b>С чего начать</b>\n\n"
        "1. При первом запуске выбери <b>город/часовой пояс</b> — от него зависят "
        "«сегодня/завтра» и напоминания.\n"
        "2. Внизу — постоянное меню:\n"
        "• 📅 <b>Активные планы</b> — сегодня и ближайшая неделя\n"
        "• 🕓 <b>История планов</b> — прошедшие дни и выполненные задачи\n"
        "• 📋 <b>Дни с задачами</b> — активные дни\n"
        "• ➕ <b>Новая задача</b>, 🔁 <b>Повторяющаяся</b>\n"
        "• 🗑 <b>Удалить задачу</b>, 📝 <b>Заметки</b>\n"
        "• ⚙️ <b>Настройка времени</b>, 💬 <b>Обратная связь</b>, 📖 <b>Помощь</b>\n\n"
        "3. Команды: /MyPlans, /history, /alldays, /NewPlan, /add, /everyN, "
        "/notes, /templates, /find, /stats, /export, /database, /notify, "
        "/changeTime, /cancel.\n\n"
        "Если нижняя клавиатура старая — отправь <b>/start</b>.",
    ),
    (
        "plans",
        "📅 Активные планы",
        "📅 <b>Активные планы и день</b>\n\n"
        "• /MyPlans или кнопка «📅 Активные планы» — ближайшая неделя.\n"
        "• В меню недели: «📋 Активные дни», «🕓 История», «📆 Календарь», "
        "«📊 Статистика», «📤 Экспорт .ics», «📋 Шаблоны», «⚙️ Настройка времени», "
        "«🗑 Удалить задачу».\n"
        "• Нажми день → откроется список задач.\n"
        "• Нажми задачу → карточка: «✅ Готово», «✏️ Редактировать», "
        "«🔔 Напоминания», «💾 Сохранить как шаблон», «🗑 Удалить».\n\n"
        "<b>Что умеет карточка:</b>\n"
        "• ✅ отметить выполненной — задача не попадёт в сводки и напоминания;\n"
        "• ✏️ изменить название, описание, дату/дату начала повтора, время;\n"
        "• 🔔 добавить несколько напоминаний;\n"
        "• 💾 сохранить как шаблон.\n\n"
        "Прошедшие дни не показываются в активных — они в «🕓 История планов».",
    ),
    (
        "new",
        "➕ Новая задача",
        "➕ <b>Новая задача</b>\n\n"
        "<b>По шагам:</b> /NewPlan → дата → время начала → окончание "
        "(можно «Без окончания») → название → описание (можно «Без описания») "
        "→ напоминание.\n\n"
        "<b>Одной строкой:</b> /add завтра 10:00-11:00 Созвон\n"
        "Ещё примеры:\n"
        "<code>/add 19.10 14:30 Позвонить</code>\n"
        "<code>/add в четверг Сходить в зал</code>\n\n"
        "<b>Даты:</b> 19.10, 19.10.2026, сегодня, завтра, послезавтра, через 3 дня, "
        "в четверг, на следующей неделе в среду, через месяц.\n"
        "<b>Время:</b> 14:30, 14, 9 вечера, 9:30 утра, полдень, полночь.\n"
        "<b>Напоминания:</b> «за 30 минут», «за 1 час 30 минут», «за 2 дня».\n\n"
        "Лимиты: название — 100 символов, описание — 1500.",
    ),
    (
        "repeat",
        "🔁 Повторяющиеся",
        "🔁 <b>Повторяющиеся задачи</b>\n\n"
        "/everyN или кнопка «🔁 Повторяющаяся». Бот спросит название/описание, "
        "время, периодичность, дату старта и напоминание.\n\n"
        "<b>Периодичность:</b>\n"
        "• каждый день;\n"
        "• каждые N дней (1–365);\n"
        "• по дням недели (например, «по понедельникам и средам»);\n"
        "• каждый месяц N числа;\n"
        "• каждый год N месяца.\n\n"
        "<b>Особенности:</b>\n"
        "• «каждый месяц 31 числа» в коротких месяцах сработает в последний день;\n"
        "• 29 февраля задаётся текстом «каждый год 29 февраля»;\n"
        "• удалить можно только один день или все повторения;\n"
        "• поставить на паузу — «🗑 Удалить задачу» → «Все повторяющиеся» → "
        "кнопка ⏸/▶️ у нужного правила.",
    ),
    (
        "reminders",
        "🔔 Напоминания",
        "🔔 <b>Напоминания и сводки</b>\n\n"
        "• В карточке задачи — «🔔 Напоминания (N)».\n"
        "• Пресеты: 15 минут, 30 минут, 1 час, 2 часа, 1 день.\n"
        "• «⏰ Своё значение» — любой интервал, например «за 45 минут».\n"
        "• Каждое напоминание приходит отдельно и не дублируется.\n"
        "• Под напоминанием: +10 / +30 / +60 минут (snooze).\n\n"
        "<b>Сводки:</b> /notify — утренняя (планы на сегодня) и вечерняя "
        "(планы на завтра), можно включать/выключать и менять время.\n"
        "• «Пустые сводки» можно отключить.\n"
        "• «Тихие часы» (по умолчанию выкл., 23:00–08:00): напоминания ночью "
        "переносятся на утро.\n"
        "• Выполненные задачи в сводки и напоминания не попадают.",
    ),
    (
        "notes",
        "📝 Заметки",
        "📝 <b>Заметки</b>\n\n"
        "/notes или кнопка «📝 Заметки».\n\n"
        "• Папки: одна папка на заметку, можно переносить; есть «Без папки».\n"
        "• Заметка: текст, интерактивный чек-лист, фото/файлы.\n"
        "• Файлы <b>не хранятся на сервере</b>: бот запоминает file_id и "
        "пересылает файл из чата. Если сообщение удалено — предупредит, что файл "
        "недоступен.\n\n"
        "<b>В карточке заметки:</b>\n"
        "• ✏️ текст, 📝 заголовок;\n"
        "• ☑️ добавить пункт, нажать на пункт — отметить/снять;\n"
        "• 📎 добавить файл, «Показать файлы»;\n"
        "• 📁 папка, 📅 дата заметки;\n"
        "• 📤 экспорт в .md, 🗑 удалить.\n\n"
        "Поиск: /find или «🔎 Поиск» в заметках.",
    ),
    (
        "templates",
        "📋 Шаблоны",
        "📋 <b>Шаблоны задач</b>\n\n"
        "/templates или «📋 Шаблоны» в меню недели.\n\n"
        "• Сохранить из карточки задачи: «💾 Сохранить как шаблон».\n"
        "• Создать вручную: «➕ Новый шаблон» и одна строка:\n"
        "<code>Созвон | с командой | 10:00-11:00 | за 30 минут</code>\n"
        "Описание, время и напоминание можно не указывать.\n\n"
        "• Применить: «Сегодня», «Завтра» или «Другая дата».\n"
        "• Удалить шаблон — с подтверждением.\n"
        "В шаблон сохраняется одно напоминание (максимальное); после применения "
        "можно добавить ещё.",
    ),
    (
        "history",
        "🕓 История",
        "🕓 <b>История планов</b>\n\n"
        "/history или кнопка «🕓 История планов».\n\n"
        "• Показывает прошедшие дни и дни с выполненными задачами.\n"
        "• Сначала самые новые, по 5 дней на страницу.\n"
        "• Нажми день — откроются задачи; можно посмотреть или удалить.\n\n"
        "Активные планы — /MyPlans; старые дни в активных списках больше не мешают.",
    ),
    (
        "find",
        "🔎 Поиск/статистика",
        "🔎 <b>Поиск и статистика</b>\n\n"
        "• /find текст — ищет по названию/описанию задач, повторяющихся правил "
        "и заметок.\n"
        "• /stats — сколько разовых и повторяющихся задач выполнено за 7 дней, "
        "сколько активных задач и повторов сейчас.\n"
        "• Поиск заметок также доступен кнопкой «🔎 Поиск» в /notes.",
    ),
    (
        "export",
        "📤 Экспорт/база",
        "📤 <b>Экспорт и база</b>\n\n"
        "• /export или «📤 Экспорт .ics» — календарь на 30 дней для "
        "Google/Apple Calendar. Внутри — задачи и повторения.\n"
        "• /database — скачать личную SQLite-базу со всеми планами. "
        "Файл можно открыть в DB Browser for SQLite.\n"
        "• База у каждого пользователя своя; .env и базы не попадают в Git.",
    ),
    (
        "settings",
        "⚙️ Настройки",
        "⚙️ <b>Настройки</b>\n\n"
        "• /notify — утренняя/вечерняя сводка, пустые сводки, тихие часы, "
        "часовой пояс.\n"
        "• /changeTime — выбор города/IANA-зоны. Учитывается переход на "
        "летнее/зимнее время и смещения вида UTC+5:30. Есть резервный режим "
        "«🕐 По текущему времени».\n"
        "• Часовой пояс хранится в user_settings.timezone_name.\n"
        "• Если нижняя клавиатура старая — /start.",
    ),
    (
        "tips",
        "💡 Полезное",
        "💡 <b>Полезное</b>\n\n"
        "• /cancel — отменить текущий шаг (создание задачи, заметки и т.п.).\n"
        "• /feedback или кнопка «💬 Обратная связь» — написать владельцу.\n"
        "• Владельцу: /status (версия, аптайм, пользователи), /restart, "
        "/backup, /broadcast.\n"
        "• Лимиты: название задачи 100, описание 1500, текст заметки 4000.\n"
        "• Если бот не отвечает — проверь /status или запусти TaskMNGR.bat.\n"
        "• Бэкапы: ежедневный cron + /backup у владельца.",
    ),
]

GUIDE_BY_KEY = {key: (title, text) for key, title, text in GUIDE_SECTIONS}
GUIDE_ORDER = [key for key, _, _ in GUIDE_SECTIONS]


def guide_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for key, title, _ in GUIDE_SECTIONS:
        builder.button(text=title, callback_data=f"guide:{key}")
    builder.adjust(2)
    return builder.as_markup()


def guide_section_keyboard(key: str):
    builder = InlineKeyboardBuilder()
    try:
        index = GUIDE_ORDER.index(key)
    except ValueError:
        index = 0
    nav: list[InlineKeyboardButton] = []
    if index > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"guide:{GUIDE_ORDER[index - 1]}"
            )
        )
    if index + 1 < len(GUIDE_ORDER):
        nav.append(
            InlineKeyboardButton(
                text="Далее ➡️", callback_data=f"guide:{GUIDE_ORDER[index + 1]}"
            )
        )
    if nav:
        builder.row(*nav)
    builder.row(
        InlineKeyboardButton(text="📖 К разделам", callback_data="guide:menu")
    )
    return builder.as_markup()


async def _safe_edit(message: Message, text: str, reply_markup) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            await message.answer(text, reply_markup=reply_markup)


@router.message(Command("help", "guide", ignore_case=True))
@router.message(F.text == BTN_HELP)
async def cmd_guide(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(GUIDE_MENU_TEXT, reply_markup=guide_menu_keyboard())


@router.callback_query(F.data.startswith("guide:"))
async def cb_guide(callback: CallbackQuery) -> None:
    key = (callback.data or "").split(":", 1)[1]
    await callback.answer()
    if callback.message is None:
        return
    if key == "menu":
        await _safe_edit(
            callback.message, GUIDE_MENU_TEXT, guide_menu_keyboard()
        )
        return

    section = GUIDE_BY_KEY.get(key)
    if section is None:
        await _safe_edit(
            callback.message, GUIDE_MENU_TEXT, guide_menu_keyboard()
        )
        return

    _, text = section
    if len(text) > MAX_MESSAGE:
        text = text[: MAX_MESSAGE - 1] + "…"
    await _safe_edit(callback.message, text, guide_section_keyboard(key))
