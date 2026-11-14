"""
Просмотр планов по дням, сводка всех дней с задачами («📋 Дни с задачами»),
редактирование напоминаний и удаление задач (разовых, повторяющихся и за весь день).
"""
from __future__ import annotations

import calendar
import html
from datetime import date, datetime, time as dtime, timedelta, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db_manager import UserDB
from database.plans_repo import (
    PlanItem,
    count_active_plans,
    count_active_rules,
    count_done_plans,
    count_done_rules,
    delete_all_for_date,
    delete_plan,
    delete_rule,
    exclude_rule_date,
    get_plan_row,
    get_plans_for_date,
    get_rule_row,
    get_scheduled_days,
    get_plan_counts_for_dates,
    toggle_plan_done,
    toggle_rule_active,
    toggle_rule_done,
    update_plan,
    update_plan_reminder,
    update_rule,
    update_rule_reminder,
)
from keyboards.inline import (
    all_days_keyboard,
    cancel_inline_keyboard,
    day_delete_keyboard,
    day_plans_keyboard,
    del_day_confirm_keyboard,
    del_plan_confirm_keyboard,
    del_rule_confirm_keyboard,
    edit_item_keyboard,
    global_delete_menu_keyboard,
    item_detail_keyboard,
    recur_delete_confirm_keyboard,
    reminder_choice_keyboard,
    rules_delete_keyboard,
    stats_keyboard,
    week_days_keyboard,
)
from keyboards.reply import (
    BTN_ALL_DAYS,
    BTN_DELETE_TASK,
    BTN_MY_PLANS,
    MAIN_MENU_BUTTONS,
)
from states import PlanEditStates, ReminderEditStates
from utils.clock import today_for_user
from utils.date_utils import (
    format_date_full_ru,
    is_skip_time_phrase,
    parse_natural_date,
    parse_time,
    weekday_name,
)
from utils.reminder_utils import describe_reminder, parse_reminder_offset
from utils.repeat_parser import describe_rule
from utils.text import (
    MAX_DESCRIPTION,
    MAX_MESSAGE,
    MAX_TITLE,
    esc,
    unquote_menu_literal,
)

router = Router(name="myplans")

MONTH_NAMES = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]

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
    db: UserDB, page: int = 0, page_size: int = 5
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
        for item in items[:6]:
            if item.done_at:
                prefix = "✅"
            elif item.kind == "recur":
                prefix = "🔁"
            else:
                prefix = "•"
            lines.append(
                f"   {prefix} {esc(item.time_label())} — {esc(item.title, 60)}"
            )
        if len(items) > 6:
            lines.append(f"   … и ещё {len(items) - 6}")
        lines.append("")

    if max_pages > 1:
        lines.append(f"<i>Страница {page + 1} из {max_pages}</i>\n")

    if rules:
        lines.append("🔁 <b>Повторяющиеся задачи:</b>")
        for r in rules[:10]:
            t_lbl = r["time_start"] or "Без времени"
            if r["time_start"] and r["time_end"]:
                t_lbl = f"{r['time_start']}-{r['time_end']}"
            lines.append(
                f"   • {esc(t_lbl)} — <b>{esc(r['title'], 60)}</b> "
                f"({esc(describe_rule(r['rule_type'], r['rule_value']))})"
            )
        if len(rules) > 10:
            lines.append(
                f"   … и ещё {len(rules) - 10} (через «🗑 Удалить задачу»)"
            )
        lines.append("")

    lines.append("👇 Нажми на нужный день ниже, чтобы открыть его или удалить задачи:")

    # Обрезаем по границам строк, чтобы не разрезать HTML-теги.
    while len("\n".join(lines)) > MAX_MESSAGE and len(lines) > 2:
        lines.pop()
    lines.append("…")
    text = "\n".join(lines)

    kb = all_days_keyboard(days_list, today=today, page=page, page_size=page_size)
    return text, kb


def build_rules_view(
    db: UserDB, page: int = 0, page_size: int = 8
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Список всех повторяющихся правил с пагинацией."""
    today = today_for_user(db)
    _, rules = get_scheduled_days(db, today)
    if not rules:
        return "📭 <b>Повторяющихся задач нет.</b>", None

    max_pages = max(1, (len(rules) + page_size - 1) // page_size)
    page = max(0, min(page, max_pages - 1))
    lines = [
        f"🔁 <b>Все повторяющиеся задачи</b> "
        f"(страница {page + 1} из {max_pages}):\n"
    ]
    for r in rules:
        t_lbl = r["time_start"] or "без времени"
        if r["time_start"] and r["time_end"]:
            t_lbl = f"{r['time_start']}-{r['time_end']}"
        mark = "⏸" if not r["active"] else "🔁"
        lines.append(
            f"{mark} {esc(t_lbl)} — <b>{esc(r['title'], 60)}</b> "
            f"({esc(describe_rule(r['rule_type'], r['rule_value']))})"
        )
    lines.append(
        "\nНажми на повтор, чтобы поставить на паузу/включить, "
        "или 🗑, чтобы удалить все его повторения."
    )
    return "\n".join(lines), rules_delete_keyboard(rules, page, page_size)


def _ics_escape(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def _build_ics(db: UserDB) -> bytes:
    today = today_for_user(db)
    days, _ = get_scheduled_days(db, today, recurring_horizon_days=30)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TaskMNGR//RU",
        "CALSCALE:GREGORIAN",
    ]

    for d, items in days:
        if d < today:
            continue
        for item in items:
            lines += [
                "BEGIN:VEVENT",
                f"UID:taskmngr-{item.kind}-{item.source_id}-{d.isoformat()}@local",
                f"DTSTAMP:{stamp}",
            ]
            if item.time_start:
                try:
                    hh, mm = (int(x) for x in item.time_start.split(":"))
                except (ValueError, AttributeError):
                    hh, mm = 9, 0
                start = datetime.combine(d, dtime(hh, mm))
                end = start + timedelta(hours=1)
                if item.time_end:
                    try:
                        ehh, emm = (int(x) for x in item.time_end.split(":"))
                        candidate = datetime.combine(d, dtime(ehh, emm))
                        if candidate > start:
                            end = candidate
                    except (ValueError, AttributeError):
                        pass
                lines += [
                    f"DTSTART:{start:%Y%m%dT%H%M%S}",
                    f"DTEND:{end:%Y%m%dT%H%M%S}",
                ]
            else:
                lines += [
                    f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
                    f"DTEND;VALUE=DATE:{(d + timedelta(days=1)):%Y%m%d}",
                ]

            description = (item.description or "").strip()
            if item.kind == "recur" and item.rule_type and item.rule_value:
                description += "\nПовтор: " + describe_rule(
                    item.rule_type, item.rule_value
                )
            if item.done_at:
                description += "\nВыполнено"
            lines.append(f"SUMMARY:{_ics_escape(item.title)}")
            if description.strip():
                lines.append(f"DESCRIPTION:{_ics_escape(description.strip())}")
            lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode("utf-8")


async def _send_ics(message: Message, db: UserDB) -> None:
    await message.answer_document(
        BufferedInputFile(_build_ics(db), filename="taskmngr.ics"),
        caption="📤 Календарь для Google/Apple Calendar",
    )


def build_calendar_view(
    db: UserDB, year: int, month: int
) -> tuple[str, InlineKeyboardMarkup]:
    today = today_for_user(db)
    year = max(1970, min(2100, int(year)))
    month = int(month)
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1

    days_in_month = calendar.monthrange(year, month)[1]
    dates = [date(year, month, d) for d in range(1, days_in_month + 1)]
    counts = get_plan_counts_for_dates(db, dates)

    builder = InlineKeyboardBuilder()
    builder.row(
        *[
            InlineKeyboardButton(text=name, callback_data="noop")
            for name in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
        ]
    )
    for week in calendar.monthcalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
                continue
            d = date(year, month, day)
            label = str(day)
            if counts.get(d, 0) > 0:
                label += "•"
            if d == today:
                label = f"[{label}]"
            row.append(
                InlineKeyboardButton(
                    text=label, callback_data=f"day:{d.isoformat()}"
                )
            )
        builder.row(*row)

    builder.row(
        InlineKeyboardButton(
            text="⬅️", callback_data=f"cal:{year}:{month - 1}"
        ),
        InlineKeyboardButton(
            text="Сегодня", callback_data=f"cal:{today.year}:{today.month}"
        ),
        InlineKeyboardButton(
            text="➡️", callback_data=f"cal:{year}:{month + 1}"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ К неделе", callback_data="week_menu")
    )
    text = (
        f"📆 <b>{MONTH_NAMES[month - 1]} {year}</b>\n"
        "• — есть задачи. Нажми на день, чтобы открыть его."
    )
    return text, builder.as_markup()


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
    return text, global_delete_menu_keyboard(
        days_list, rules, today=today, page=page, page_size=5
    )


# ─── /MyPlans, «Дни с задачами» и общее «Удалить задачу» ─────────────────────


@router.message(Command("MyPlans", "myplans", ignore_case=True))
@router.message(F.text == BTN_MY_PLANS)
async def cmd_myplans(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    today = today_for_user(db)
    await message.answer(WEEK_INTRO, reply_markup=week_days_keyboard(today, db=db))


def _stats_view(db: UserDB) -> tuple[str, InlineKeyboardMarkup]:
    today = today_for_user(db)
    since = today - timedelta(days=6)
    text = (
        "📊 <b>Статистика за 7 дней</b>\n\n"
        f"✅ Разовых выполнено: <b>{count_done_plans(db, since)}</b>\n"
        f"🔁 Повторяющихся выполнено: <b>{count_done_rules(db, since)}</b>\n\n"
        f"📌 Активных разовых задач: <b>{count_active_plans(db, today)}</b>\n"
        f"🔁 Активных повторов: <b>{count_active_rules(db)}</b>"
    )
    return text, stats_keyboard()


@router.message(Command("stats", ignore_case=True))
async def cmd_stats(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    text, kb = _stats_view(db)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery, db: UserDB) -> None:
    text, kb = _stats_view(db)
    await callback.answer()
    await _safe_edit(callback.message, text, reply_markup=kb)


@router.message(Command("calendar", "cal", ignore_case=True))
async def cmd_calendar(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    today = today_for_user(db)
    text, kb = build_calendar_view(db, today.year, today.month)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("cal:"))
async def cb_calendar(callback: CallbackQuery, db: UserDB) -> None:
    try:
        _, year_str, month_str = (callback.data or "").split(":", 2)
        year, month = int(year_str), int(month_str)
    except ValueError:
        await callback.answer("Кнопка устарела", show_alert=True)
        return
    text, kb = build_calendar_view(db, year, month)
    await callback.answer()
    await _safe_edit(callback.message, text, reply_markup=kb)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(Command("export", "ics", ignore_case=True))
async def cmd_export(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    await _send_ics(message, db)


@router.callback_query(F.data == "export_ics")
async def cb_export_ics(callback: CallbackQuery, db: UserDB) -> None:
    await callback.answer()
    if callback.message:
        await _send_ics(callback.message, db)


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
        esc(target.description, MAX_DESCRIPTION)
        if target.description
        else "Описание отсутствует"
    )
    recur_line = ""
    if target.kind == "recur" and target.rule_type and target.rule_value:
        recur_line = (
            f"\n🔁 Повторение: {html.escape(describe_rule(target.rule_type, target.rule_value))}"
        )
    status_line = "\n✅ <b>Выполнено</b>" if target.done_at else ""
    return (
        f"<b>{esc(target.title, MAX_TITLE)}</b>\n"
        f"🕐 {html.escape(target.time_label())}{recur_line}{status_line}\n\n"
        f"💬 Описание: {description}\n\n"
        f"{reminder}"
    )


@router.callback_query(F.data.startswith("toggle_done:"))
async def on_toggle_done(callback: CallbackQuery, db: UserDB) -> None:
    _, kind, source_id_str, iso_date = (callback.data or "").split(":", 3)
    source_id = int(source_id_str)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)
    _, target = _find_item(items, kind, source_id_str)
    if target is None:
        await callback.answer("Задача не найдена", show_alert=True)
        return

    make_done = not bool(target.done_at)
    if kind == "plan":
        toggle_plan_done(db, source_id, make_done)
    else:
        toggle_rule_done(db, source_id, d, make_done)

    await callback.answer("✅ Готово" if make_done else "↩️ Возвращено")
    items = get_plans_for_date(db, d)
    _, target = _find_item(items, kind, source_id_str)
    if target is None:
        await _safe_edit(
            callback.message,
            build_day_text(d, items),
            day_plans_keyboard(d, items),
        )
        return

    await _safe_edit(
        callback.message,
        _item_detail_text(target, describe_reminder(target.reminder_minutes)),
        item_detail_keyboard(d, target),
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


# ─── Редактирование задач ─────────────────────────────────────────────────────


_EDIT_PROMPTS = {
    "title": "📝 Пришли новое название задачи.",
    "description": "💬 Пришли новое описание (или «-», чтобы убрать).",
    "date": "📅 Пришли новую дату задачи.",
    "start_date": "📅 С какой даты повторять задачу?",
    "time_start": "🕐 Пришли новое время начала (или «без времени»).",
    "time_end": "🏁 Пришли новое время окончания (или «без окончания»).",
}


@router.callback_query(F.data.startswith("edit_menu:"))
async def on_edit_menu(callback: CallbackQuery, db: UserDB) -> None:
    _, kind, source_id_str, iso_date = (callback.data or "").split(":", 3)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)
    _, target = _find_item(items, kind, source_id_str)
    if target is None:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    await callback.answer()
    await _safe_edit(
        callback.message,
        f"✏️ Редактирование: <b>{esc(target.title, MAX_TITLE)}</b>\n\nЧто меняем?",
        edit_item_keyboard(d, target),
    )


@router.callback_query(F.data.startswith("edit_field:"))
async def on_edit_field(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    _, kind, source_id_str, iso_date, field = (callback.data or "").split(":", 4)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)
    _, target = _find_item(items, kind, source_id_str)
    if target is None:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    await callback.answer()
    await state.set_state(PlanEditStates.waiting_value)
    await state.update_data(
        kind=kind, source_id=int(source_id_str), iso_date=iso_date, field=field
    )
    if callback.message:
        await callback.message.answer(
            _EDIT_PROMPTS.get(field, "Пришли новое значение."),
            reply_markup=cancel_inline_keyboard(),
        )


@router.message(
    StateFilter(PlanEditStates.waiting_value),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_edit_value(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    data = await state.get_data()
    kind = data["kind"]
    source_id = int(data["source_id"])
    field = data["field"]
    old_date = datetime.strptime(data["iso_date"], "%Y-%m-%d").date()
    raw = (message.text or "").strip()

    value = None
    new_date = None

    if field == "title":
        value = unquote_menu_literal(raw, MAIN_MENU_BUTTONS)
        if not value:
            await message.answer("Название не может быть пустым.")
            return
        if len(value) > MAX_TITLE:
            await message.answer(f"Максимум {MAX_TITLE} символов.")
            return
    elif field == "description":
        value = None if raw.lower() in {"-", "нет", "без описания"} or not raw else raw
        if value is not None and len(value) > MAX_DESCRIPTION:
            await message.answer(f"Максимум {MAX_DESCRIPTION} символов.")
            return
    elif field in {"date", "start_date"}:
        parsed = parse_natural_date(raw, today=today_for_user(db))
        if parsed is None:
            await message.answer("Не понял дату. Напиши, например, <code>19.10</code>.")
            return
        new_date = parsed
        value = parsed.isoformat()
    elif field in {"time_start", "time_end"}:
        if is_skip_time_phrase(raw):
            value = None
        else:
            value = parse_time(raw)
            if value is None:
                await message.answer("Не понял время. Напиши, например, <code>14:30</code>.")
                return

    if kind == "plan":
        kwargs = {field: value}
        if field == "date":
            kwargs = {"plan_date": new_date}
        update_plan(db, source_id, **kwargs)
    else:
        kwargs = {field: value}
        if field == "start_date":
            kwargs = {"start_date": new_date}
        update_rule(db, source_id, **kwargs)

    await state.clear()

    show_date = new_date or old_date
    items = get_plans_for_date(db, show_date)
    _, target = _find_item(items, kind, str(source_id))
    if target is None:
        await message.answer("Готово ✅")
        return

    await message.answer(
        _item_detail_text(target, describe_reminder(target.reminder_minutes)),
        reply_markup=item_detail_keyboard(show_date, target),
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
        plan = get_plan_row(db, source_id)
        title = plan["title"] if plan is not None else "эту задачу"
        await callback.answer()
        await _safe_edit(
            callback.message,
            f"🗑 Удалить задачу «<b>{esc(title, MAX_TITLE)}</b>»?",
            reply_markup=del_plan_confirm_keyboard(d, source_id),
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
        f"🔁 Задача <b>«{esc(rule['title'], MAX_TITLE)}»</b> является повторяющейся "
        f"({html.escape(describe_rule(rule['rule_type'], rule['rule_value']))}).\n\n"
        "Как именно её удалить?",
        reply_markup=recur_delete_confirm_keyboard(d, source_id),
    )


@router.callback_query(F.data.startswith("del_plan_yes:"))
async def on_delete_plan_yes(callback: CallbackQuery, db: UserDB) -> None:
    _, plan_id_str, iso_date = (callback.data or "").split(":", 2)
    plan_id = int(plan_id_str)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    delete_plan(db, plan_id)
    await callback.answer("🗑 Задача удалена!")
    items = get_plans_for_date(db, d)
    await _safe_edit(
        callback.message,
        f"✅ Задача удалена!\n\n{build_day_text(d, items)}",
        reply_markup=day_plans_keyboard(d, items),
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
    rule = get_rule_row(db, int(rule_id_str))
    if rule is None:
        await callback.answer("Задача уже удалена", show_alert=True)
        return
    await callback.answer()
    await _safe_edit(
        callback.message,
        f"🗑 Удалить все повторения задачи "
        f"«<b>{esc(rule['title'], MAX_TITLE)}</b>»?",
        reply_markup=del_rule_confirm_keyboard(int(rule_id_str)),
    )


@router.callback_query(F.data.startswith("del_rule_yes:"))
async def on_delete_rule_yes(callback: CallbackQuery, db: UserDB) -> None:
    _, rule_id_str = (callback.data or "").split(":", 1)
    delete_rule(db, int(rule_id_str))
    await callback.answer("🗑 Повторяющаяся задача удалена!")
    text, kb = build_delete_menu_view(db, page=0)
    await _safe_edit(callback.message, f"✅ Повторяющаяся задача удалена!\n\n{text}", reply_markup=kb)


@router.callback_query(F.data.startswith("del_rules:"))
async def cb_delete_rules(callback: CallbackQuery, db: UserDB) -> None:
    _, page_str = (callback.data or "").split(":", 1)
    page = int(page_str) if page_str.isdigit() else 0
    text, kb = build_rules_view(db, page=page)
    await callback.answer()
    await _safe_edit(callback.message, text, reply_markup=kb)


@router.callback_query(F.data.startswith("rule_toggle:"))
async def cb_rule_toggle(callback: CallbackQuery, db: UserDB) -> None:
    _, rule_id_str, page_str = (callback.data or "").split(":", 2)
    active = toggle_rule_active(db, int(rule_id_str))
    if active is None:
        await callback.answer("Повтор уже удалён", show_alert=True)
        return
    await callback.answer("▶️ Включено" if active else "⏸ Пауза")
    page = int(page_str) if page_str.isdigit() else 0
    text, kb = build_rules_view(db, page=page)
    await _safe_edit(callback.message, text, reply_markup=kb)


@router.callback_query(F.data.startswith("del_day_all:"))
async def on_delete_all_day(callback: CallbackQuery, db: UserDB) -> None:
    _, iso_date = (callback.data or "").split(":", 1)
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    items = get_plans_for_date(db, d)
    await callback.answer()
    await _safe_edit(
        callback.message,
        f"💥 Удалить <b>все задачи</b> на {format_date_full_ru(d)} "
        f"({len(items)} шт.)?",
        reply_markup=del_day_confirm_keyboard(d),
    )


@router.callback_query(F.data.startswith("del_day_all_yes:"))
async def on_delete_all_day_yes(callback: CallbackQuery, db: UserDB) -> None:
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
