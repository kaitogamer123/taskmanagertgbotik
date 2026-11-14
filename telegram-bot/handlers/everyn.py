from __future__ import annotations

import html
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.plans_repo import add_recurring_rule
from keyboards.inline import (
    cancel_inline_keyboard,
    every_n_type_keyboard,
    reminder_choice_keyboard,
    skip_keyboard,
    weekday_multiselect_keyboard,
)
from keyboards.reply import BTN_EVERY_N, MAIN_MENU_BUTTONS, main_reply_keyboard
from states import EveryNStates
from utils.clock import today_for_user
from utils.date_utils import (
    format_date_full_ru,
    is_skip_time_phrase,
    parse_day_month,
    parse_natural_date,
    parse_time,
    weekday_name,
)
from utils.reminder_utils import describe_reminder, parse_reminder_offset
from utils.repeat_parser import describe_rule, parse_repeat_phrase
from utils.text import (
    MAX_DESCRIPTION,
    MAX_TITLE,
    esc,
    unquote_menu_literal,
)

router = Router(name="everyn")


@router.message(Command("everyN", "everyn", ignore_case=True))
@router.message(F.text == BTN_EVERY_N)
async def cmd_every_n(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(EveryNStates.waiting_title)
    await message.answer(
        "Добавляем повторяющуюся задачу 🔁\n\n"
        "Напиши название задачи. Если хочешь добавить и описание — "
        "укажи его через вертикальную черту, например:\n"
        "<code>Пить витамины | Утром после завтрака</code>\n\n"
        f"<i>(название до {MAX_TITLE}, описание до {MAX_DESCRIPTION}; "
        "если название совпадает с кнопкой меню — оберни его в «кавычки»)</i>",
        reply_markup=cancel_inline_keyboard(),
    )


@router.message(
    StateFilter(EveryNStates.waiting_title),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_title(message: Message, state: FSMContext) -> None:
    raw = unquote_menu_literal((message.text or "").strip(), MAIN_MENU_BUTTONS)
    if not raw:
        await message.answer("Название не может быть пустым, напиши ещё раз.")
        return
    if "|" in raw:
        title, description = (part.strip() for part in raw.split("|", 1))
        description = description or None
    else:
        title, description = raw, None

    if not title:
        await message.answer("Название не может быть пустым, напиши ещё раз.")
        return
    if len(title) > MAX_TITLE:
        await message.answer(
            f"Слишком длинное название 🙈 Максимум {MAX_TITLE} символов. Сократи."
        )
        return
    if description and len(description) > MAX_DESCRIPTION:
        await message.answer(
            f"Слишком длинное описание 🙈 Максимум {MAX_DESCRIPTION} символов. Сократи."
        )
        return

    await state.update_data(title=title, description=description)
    await state.set_state(EveryNStates.waiting_time_start)
    await message.answer(
        "Во сколько должна начинаться задача? Напиши время (например <code>09:00</code>) "
        "или нажми «Без конкретного времени».",
        reply_markup=skip_keyboard("en_skip_start", "Без конкретного времени"),
    )


@router.message(
    StateFilter(EveryNStates.waiting_time_start),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_time_start(message: Message, state: FSMContext) -> None:
    raw = message.text or ""
    if is_skip_time_phrase(raw):
        await state.update_data(time_start=None)
        await _ask_time_end(message, state)
        return

    parsed = parse_time(raw)
    if parsed is None:
        await message.answer(
            "Не понял время 🙈 Напиши в формате ЧЧ:ММ (например <code>09:00</code>) "
            "или нажми кнопку «Без конкретного времени»."
        )
        return

    await state.update_data(time_start=parsed)
    await _ask_time_end(message, state)


@router.callback_query(
    StateFilter(EveryNStates.waiting_time_start), F.data == "en_skip_start"
)
async def skip_time_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time_start=None)
    await callback.answer()
    if callback.message:
        await _ask_time_end(callback.message, state)


async def _ask_time_end(message: Message, state: FSMContext) -> None:
    await state.set_state(EveryNStates.waiting_time_end)
    await message.answer(
        "Во сколько окончание? Если не знаешь — нажми кнопку или напиши «без окончания».",
        reply_markup=skip_keyboard("en_skip_end", "Без окончания"),
    )


@router.message(
    StateFilter(EveryNStates.waiting_time_end),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_time_end(message: Message, state: FSMContext) -> None:
    raw = message.text or ""
    if is_skip_time_phrase(raw):
        await state.update_data(time_end=None)
        await _ask_repeat_type(message, state)
        return

    parsed = parse_time(raw)
    if parsed is None:
        await message.answer(
            "Не понял время окончания 🙈 Напиши в формате ЧЧ:ММ "
            "или нажми кнопку «Без окончания»."
        )
        return

    await state.update_data(time_end=parsed)
    await _ask_repeat_type(message, state)


@router.callback_query(
    StateFilter(EveryNStates.waiting_time_end), F.data == "en_skip_end"
)
async def skip_time_end(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time_end=None)
    await callback.answer()
    if callback.message:
        await _ask_repeat_type(callback.message, state)


async def _ask_repeat_type(message: Message, state: FSMContext) -> None:
    await state.set_state(EveryNStates.waiting_repeat_type)
    await message.answer(
        "Как часто повторять задачу?\n\n"
        "Можешь нажать одну из кнопок ниже, либо просто написать, например:\n"
        "— «каждый день»\n"
        "— «каждые 3 дня»\n"
        "— «по понедельникам и средам»\n"
        "— «каждый месяц 15 числа»\n"
        "— «каждый год 1 января»",
        reply_markup=every_n_type_keyboard(),
    )


@router.message(
    StateFilter(EveryNStates.waiting_repeat_type),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_repeat_text(message: Message, state: FSMContext) -> None:
    result = parse_repeat_phrase(message.text or "")
    if result is None:
        await message.answer(
            "Не понял периодичность 🙈 Попробуй написать иначе или воспользуйся кнопками выше."
        )
        return

    if result.is_complete() and result.rule_value is not None:
        await _ask_start_date(message, state, result.rule_type, result.rule_value)
        return

    if result.rule_type == "monthly":
        await state.set_state(EveryNStates.waiting_monthly_value)
        await message.answer("Какого числа каждый месяц? Напиши число от 1 до 31.")
    elif result.rule_type == "yearly":
        await state.set_state(EveryNStates.waiting_yearly_value)
        await message.answer(
            "Какого числа и месяца каждый год? Например: <code>1 января</code> или <code>01.01</code>."
        )


@router.callback_query(
    StateFilter(EveryNStates.waiting_repeat_type), F.data.startswith("everyn_type:")
)
async def process_repeat_button(
    callback: CallbackQuery, state: FSMContext
) -> None:
    _, rtype = (callback.data or "").split(":", 1)
    await callback.answer()
    if not callback.message:
        return

    if rtype == "daily":
        await _ask_start_date(callback.message, state, "interval", "1")
    elif rtype == "interval":
        await state.set_state(EveryNStates.waiting_interval_value)
        await callback.message.answer(
            "Через сколько дней повторять? Напиши число, например <code>3</code>.",
            reply_markup=cancel_inline_keyboard(),
        )
    elif rtype == "weekday":
        await state.update_data(selected_weekdays=[])
        await state.set_state(EveryNStates.waiting_weekday_select)
        await callback.message.answer(
            "Выбери дни недели (можно несколько), потом нажми «Готово»:",
            reply_markup=weekday_multiselect_keyboard(set()),
        )
    elif rtype == "monthly":
        await state.set_state(EveryNStates.waiting_monthly_value)
        await callback.message.answer(
            "Какого числа каждый месяц? Напиши число от 1 до 31.",
            reply_markup=cancel_inline_keyboard(),
        )
    elif rtype == "yearly":
        await state.set_state(EveryNStates.waiting_yearly_value)
        await callback.message.answer(
            "Какого числа и месяца каждый год? Например: <code>1 января</code> или <code>01.01</code>.",
            reply_markup=cancel_inline_keyboard(),
        )


@router.message(
    StateFilter(EveryNStates.waiting_interval_value),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_interval_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 365):
        await message.answer(
            "Нужно целое число дней от 1 до 365, например <code>3</code>. Попробуй ещё раз."
        )
        return
    await _ask_start_date(message, state, "interval", text)


@router.callback_query(
    StateFilter(EveryNStates.waiting_weekday_select), F.data.startswith("wd_toggle:")
)
async def toggle_weekday(callback: CallbackQuery, state: FSMContext) -> None:
    _, idx_str = (callback.data or "").split(":", 1)
    idx = int(idx_str)
    data = await state.get_data()
    selected = set(data.get("selected_weekdays", []))
    if idx in selected:
        selected.discard(idx)
    else:
        selected.add(idx)
    await state.update_data(selected_weekdays=list(selected))
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=weekday_multiselect_keyboard(selected)
        )
    await callback.answer()


@router.callback_query(
    StateFilter(EveryNStates.waiting_weekday_select), F.data == "wd_done"
)
async def finish_weekday_select(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = sorted(set(data.get("selected_weekdays", [])))
    await callback.answer()
    if not callback.message:
        return
    if not selected:
        await callback.message.answer("Выбери хотя бы один день недели.")
        return
    value = ",".join(str(i) for i in selected)
    await _ask_start_date(callback.message, state, "weekday", value)


@router.message(
    StateFilter(EveryNStates.waiting_monthly_value),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_monthly_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 31):
        await message.answer("Напиши число от 1 до 31.")
        return
    await _ask_start_date(message, state, "monthly", text)


@router.message(
    StateFilter(EveryNStates.waiting_yearly_value),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_yearly_value(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    parsed = parse_day_month(message.text or "")
    if parsed is None:
        await message.answer(
            "Не понял дату. Напиши, например: <code>1 января</code> или <code>29.02</code>."
        )
        return
    day, month = parsed
    await _ask_start_date(message, state, "yearly", f"{day}-{month}")


async def _ask_start_date(
    message: Message, state: FSMContext, rule_type: str, rule_value: str
) -> None:
    await state.update_data(rule_type=rule_type, rule_value=rule_value)
    await state.set_state(EveryNStates.waiting_start_date)
    await message.answer(
        f"🔁 Периодичность: <b>{html.escape(describe_rule(rule_type, rule_value))}</b>.\n\n"
        "С какой даты начать повторять задачу? Напиши дату или нажми «Сегодня».",
        reply_markup=skip_keyboard("en_start_today", "Сегодня"),
    )


@router.message(
    StateFilter(EveryNStates.waiting_start_date),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_start_date(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    parsed = parse_natural_date(message.text or "", today=today_for_user(db))
    if parsed is None:
        await message.answer(
            "Не понял дату, попробуй ещё раз, например <code>19.10</code> или «завтра»."
        )
        return
    await _ask_reminder_or_save(message, state, db, parsed)


@router.callback_query(
    StateFilter(EveryNStates.waiting_start_date), F.data == "en_start_today"
)
async def start_date_today(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await callback.answer()
    if callback.message:
        await _ask_reminder_or_save(
            callback.message, state, db, today_for_user(db)
        )


async def _ask_reminder_or_save(
    message: Message, state: FSMContext, db: UserDB, start_date: date
) -> None:
    await state.update_data(start_date=start_date.isoformat())
    data = await state.get_data()
    if not data.get("time_start"):
        await _save_rule(message, state, db, reminder_minutes=None)
        return

    await state.set_state(EveryNStates.waiting_reminder)
    await message.answer(
        "За сколько времени до начала задачи напомнить? Выбери вариант или "
        "напиши свой, например «за 45 минут»:",
        reply_markup=reminder_choice_keyboard("en_rem"),
    )


@router.message(
    StateFilter(EveryNStates.waiting_reminder),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_reminder_text(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    minutes = parse_reminder_offset(message.text or "")
    if minutes is None:
        await message.answer(
            "Не понял 🙈 Напиши, например «30 минут», «1 час», «2 часа» "
            "или нажми одну из кнопок выше."
        )
        return
    await _save_rule(message, state, db, reminder_minutes=minutes)


@router.callback_query(
    StateFilter(EveryNStates.waiting_reminder), F.data.startswith("en_rem:")
)
async def process_reminder_button(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    _, value = (callback.data or "").split(":", 1)
    minutes = 0 if value == "off" else int(value)
    await callback.answer()
    if callback.message:
        await _save_rule(callback.message, state, db, reminder_minutes=minutes)


async def _save_rule(
    message: Message, state: FSMContext, db: UserDB, reminder_minutes: int | None
) -> None:
    data = await state.get_data()
    title = data["title"]
    description = data.get("description")
    time_start = data.get("time_start")
    time_end = data.get("time_end")
    rule_type = data["rule_type"]
    rule_value = data["rule_value"]
    start_date = date.fromisoformat(data["start_date"])

    add_recurring_rule(
        db,
        title,
        description,
        time_start,
        time_end,
        start_date,
        rule_type,
        rule_value,
        reminder_minutes,
    )
    await state.clear()

    time_label = time_start or "без времени"
    if time_start and time_end:
        time_label = f"{time_start}-{time_end}"

    await message.answer(
        "Готово! ✅ Повторяющаяся задача добавлена:\n\n"
        f"📝 <b>{esc(title, MAX_TITLE)}</b>\n"
        f"💬 {esc(description, MAX_DESCRIPTION) if description else 'Описание отсутствует'}\n"
        f"🕐 {html.escape(time_label)}\n"
        f"🔁 {html.escape(describe_rule(rule_type, rule_value))}\n"
        f"📅 Начиная с {format_date_full_ru(start_date)} ({weekday_name(start_date)})\n"
        f"{describe_reminder(reminder_minutes)}"
        + (
            "\n\nℹ️ В коротких месяцах задача будет в последний день."
            if rule_type == "monthly" and int(rule_value) > 28
            else ""
        )
        + "\n\n"
        "Посмотреть планы можно кнопкой «📅 Мои планы» или «📋 Дни с задачами».",
        reply_markup=main_reply_keyboard(),
    )
