from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.plans_repo import add_recurring_rule
from keyboards.inline import every_n_type_keyboard, skip_keyboard, weekday_multiselect_keyboard
from states import EveryNStates
from utils.date_utils import format_date_full_ru, parse_natural_date, parse_time, weekday_name
from utils.repeat_parser import describe_rule, parse_repeat_phrase

router = Router(name="everyn")


@router.message(Command("everyN", "everyn"))
async def cmd_every_n(message: Message, state: FSMContext) -> None:
    await state.set_state(EveryNStates.waiting_title)
    await message.answer(
        "Добавляем повторяющуюся задачу 🔁\n\n"
        "Напиши название задачи. Если хочешь добавить и описание — "
        "укажи его через вертикальную черту, например:\n"
        "«Пить витамины | Утром после завтрака»"
    )


@router.message(StateFilter(EveryNStates.waiting_title))
async def process_title(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Название не может быть пустым, напиши ещё раз.")
        return
    if "|" in raw:
        title, description = (part.strip() for part in raw.split("|", 1))
        description = description or None
    else:
        title, description = raw, None

    await state.update_data(title=title, description=description)
    await state.set_state(EveryNStates.waiting_time_start)
    await message.answer(
        "Во сколько должна начинаться задача? Напиши время (например 09:00) "
        "или нажми «без времени».",
        reply_markup=skip_keyboard("en_skip_start", "Без конкретного времени"),
    )


@router.message(StateFilter(EveryNStates.waiting_time_start))
async def process_time_start(message: Message, state: FSMContext) -> None:
    await state.update_data(time_start=parse_time(message.text or ""))
    await _ask_time_end(message, state)


@router.callback_query(StateFilter(EveryNStates.waiting_time_start), F.data == "en_skip_start")
async def skip_time_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time_start=None)
    await callback.answer()
    await _ask_time_end(callback.message, state)


async def _ask_time_end(message: Message, state: FSMContext) -> None:
    await state.set_state(EveryNStates.waiting_time_end)
    await message.answer(
        "Во сколько окончание? Если не знаешь — нажми кнопку или напиши «без окончания».",
        reply_markup=skip_keyboard("en_skip_end", "Без окончания"),
    )


@router.message(StateFilter(EveryNStates.waiting_time_end))
async def process_time_end(message: Message, state: FSMContext) -> None:
    await state.update_data(time_end=parse_time(message.text or ""))
    await _ask_repeat_type(message, state)


@router.callback_query(StateFilter(EveryNStates.waiting_time_end), F.data == "en_skip_end")
async def skip_time_end(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time_end=None)
    await callback.answer()
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


@router.message(StateFilter(EveryNStates.waiting_repeat_type))
async def process_repeat_text(message: Message, state: FSMContext) -> None:
    result = parse_repeat_phrase(message.text or "")
    if result is None:
        await message.answer(
            "Не понял периодичность 🙈 Попробуй написать иначе или воспользуйся кнопками выше."
        )
        return

    if result.is_complete():
        await _ask_start_date(message, state, result.rule_type, result.rule_value)
        return

    if result.rule_type == "monthly":
        await state.set_state(EveryNStates.waiting_monthly_value)
        await message.answer("Какого числа каждый месяц? Напиши число от 1 до 31.")
    elif result.rule_type == "yearly":
        await state.set_state(EveryNStates.waiting_yearly_value)
        await message.answer("Какого числа и месяца каждый год? Например: 1 января или 01.01.")


@router.callback_query(StateFilter(EveryNStates.waiting_repeat_type), F.data.startswith("everyn_type:"))
async def process_repeat_button(callback: CallbackQuery, state: FSMContext) -> None:
    _, rtype = callback.data.split(":", 1)
    await callback.answer()

    if rtype == "daily":
        await _ask_start_date(callback.message, state, "interval", "1")
    elif rtype == "interval":
        await state.set_state(EveryNStates.waiting_interval_value)
        await callback.message.answer("Через сколько дней повторять? Напиши число, например 3.")
    elif rtype == "weekday":
        await state.update_data(selected_weekdays=[])
        await state.set_state(EveryNStates.waiting_weekday_select)
        await callback.message.answer(
            "Выбери дни недели (можно несколько), потом нажми «Готово»:",
            reply_markup=weekday_multiselect_keyboard(set()),
        )
    elif rtype == "monthly":
        await state.set_state(EveryNStates.waiting_monthly_value)
        await callback.message.answer("Какого числа каждый месяц? Напиши число от 1 до 31.")
    elif rtype == "yearly":
        await state.set_state(EveryNStates.waiting_yearly_value)
        await callback.message.answer("Какого числа и месяца каждый год? Например: 1 января или 01.01.")


@router.message(StateFilter(EveryNStates.waiting_interval_value))
async def process_interval_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("Нужно целое положительное число дней, например 3. Попробуй ещё раз.")
        return
    await _ask_start_date(message, state, "interval", text)


@router.callback_query(StateFilter(EveryNStates.waiting_weekday_select), F.data.startswith("wd_toggle:"))
async def toggle_weekday(callback: CallbackQuery, state: FSMContext) -> None:
    _, idx_str = callback.data.split(":", 1)
    idx = int(idx_str)
    data = await state.get_data()
    selected = set(data.get("selected_weekdays", []))
    if idx in selected:
        selected.discard(idx)
    else:
        selected.add(idx)
    await state.update_data(selected_weekdays=list(selected))
    await callback.message.edit_reply_markup(reply_markup=weekday_multiselect_keyboard(selected))
    await callback.answer()


@router.callback_query(StateFilter(EveryNStates.waiting_weekday_select), F.data == "wd_done")
async def finish_weekday_select(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = sorted(set(data.get("selected_weekdays", [])))
    await callback.answer()
    if not selected:
        await callback.message.answer("Выбери хотя бы один день недели.")
        return
    value = ",".join(str(i) for i in selected)
    await _ask_start_date(callback.message, state, "weekday", value)


@router.message(StateFilter(EveryNStates.waiting_monthly_value))
async def process_monthly_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 31):
        await message.answer("Напиши число от 1 до 31.")
        return
    await _ask_start_date(message, state, "monthly", text)


@router.message(StateFilter(EveryNStates.waiting_yearly_value))
async def process_yearly_value(message: Message, state: FSMContext) -> None:
    parsed = parse_natural_date(message.text or "")
    if parsed is None:
        await message.answer("Не понял дату. Напиши, например: 1 января или 01.01.")
        return
    await _ask_start_date(message, state, "yearly", f"{parsed.day}-{parsed.month}")


async def _ask_start_date(message: Message, state: FSMContext, rule_type: str, rule_value: str) -> None:
    await state.update_data(rule_type=rule_type, rule_value=rule_value)
    await state.set_state(EveryNStates.waiting_start_date)
    await message.answer(
        f"Периодичность: {describe_rule(rule_type, rule_value)}.\n\n"
        "С какой даты начать повторять задачу? Напиши дату или нажми «Сегодня».",
        reply_markup=skip_keyboard("en_start_today", "Сегодня"),
    )


@router.message(StateFilter(EveryNStates.waiting_start_date))
async def process_start_date(message: Message, state: FSMContext, db: UserDB) -> None:
    parsed = parse_natural_date(message.text or "")
    if parsed is None:
        await message.answer("Не понял дату, попробуй ещё раз, например 19.10 или «завтра».")
        return
    await _save_rule(message, state, db, parsed)


@router.callback_query(StateFilter(EveryNStates.waiting_start_date), F.data == "en_start_today")
async def start_date_today(callback: CallbackQuery, state: FSMContext, db: UserDB) -> None:
    await callback.answer()
    await _save_rule(callback.message, state, db, date.today())


async def _save_rule(message: Message, state: FSMContext, db: UserDB, start_date: date) -> None:
    data = await state.get_data()
    title = data["title"]
    description = data.get("description")
    time_start = data.get("time_start")
    time_end = data.get("time_end")
    rule_type = data["rule_type"]
    rule_value = data["rule_value"]

    add_recurring_rule(
        db, title, description, time_start, time_end, start_date, rule_type, rule_value
    )
    await state.clear()

    time_label = time_start or "без времени"
    if time_start and time_end:
        time_label = f"{time_start}-{time_end}"

    await message.answer(
        "Готово! ✅ Повторяющаяся задача добавлена:\n\n"
        f"📝 {title}\n"
        f"💬 {description or 'Описание отсутствует'}\n"
        f"🕐 {time_label}\n"
        f"🔁 {describe_rule(rule_type, rule_value)}\n"
        f"📅 Начиная с {format_date_full_ru(start_date)} ({weekday_name(start_date)})\n\n"
        "Посмотреть планы можно командой /MyPlans"
    )
