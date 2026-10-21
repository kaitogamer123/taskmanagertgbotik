from __future__ import annotations

from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.plans_repo import (
    get_plans_for_date,
    update_plan_reminder,
    update_rule_reminder,
)
from keyboards.inline import (
    day_plans_keyboard,
    item_detail_keyboard,
    reminder_choice_keyboard,
    week_days_keyboard,
)
from states import ReminderEditStates
from utils.date_utils import format_date_full_ru, parse_natural_date, weekday_name
from utils.reminder_utils import describe_reminder, parse_reminder_offset

router = Router(name="myplans")

WEEK_INTRO = (
    "Привет, вот твои планы на ближайшую неделю :)\n"
    "(Если хочешь выбрать другой день, просто напиши дату и я открою этот день)"
)


def build_day_text(d: date, items: list) -> str:
    header = f"На {format_date_full_ru(d)}, *{weekday_name(d)}*."
    if not items:
        return f"{header}\nНа этот день планов пока нет 🙂\nМожешь добавить задачу кнопкой ниже."
    return f"{header} У тебя будут такие планы:"


@router.message(Command("MyPlans", "myplans"))
async def cmd_myplans(message: Message) -> None:
    today = date.today()
    await message.answer(WEEK_INTRO, reply_markup=week_days_keyboard(today))


@router.callback_query(F.data.startswith("day:"))
async def on_day_selected(callback: CallbackQuery, db: UserDB) -> None:
    _, iso_date = callback.data.split(":", 1)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)
    text = build_day_text(d, items)
    await callback.message.edit_text(
        text, reply_markup=day_plans_keyboard(d, items), parse_mode="Markdown"
    )
    await callback.answer()


async def show_day_plans(message: Message, db: UserDB, d: date) -> None:
    items = get_plans_for_date(db, d)
    text = build_day_text(d, items)
    await message.answer(
        text, reply_markup=day_plans_keyboard(d, items), parse_mode="Markdown"
    )


def _find_item(items: list, kind: str, source_id: str):
    for idx, item in enumerate(items):
        if item.kind == kind and str(item.source_id) == source_id:
            return idx, item
    return None, None


def _item_detail_text(target, reminder: str) -> str:
    description = target.description or "Описание отсутствует"
    return (
        f"*{target.title}*\n"
        f"{target.time_label()}\n\n"
        f"Описание: {description}\n\n"
        f"{reminder}"
    )


@router.callback_query(F.data.startswith("view:"))
async def on_view_item(callback: CallbackQuery, db: UserDB) -> None:
    _, kind, source_id, iso_date = callback.data.split(":", 3)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)

    target_index, target = _find_item(items, kind, source_id)

    if target is None:
        await callback.answer("Эта задача уже не найдена 🤔", show_alert=True)
        return

    reminder_note = ""
    if target_index is not None and target_index > 0:
        prev_item = items[target_index - 1]
        reminder_note = f'Успей закончить "{prev_item.title}"!!\n\n'

    text = (
        f"{reminder_note}"
        f"{_item_detail_text(target, describe_reminder(target.reminder_minutes))}"
    )

    await callback.message.edit_text(
        text, reply_markup=item_detail_keyboard(d, target), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("addto:"))
async def on_add_to_day(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.newplan import start_new_plan_with_date

    _, iso_date = callback.data.split(":", 1)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    await start_new_plan_with_date(callback.message, state, d)
    await callback.answer()


@router.callback_query(F.data.startswith("remind_edit:"))
async def on_remind_edit(callback: CallbackQuery, state: FSMContext, db: UserDB) -> None:
    _, kind, source_id, iso_date = callback.data.split(":", 3)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)
    _, target = _find_item(items, kind, source_id)

    if target is None:
        await callback.answer("Эта задача уже не найдена 🤔", show_alert=True)
        return

    if not target.time_start:
        await callback.answer(
            "У этой задачи нет точного времени начала, поэтому напоминание "
            "поставить не получится.",
            show_alert=True,
        )
        return

    await state.set_state(ReminderEditStates.waiting_value)
    await state.update_data(kind=kind, source_id=source_id, iso_date=iso_date)
    await callback.answer()
    await callback.message.answer(
        f'За сколько времени напоминать о задаче "{target.title}"? '
        "Выбери вариант или напиши свой, например «за 45 минут»:",
        reply_markup=reminder_choice_keyboard("redit_rem"),
    )


async def _apply_reminder_change(
    message: Message, state: FSMContext, db: UserDB, minutes: int
) -> None:
    data = await state.get_data()
    kind = data["kind"]
    source_id = int(data["source_id"])
    iso_date = data["iso_date"]
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()

    if kind == "plan":
        update_plan_reminder(db, source_id, minutes)
    else:
        update_rule_reminder(db, source_id, minutes)

    await state.clear()

    items = get_plans_for_date(db, d)
    _, target = _find_item(items, kind, str(source_id))
    if target is None:
        await message.answer("Напоминание обновлено ✅")
        return

    await message.answer(
        f"Готово ✅ {describe_reminder(minutes)}.\n\n"
        f"{_item_detail_text(target, describe_reminder(target.reminder_minutes))}",
        reply_markup=item_detail_keyboard(d, target),
        parse_mode="Markdown",
    )


@router.message(StateFilter(ReminderEditStates.waiting_value))
async def process_reminder_edit_text(message: Message, state: FSMContext, db: UserDB) -> None:
    minutes = parse_reminder_offset(message.text or "")
    if minutes is None:
        await message.answer(
            "Не понял 🙈 Напиши, например «30 минут», «1 час», «2 часа» "
            "или нажми одну из кнопок выше."
        )
        return
    await _apply_reminder_change(message, state, db, minutes)


@router.callback_query(StateFilter(ReminderEditStates.waiting_value), F.data.startswith("redit_rem:"))
async def process_reminder_edit_button(callback: CallbackQuery, state: FSMContext, db: UserDB) -> None:
    _, value = callback.data.split(":", 1)
    minutes = 0 if value == "off" else int(value)
    await callback.answer()
    await _apply_reminder_change(callback.message, state, db, minutes)


@router.message(StateFilter(None))
async def on_plain_date_text(message: Message, db: UserDB) -> None:
    """
    Если пользователь вне любого сценария просто написал дату
    (19.10, «в четверг», «через 3 дня» и т.п.) — показываем планы на этот день.
    Если текст не похож на дату — просто подсказываем доступные команды.
    """
    if not message.text or message.text.startswith("/"):
        return

    parsed = parse_natural_date(message.text)
    if parsed is None:
        await message.answer(
            "Не понял 🙈 Если хочешь посмотреть планы на день — напиши дату "
            "(например 19.10 или «в четверг»). Доступные команды: "
            "/MyPlans, /NewPlan, /everyN, /notify, /database"
        )
        return

    await show_day_plans(message, db, parsed)
