from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.plans_repo import add_plan
from keyboards.inline import reminder_choice_keyboard, skip_keyboard
from states import NewPlanStates
from utils.date_utils import format_date_full_ru, parse_natural_date, parse_time, weekday_name
from utils.reminder_utils import describe_reminder, parse_reminder_offset

router = Router(name="newplan")


@router.message(Command("NewPlan", "newplan"))
async def cmd_new_plan(message: Message, state: FSMContext) -> None:
    await state.set_state(NewPlanStates.waiting_date)
    await message.answer(
        "Добавляем новую задачу 📝\n\n"
        "На какую дату её запланировать? Можно написать:\n"
        "— точную дату: 19.10 или 19.10.2026\n"
        "— день недели: четверг, в субботу\n"
        "— «на следующей неделе в четверг»\n"
        "— сегодня / завтра / послезавтра / через 3 дня"
    )


async def start_new_plan_with_date(message: Message, state: FSMContext, d: date) -> None:
    await state.set_state(NewPlanStates.waiting_time_start)
    await state.update_data(plan_date=d.isoformat())
    await message.answer(
        f"Дата: {format_date_full_ru(d)} ({weekday_name(d)}).\n"
        "Во сколько начало задачи? Напиши время (например 14:00).",
        reply_markup=skip_keyboard("np_skip_start", "Без конкретного времени"),
    )


@router.message(StateFilter(NewPlanStates.waiting_date))
async def process_date(message: Message, state: FSMContext) -> None:
    parsed = parse_natural_date(message.text or "")
    if parsed is None:
        await message.answer(
            "Не смог понять дату 🙈 Попробуй ещё раз, например: 19.10, "
            "«в четверг» или «на следующей неделе в среду»."
        )
        return
    await start_new_plan_with_date(message, state, parsed)


@router.message(StateFilter(NewPlanStates.waiting_time_start))
async def process_time_start(message: Message, state: FSMContext) -> None:
    time_start = parse_time(message.text or "")
    await state.update_data(time_start=time_start)
    await _ask_time_end(message, state)


@router.callback_query(
    StateFilter(NewPlanStates.waiting_time_start), F.data == "np_skip_start"
)
async def skip_time_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time_start=None)
    await callback.answer()
    await _ask_time_end(callback.message, state)


async def _ask_time_end(message: Message, state: FSMContext) -> None:
    await state.set_state(NewPlanStates.waiting_time_end)
    await message.answer(
        "Во сколько окончание? Если не знаешь — нажми кнопку или напиши «без окончания».",
        reply_markup=skip_keyboard("np_skip_end", "Без окончания"),
    )


@router.message(StateFilter(NewPlanStates.waiting_time_end))
async def process_time_end(message: Message, state: FSMContext) -> None:
    time_end = parse_time(message.text or "")
    await state.update_data(time_end=time_end)
    await _ask_title(message, state)


@router.callback_query(
    StateFilter(NewPlanStates.waiting_time_end), F.data == "np_skip_end"
)
async def skip_time_end(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time_end=None)
    await callback.answer()
    await _ask_title(callback.message, state)


async def _ask_title(message: Message, state: FSMContext) -> None:
    await state.set_state(NewPlanStates.waiting_title)
    await message.answer("Как назвать задачу? Напиши короткое название.")


@router.message(StateFilter(NewPlanStates.waiting_title))
async def process_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым, напиши ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(NewPlanStates.waiting_description)
    await message.answer(
        "Хочешь добавить описание задачи? Напиши его, или нажми «без описания».",
        reply_markup=skip_keyboard("np_skip_desc", "Без описания"),
    )


_NO_DESCRIPTION_WORDS = {"нет", "без описания", "-", "пропустить", "не надо", "не знаю"}


@router.message(StateFilter(NewPlanStates.waiting_description))
async def process_description(message: Message, state: FSMContext, db: UserDB) -> None:
    raw = (message.text or "").strip()
    description = None if raw.lower() in _NO_DESCRIPTION_WORDS or not raw else raw
    await state.update_data(description=description)
    await _ask_reminder_or_save(message, state, db)


@router.callback_query(
    StateFilter(NewPlanStates.waiting_description), F.data == "np_skip_desc"
)
async def skip_description(callback: CallbackQuery, state: FSMContext, db: UserDB) -> None:
    await callback.answer()
    await state.update_data(description=None)
    await _ask_reminder_or_save(callback.message, state, db)


async def _ask_reminder_or_save(message: Message, state: FSMContext, db: UserDB) -> None:
    """Если у задачи указано время начала — спрашиваем про напоминание,
    иначе сохраняем сразу (напоминание привязывать не к чему)."""
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


@router.message(StateFilter(NewPlanStates.waiting_reminder))
async def process_reminder_text(message: Message, state: FSMContext, db: UserDB) -> None:
    minutes = parse_reminder_offset(message.text or "")
    if minutes is None:
        await message.answer(
            "Не понял 🙈 Напиши, например «30 минут», «1 час», «2 часа» "
            "или нажми одну из кнопок выше."
        )
        return
    await _save_plan(message, state, db, reminder_minutes=minutes)


@router.callback_query(StateFilter(NewPlanStates.waiting_reminder), F.data.startswith("np_rem:"))
async def process_reminder_button(callback: CallbackQuery, state: FSMContext, db: UserDB) -> None:
    _, value = callback.data.split(":", 1)
    minutes = 0 if value == "off" else int(value)
    await callback.answer()
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

    add_plan(db, plan_date, title, time_start, time_end, description, reminder_minutes)
    await state.clear()

    time_label = time_start or "без времени"
    if time_start and time_end:
        time_label = f"{time_start}-{time_end}"

    await message.answer(
        "Готово! ✅ Задача добавлена:\n\n"
        f"📅 {format_date_full_ru(plan_date)} ({weekday_name(plan_date)})\n"
        f"🕐 {time_label}\n"
        f"📝 {title}\n"
        f"💬 {description or 'Описание отсутствует'}\n"
        f"{describe_reminder(reminder_minutes)}\n\n"
        "Посмотреть все планы на этот день можно командой /MyPlans"
    )
