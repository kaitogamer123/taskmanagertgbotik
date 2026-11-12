"""
Просмотр планов по дням, сводка всех дней с задачами («📋 Дни с задачами»),
редактирование напоминаний и удаление задач (разовых, повторяющихся и за весь день).
"""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from database.db_manager import UserDB
from database.plans_repo import (
    PlanItem,
    delete_all_for_date,
    delete_plan,
    delete_rule,
    exclude_rule_date,
    get_plans_for_date,
    get_rule_row,
    get_scheduled_days,
    update_plan_reminder,
    update_rule_reminder,
)
from keyboards.inline import (
    all_days_keyboard,
    day_delete_keyboard,
    day_plans_keyboard,
    global_delete_menu_keyboard,
    item_detail_keyboard,
    recur_delete_confirm_keyboard,
    reminder_choice_keyboard,
    week_days_keyboard,
)
from keyboards.reply import (
    BTN_ALL_DAYS,
    BTN_DELETE_TASK,
    BTN_MY_PLANS,
    MAIN_MENU_BUTTONS,
)
from states import ReminderEditStates
from utils.clock import today_for_user
from utils.date_utils import (
    format_date_full_ru,
    parse_natural_date,
    weekday_name,
)
from utils.reminder_utils import describe_reminder, parse_reminder_offset
from utils.repeat_parser import describe_rule

router = Router(name="myplans")

WEEK_INTRO = (
    "Привет, вот твои планы на ближайшую неделю :)\n"
    "<i>(Также можешь просто написать любую дату сообщением — и я сразу открою этот день)</i>"
)


async def _safe_edit(
    message: Message | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            await message.answer(text, reply_markup=reply_markup)


def build_day_text(d: date, items: list[PlanItem]) -> str:
    header = f"📅 На <b>{format_date_full_ru(d)}, {weekday_name(d)}</b>:"
    if not items:
        return (
            f"{header}\n\n"
            "На этот день планов пока нет 🙂\n"
            "Можешь добавить задачу кнопкой ниже."
        )
    return f"{header}\nУ тебя запланированы такие задачи:"


def _day_badge(d: date, today: date) -> str:
    if d == today:
        return " (сегодня)"
    if d == today + timedelta(days=1):
        return " (завтра)"
    if d < today:
        return " (прошедший день)"
    return ""


def build_all_days_view(
    db: UserDB, page: int = 0, page_size: int = 10
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Формирует текст и клавиатуру для кнопки «В какие дни есть задачи»."""
    today = today_for_user(db)
    days_list, rules = get_scheduled_days(db, today)

    if not days_list and not rules:
        return (
            "📭 <b>Сейчас у тебя нет ни одной запланированной задачи.</b>\n\n"
            "Добавить новую задачу можно кнопкой <b>«➕ Новая задача»</b> "
            "(или командой /NewPlan), а повторяющуюся — <b>«🔁 Повторяющаяся»</b> (/everyN).",
            None,
        )

    lines: list[str] = ["📋 <b>Дни, в которые у тебя есть задачи:</b>\n"]

    total_days = len(days_list)
    max_pages = max(1, (total_days + page_size - 1) // page_size)
    page = max(0, min(page, max_pages - 1))
    slice_days = days_list[page * page_size : (page + 1) * page_size]

    for d, items in slice_days:
        badge = _day_badge(d, today)
        lines.append(
            f"📅 <b>{format_date_full_ru(d)}, {weekday_name(d)}{badge}</b> "
            f"— задач: {len(items)}"
        )
        for item in items:
            prefix = "🔁" if item.kind == "recur" else "•"
            lines.append(
                f"   {prefix} {html.escape(item.time_label())} — "
                f"{html.escape(item.title)}"
            )
        lines.append("")

    if max_pages > 1:
        lines.append(f"<i>Страница {page + 1} из {max_pages}</i>\n")

    if rules:
        lines.append("🔁 <b>Повторяющиеся задачи:</b>")
        for r in rules:
            t_lbl = r["time_start"] or "Без времени"
            if r["time_start"] and r["time_end"]:
                t_lbl = f"{r['time_start']}-{r['time_end']}"
            lines.append(
                f"   • {html.escape(t_lbl)} — <b>{html.escape(r['title'])}</b> "
                f"({html.escape(describe_rule(r['rule_type'], r['rule_value']))})"
            )
        lines.append("")

    lines.append("👇 Нажми на нужный день ниже, чтобы открыть его или удалить задачи:")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3980] + "\n…"

    kb = all_days_keyboard(days_list, today=today, page=page, page_size=page_size)
    return text, kb


def build_delete_menu_view(
    db: UserDB, page: int = 0
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Формирует общее меню удаления задач."""
    today = today_for_user(db)
    days_list, rules = get_scheduled_days(db, today)
    if not days_list and not rules:
        return (
            "📭 <b>Удалять пока нечего — активных задач нет!</b>",
            None,
        )

    text = (
        "🗑 <b>Удаление задач</b>\n\n"
        "Выбери день, в котором нужно удалить задачу (или удали повторяющееся правило целиком):"
    )
    return text, global_delete_menu_keyboard(days_list, rules, today=today, page=page)


# ─── /MyPlans, «Дни с задачами» и общее «Удалить задачу» ─────────────────────


@router.message(Command("MyPlans", "myplans", ignore_case=True))
@router.message(F.text == BTN_MY_PLANS)
async def cmd_myplans(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    today = today_for_user(db)
    await message.answer(WEEK_INTRO, reply_markup=week_days_keyboard(today, db=db))


@router.callback_query(F.data == "week_menu")
async def cb_week_menu(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    today = today_for_user(db)
    await callback.answer()
    await _safe_edit(
        callback.message, WEEK_INTRO, reply_markup=week_days_keyboard(today, db=db)
    )


@router.message(Command("alldays", "days", ignore_case=True))
@router.message(F.text == BTN_ALL_DAYS)
async def cmd_all_days(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    text, kb = build_all_days_view(db, page=0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("all_days:"))
async def cb_all_days(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    _, page_str = (callback.data or "").split(":", 1)
    page = int(page_str) if page_str.isdigit() else 0
    text, kb = build_all_days_view(db, page=page)
    await callback.answer()
    await _safe_edit(callback.message, text, reply_markup=kb)


@router.message(Command("delete", ignore_case=True))
@router.message(F.text == BTN_DELETE_TASK)
async def cmd_delete_menu(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    text, kb = build_delete_menu_view(db, page=0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "del_menu")
async def cb_delete_menu(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    text, kb = build_delete_menu_view(db, page=0)
    await callback.answer()
    await _safe_edit(callback.message, text, reply_markup=kb)


@router.callback_query(F.data.startswith("del_page:"))
async def cb_delete_page(callback: CallbackQuery, db: UserDB) -> None:
    _, page_str = (callback.data or "").split(":", 1)
    page = int(page_str) if page_str.isdigit() else 0
    text, kb = build_delete_menu_view(db, page=page)
    await callback.answer()
    await _safe_edit(callback.message, text, reply_markup=kb)


# ─── Просмотр конкретного дня и карточки задачи ───────────────────────────────


@router.callback_query(F.data.startswith("day:"))
async def on_day_selected(callback: CallbackQuery, db: UserDB) -> None:
    _, iso_date = (callback.data or "").split(":", 1)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)
    text = build_day_text(d, items)
    await callback.answer()
    await _safe_edit(
        callback.message, text, reply_markup=day_plans_keyboard(d, items)
    )


async def show_day_plans(message: Message, db: UserDB, d: date) -> None:
    items = get_plans_for_date(db, d)
    text = build_day_text(d, items)
    await message.answer(text, reply_markup=day_plans_keyboard(d, items))


def _find_item(items: list[PlanItem], kind: str, source_id: str):
    for idx, item in enumerate(items):
        if item.kind == kind and str(item.source_id) == source_id:
            return idx, item
    return None, None


def _item_detail_text(target: PlanItem, reminder: str) -> str:
    description = (
        html.escape(target.description)
        if target.description
        else "Описание отсутствует"
    )
    recur_line = ""
    if target.kind == "recur" and target.rule_type and target.rule_value:
        recur_line = (
            f"\n🔁 Повторение: {html.escape(describe_rule(target.rule_type, target.rule_value))}"
        )
    return (
        f"<b>{html.escape(target.title)}</b>\n"
        f"🕐 {html.escape(target.time_label())}{recur_line}\n\n"
        f"💬 Описание: {description}\n\n"
        f"{reminder}"
    )


@router.callback_query(F.data.startswith("view:"))
async def on_view_item(callback: CallbackQuery, db: UserDB) -> None:
    _, kind, source_id, iso_date = (callback.data or "").split(":", 3)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)

    target_index, target = _find_item(items, kind, source_id)
    if target is None:
        await callback.answer("Эта задача уже удалена или не найдена 🤔", show_alert=True)
        await _safe_edit(
            callback.message,
            build_day_text(d, items),
            reply_markup=day_plans_keyboard(d, items),
        )
        return

    reminder_note = ""
    if target_index is not None and target_index > 0:
        prev_item = items[target_index - 1]
        reminder_note = f'⚠️ Успей закончить «{html.escape(prev_item.title)}»!!\n\n'

    text = (
        f"{reminder_note}"
        f"{_item_detail_text(target, describe_reminder(target.reminder_minutes))}"
    )

    await callback.answer()
    await _safe_edit(
        callback.message, text, reply_markup=item_detail_keyboard(d, target)
    )


# ─── Удаление задач (из карточки задачи, из дня и из общего меню удаления) ───


@router.callback_query(F.data.startswith("del_day_menu:"))
async def on_day_delete_menu(callback: CallbackQuery, db: UserDB) -> None:
    _, iso_date = (callback.data or "").split(":", 1)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)
    if not items:
        await callback.answer("На этот день уже нет задач 🙂", show_alert=True)
        await _safe_edit(
            callback.message,
            build_day_text(d, items),
            reply_markup=day_plans_keyboard(d, items),
        )
        return

    text = (
        f"🗑 <b>Удаление задач на {format_date_full_ru(d)} ({weekday_name(d)})</b>\n\n"
        "Нажми на задачу ниже, чтобы удалить её:"
    )
    await callback.answer()
    await _safe_edit(
        callback.message, text, reply_markup=day_delete_keyboard(d, items)
    )


@router.callback_query(F.data.startswith("del_item:"))
async def on_delete_item(callback: CallbackQuery, db: UserDB) -> None:
    _, kind, source_id_str, iso_date = (callback.data or "").split(":", 3)
    source_id = int(source_id_str)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()

    if kind == "plan":
        delete_plan(db, source_id)
        await callback.answer("🗑 Задача удалена!")
        items = get_plans_for_date(db, d)
        await _safe_edit(
            callback.message,
            f"✅ Задача удалена!\n\n{build_day_text(d, items)}",
            reply_markup=day_plans_keyboard(d, items),
        )
        return

    # Повторяющаяся задача — предлагаем удалить только на этот день или навсегда
    rule = get_rule_row(db, source_id)
    if rule is None:
        await callback.answer("Задача уже удалена", show_alert=True)
        items = get_plans_for_date(db, d)
        await _safe_edit(
            callback.message,
            build_day_text(d, items),
            reply_markup=day_plans_keyboard(d, items),
        )
        return

    await callback.answer()
    await _safe_edit(
        callback.message,
        f"🔁 Задача <b>«{html.escape(rule['title'])}»</b> является повторяющейся "
        f"({html.escape(describe_rule(rule['rule_type'], rule['rule_value']))}).\n\n"
        "Как именно её удалить?",
        reply_markup=recur_delete_confirm_keyboard(d, source_id),
    )


@router.callback_query(F.data.startswith("del_skip:"))
async def on_delete_recur_single_date(
    callback: CallbackQuery, db: UserDB
) -> None:
    _, rule_id_str, iso_date = (callback.data or "").split(":", 2)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    exclude_rule_date(db, int(rule_id_str), d)
    await callback.answer("🗑 Удалено на выбранный день!")
    items = get_plans_for_date(db, d)
    await _safe_edit(
        callback.message,
        f"✅ Повторяющаяся задача скрыта на {format_date_full_ru(d)}!\n\n"
        f"{build_day_text(d, items)}",
        reply_markup=day_plans_keyboard(d, items),
    )


@router.callback_query(F.data.startswith("del_rule_full:"))
async def on_delete_recur_everywhere(
    callback: CallbackQuery, db: UserDB
) -> None:
    _, rule_id_str, iso_date = (callback.data or "").split(":", 2)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    delete_rule(db, int(rule_id_str))
    await callback.answer("🗑 Повторяющаяся задача полностью удалена!")
    items = get_plans_for_date(db, d)
    await _safe_edit(
        callback.message,
        f"✅ Повторяющаяся задача удалена навсегда!\n\n{build_day_text(d, items)}",
        reply_markup=day_plans_keyboard(d, items),
    )


@router.callback_query(F.data.startswith("del_rule_now:"))
async def on_delete_rule_from_global_menu(
    callback: CallbackQuery, db: UserDB
) -> None:
    _, rule_id_str = (callback.data or "").split(":", 1)
    delete_rule(db, int(rule_id_str))
    await callback.answer("🗑 Повторяющаяся задача удалена!")
    text, kb = build_delete_menu_view(db, page=0)
    await _safe_edit(callback.message, text, reply_markup=kb)


@router.callback_query(F.data.startswith("del_day_all:"))
async def on_delete_all_day(callback: CallbackQuery, db: UserDB) -> None:
    _, iso_date = (callback.data or "").split(":", 1)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    removed = delete_all_for_date(db, d)
    await callback.answer(f"🗑 Удалено задач: {removed}")
    items = get_plans_for_date(db, d)
    await _safe_edit(
        callback.message,
        f"✅ Все задачи за {format_date_full_ru(d)} удалены ({removed} шт.)!\n\n"
        f"{build_day_text(d, items)}",
        reply_markup=day_plans_keyboard(d, items),
    )


# ─── Добавление задачи в день и изменение напоминания ────────────────────────


@router.callback_query(F.data.startswith("addto:"))
async def on_add_to_day(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.newplan import start_new_plan_with_date

    _, iso_date = (callback.data or "").split(":", 1)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    await callback.answer()
    if callback.message:
        await start_new_plan_with_date(callback.message, state, d)


@router.callback_query(F.data.startswith("remind_edit:"))
async def on_remind_edit(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    _, kind, source_id, iso_date = (callback.data or "").split(":", 3)
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
    if callback.message:
        await callback.message.answer(
            f'За сколько времени напоминать о задаче «<b>{html.escape(target.title)}</b>»?\n'
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
    )


@router.message(
    StateFilter(ReminderEditStates.waiting_value),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_reminder_edit_text(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    minutes = parse_reminder_offset(message.text or "")
    if minutes is None:
        await message.answer(
            "Не понял 🙈 Напиши, например «30 минут», «1 час», «2 часа» "
            "или нажми одну из кнопок выше."
        )
        return
    await _apply_reminder_change(message, state, db, minutes)


@router.callback_query(
    StateFilter(ReminderEditStates.waiting_value), F.data.startswith("redit_rem:")
)
async def process_reminder_edit_button(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    _, value = (callback.data or "").split(":", 1)
    minutes = 0 if value == "off" else int(value)
    await callback.answer()
    if callback.message:
        await _apply_reminder_change(callback.message, state, db, minutes)


# ─── Универсальный обработчик произвольной даты в тексте ─────────────────────


@router.message(StateFilter(None))
async def on_plain_date_text(message: Message, db: UserDB) -> None:
    if not message.text or message.text.startswith("/"):
        return

    parsed = parse_natural_date(message.text, today=today_for_user(db))
    if parsed is None:
        await message.answer(
            "Не понял 🙈 Если хочешь посмотреть планы на конкретный день — напиши дату "
            "(например <code>19.10</code> или «в четверг»), либо воспользуйся кнопками меню внизу 👇"
        )
        return

    await show_day_plans(message, db, parsed)
