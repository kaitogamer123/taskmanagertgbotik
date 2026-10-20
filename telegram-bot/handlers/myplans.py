from __future__ import annotations

from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.plans_repo import get_plans_for_date
from keyboards.inline import back_to_day_keyboard, day_plans_keyboard, week_days_keyboard
from utils.date_utils import format_date_full_ru, parse_natural_date, weekday_name

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


@router.callback_query(F.data.startswith("view:"))
async def on_view_item(callback: CallbackQuery, db: UserDB) -> None:
    _, kind, source_id, iso_date = callback.data.split(":", 3)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)

    target = None
    target_index = None
    for idx, item in enumerate(items):
        if item.kind == kind and str(item.source_id) == source_id:
            target = item
            target_index = idx
            break

    if target is None:
        await callback.answer("Эта задача уже не найдена 🤔", show_alert=True)
        return

    description = target.description or "Описание отсутствует"

    reminder = ""
    if target_index is not None and target_index > 0:
        prev_item = items[target_index - 1]
        reminder = f'Успей закончить "{prev_item.title}"!!\n\n'

    text = (
        f"{reminder}"
        f"*{target.title}*\n"
        f"{target.time_label()}\n\n"
        f"Описание: {description}"
    )

    await callback.message.edit_text(
        text, reply_markup=back_to_day_keyboard(d), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("addto:"))
async def on_add_to_day(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.newplan import start_new_plan_with_date

    _, iso_date = callback.data.split(":", 1)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    await start_new_plan_with_date(callback.message, state, d)
    await callback.answer()


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
            "/MyPlans, /NewPlan, /everyN, /database"
        )
        return

    await show_day_plans(message, db, parsed)
