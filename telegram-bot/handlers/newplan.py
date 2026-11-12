from __future__ import annotations

import html
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.plans_repo import add_plan
from keyboards.inline import (
    cancel_inline_keyboard,
    reminder_choice_keyboard,
    skip_keyboard,
)
from keyboards.reply import BTN_NEW_PLAN, MAIN_MENU_BUTTONS, main_reply_keyboard
from states import NewPlanStates
from utils.clock import today_for_user
from utils.date_utils import (
    format_date_full_ru,
    is_skip_time_phrase,
    parse_natural_date,
    parse_time,
    weekday_name,
)
from utils.reminder_utils import describe_reminder, parse_reminder_offset

router = Router(name="newplan")


@router.message(Command("NewPlan", "newplan", ignore_case=True))
@router.message(F.text == BTN_NEW_PLAN)
async def cmd_new_plan(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewPlanStates.waiting_date)
    await message.answer(
        "Добавляем новую задачу 📝\n\n"
        "На какую дату её запланировать? Можно написать:\n"
        "— точную дату: <code>19.10</code> или <code>19.10.2026</code>\n"
        "— день недели: «четверг», «в субботу»\n"
        "— «на следующей неделе в четверг»\n"
        "— «сегодня» / «завтра» / «послезавтра» / «через 3 дня»",
        reply_markup=cancel_inline_keyboard(),
    )


async def start_new_plan_with_date(
    message: Message, state: FSMContext, d: date
) -> None:
    await state.set_state(NewPlanStates.waiting_time_start)
    await state.update_data(plan_date=d.isoformat())
    await message.answer(
        f"📅 Дата: <b>{format_date_full_ru(d)} ({weekday_name(d)})</b>.\n"
        "Во сколько начало задачи? Напиши время (например <code>14:00</code>).",
        reply_markup=skip_keyboard("np_skip_start", "Без конкретного времени"),
    )


@router.message(
    StateFilter(NewPlanStates.waiting_date),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_date(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    parsed = parse_natural_date(message.text or "", today=today_for_user(db))
    if parsed is None:
        await message.answer(
            "Не смог понять дату 🙈 Попробуй ещё раз, например: <code>19.10</code>, "
            "«в четверг» или «на следующей неделе в среду»."
        )
        return
    await start_new_plan_with_date(message, state, parsed)


@router.message(
    StateFilter(NewPlanStates.waiting_time_start),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_time_start(message: Message, state: FSMContext) -> None:
    raw = message.text or ""
    if is_skip_time_phrase(raw):
        await state.update_data(time_start=None)
        await _ask_time_end(message, state)
        return

    time_start = parse_time(raw)
    if time_start is None:
        await message.answer(
            "Не понял время 🙈 Напиши в формате ЧЧ:ММ (например <code>14:00</code> "
            "или просто <code>14</code>), либо нажми кнопку «Без конкретного времени»."
        )
        return

    await state.update_data(time_start=time_start)
    await _ask_time_end(message, state)


@router.callback_query(
    StateFilter(NewPlanStates.waiting_time_start), F.data == "np_skip_start"
)
async def skip_time_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time_start=None)
    await callback.answer()
    if callback.message:
        await _ask_time_end(callback.message, state)


async def _ask_time_end(message: Message, state: FSMContext) -> None:
    await state.set_state(NewPlanStates.waiting_time_end)
    await message.answer(
        "Во сколько окончание? Если не знаешь — нажми кнопку или напиши «без окончания».",
        reply_markup=skip_keyboard("np_skip_end", "Без окончания"),
    )


@router.message(
    StateFilter(NewPlanStates.waiting_time_end),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_time_end(message: Message, state: FSMContext) -> None:
    raw = message.text or ""
    if is_skip_time_phrase(raw):
        await state.update_data(time_end=None)
        await _ask_title(message, state)
        return

    time_end = parse_time(raw)
    if time_end is None:
        await message.answer(
            "Не понял время окончания 🙈 Напиши в формате ЧЧ:ММ (например <code>15:30</code>) "
            "или нажми кнопку «Без окончания»."
        )
        return

    await state.update_data(time_end=time_end)
    await _ask_title(message, state)


@router.callback_query(
    StateFilter(NewPlanStates.waiting_time_end), F.data == "np_skip_end"
)
async def skip_time_end(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time_end=None)
    await callback.answer()
    if callback.message:
        await _ask_title(callback.message, state)


async def _ask_title(message: Message, state: FSMContext) -> None:
    await state.set_state(NewPlanStates.waiting_title)
    await message.answer(
        "Как назвать задачу? Напиши короткое название.",
        reply_markup=cancel_inline_keyboard(),
    )


@router.message(
    StateFilter(NewPlanStates.waiting_title),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым, напиши ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(NewPlanStates.waiting_description)
    await message.answer(
        "Хочешь добавить описание задачи? Напиши его или нажми «Без описания».",
        reply_markup=skip_keyboard("np_skip_desc", "Без описания"),
    )


_NO_DESCRIPTION_WORDS = {
    "нет",
    "без описания",
    "-",
    "пропустить",
    "не надо",
    "не знаю",
}


@router.message(
    StateFilter(NewPlanStates.waiting_description),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_description(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    raw = (message.text or "").strip()
    description = None if raw.lower() in _NO_DESCRIPTION_WORDS or not raw else raw
    await state.update_data(description=description)
    await _ask_reminder_or_save(message, state, db)


@router.callback_query(
    StateFilter(NewPlanStates.waiting_description), F.data == "np_skip_desc"
)
async def skip_description(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await callback.answer()
    await state.update_data(description=None)
    if callback.message:
        await _ask_reminder_or_save(callback.message, state, db)


async def _ask_reminder_or_save(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    data = await state.get_data()
    if not data.get("time_start"):
        await _save_plan(message, state, db, reminder_minutes=None)
        return

    await state.set_state(NewPlanStates.waiting_reminder)
    await message.answer(
        "За сколько времени до начала задачи напомнить? Выбери вариант или "
        "напиши свой, например «за 45 минут»:",
        reply_markup=reminder_choice_keyboard("np_rem"),
    )


@router.message(
    StateFilter(NewPlanStates.waiting_reminder),
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
    await _save_plan(message, state, db, reminder_minutes=minutes)


@router.callback_query(
    StateFilter(NewPlanStates.waiting_reminder), F.data.startswith("np_rem:")
)
async def process_reminder_button(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    _, value = (callback.data or "").split(":", 1)
    minutes = 0 if value == "off" else int(value)
    await callback.answer()
    if callback.message:
        await _save_plan(callback.message, state, db, reminder_minutes=minutes)


async def _save_plan(
    message: Message, state: FSMContext, db: UserDB, reminder_minutes: int | None
) -> None:
    data = await state.get_data()
    plan_date = date.fromisoformat(data["plan_date"])
    title = data["title"]
    time_start = data.get("time_start")
    time_end = data.get("time_end")
    description = data.get("description")

    add_plan(
        db, plan_date, title, time_start, time_end, description, reminder_minutes
    )
    await state.clear()

    time_label = time_start or "без времени"
    if time_start and time_end:
        time_label = f"{time_start}-{time_end}"

    await message.answer(
        "Готово! ✅ Задача добавлена:\n\n"
        f"📅 {format_date_full_ru(plan_date)} ({weekday_name(plan_date)})\n"
        f"🕐 {html.escape(time_label)}\n"
        f"📝 <b>{html.escape(title)}</b>\n"
        f"💬 {html.escape(description) if description else 'Описание отсутствует'}\n"
        f"{describe_reminder(reminder_minutes)}\n\n"
        "Посмотреть все планы можно кнопкой «📅 Мои планы» или «📋 Дни с задачами».",
        reply_markup=main_reply_keyboard(),
    )
