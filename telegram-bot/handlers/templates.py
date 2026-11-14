"""Шаблоны задач: сохранить заготовку и создать по ней задачу на дату."""
from __future__ import annotations

import re
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db_manager import UserDB
from database.plans_repo import (
    add_plan,
    get_plan_row,
    get_reminders,
    get_rule_row,
)
from database.templates_repo import (
    create_template,
    delete_template,
    get_template,
    list_templates,
)
from keyboards.inline import (
    template_card_keyboard,
    template_delete_confirm_keyboard,
    templates_menu_keyboard,
)
from keyboards.reply import MAIN_MENU_BUTTONS
from states import TemplateStates
from utils.clock import today_for_user
from utils.date_utils import (
    format_date_full_ru,
    parse_natural_date,
    parse_time,
    weekday_name,
)
from utils.reminder_utils import describe_reminder, parse_reminder_offset
from utils.text import MAX_DESCRIPTION, MAX_TITLE, esc

router = Router(name="templates")

_TIME_RANGE_RE = re.compile(
    r"(?<!\d)(\d{1,2}(?::\d{2})?)\s*[-–—]\s*(\d{1,2}(?::\d{2})?)(?!\d)"
)


def _time_label(template) -> str:
    if template["time_start"] and template["time_end"]:
        return f"{template['time_start']}-{template['time_end']}"
    if template["time_start"]:
        return str(template["time_start"])
    return "без времени"


def _template_text(template) -> str:
    description = (
        esc(template["description"], MAX_DESCRIPTION)
        if template["description"]
        else "Описание отсутствует"
    )
    return (
        f"📋 <b>{esc(template['title'], MAX_TITLE)}</b>\n"
        f"🕐 {esc(_time_label(template))}\n"
        f"💬 {description}\n"
        f"{describe_reminder(template['reminder_minutes'])}"
    )


def _parse_line(raw: str):
    parts = [part.strip() for part in raw.split("|")]
    title = parts[0] if parts else ""
    if not title:
        return None
    description = parts[1] if len(parts) > 1 and parts[1] else None

    time_start = None
    time_end = None
    time_part = parts[2] if len(parts) > 2 else ""
    if not time_part and len(parts) == 2 and parts[1]:
        if _TIME_RANGE_RE.search(parts[1]) or parse_time(parts[1]):
            time_part = parts[1]
            description = None
    if time_part:
        match = _TIME_RANGE_RE.search(time_part)
        if match:
            time_start = parse_time(match.group(1))
            time_end = parse_time(match.group(2))
        else:
            time_start = parse_time(time_part)

    reminder = None
    if len(parts) > 3 and parts[3]:
        reminder = parse_reminder_offset(parts[3])
        if reminder is not None and reminder <= 0:
            reminder = None

    return title, description, time_start, time_end, reminder


async def _send_templates_menu(message: Message, db: UserDB) -> None:
    templates = list_templates(db)
    if templates:
        text = (
            "📋 <b>Шаблоны задач</b>\n"
            f"Всего: {len(templates)}\n\n"
            "Нажми на шаблон, чтобы создать задачу на сегодня, завтра или другую дату."
        )
    else:
        text = (
            "📋 <b>Шаблоны задач</b>\n\n"
            "Пока пусто. Создай шаблон кнопкой ниже или сохрани существующую "
            "задачу как шаблон из её карточки."
        )
    await message.answer(
        text, reply_markup=templates_menu_keyboard(templates)
    )


@router.message(Command("templates", "template", ignore_case=True))
async def cmd_templates(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    await _send_templates_menu(message, db)


@router.callback_query(F.data == "tpl_menu")
async def cb_templates_menu(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    templates = list_templates(db)
    if templates:
        text = (
            "📋 <b>Шаблоны задач</b>\n"
            f"Всего: {len(templates)}\n\n"
            "Нажми на шаблон, чтобы создать задачу."
        )
    else:
        text = "📋 <b>Шаблоны задач</b>\n\nПока пусто."
    await callback.answer()
    try:
        await callback.message.edit_text(
            text, reply_markup=templates_menu_keyboard(templates)
        )
    except Exception:  # noqa: BLE001
        if callback.message:
            await callback.message.answer(
                text, reply_markup=templates_menu_keyboard(templates)
            )


@router.callback_query(F.data.startswith("tpl_page:"))
async def cb_templates_page(callback: CallbackQuery, db: UserDB) -> None:
    _, page_str = (callback.data or "").split(":", 1)
    page = int(page_str) if page_str.isdigit() else 0
    templates = list_templates(db)
    text = (
        "📋 <b>Шаблоны задач</b>\n\n"
        "Нажми на шаблон, чтобы создать задачу."
    )
    await callback.answer()
    try:
        await callback.message.edit_text(
            text,
            reply_markup=templates_menu_keyboard(templates, page=page),
        )
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == "tpl_new")
async def cb_template_new(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.set_state(TemplateStates.waiting_line)
    if callback.message:
        await callback.message.answer(
            "➕ Новый шаблон. Пришли одной строкой:\n"
            "<code>Название | описание | 10:00-11:00 | за 30 минут</code>\n\n"
            "Описание, время и напоминание можно не указывать. "
            "Пример: <code>Созвон | с командой | 10:00-11:00</code>"
        )


@router.message(
    StateFilter(TemplateStates.waiting_line),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_template_line(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    parsed = _parse_line((message.text or "").strip())
    if parsed is None:
        await message.answer("Нужно название. Формат: Название | описание | 10:00-11:00")
        return
    title, description, time_start, time_end, reminder = parsed
    if len(title) > MAX_TITLE:
        await message.answer(f"Слишком длинное название, максимум {MAX_TITLE} символов.")
        return
    if description and len(description) > MAX_DESCRIPTION:
        await message.answer(f"Слишком длинное описание, максимум {MAX_DESCRIPTION}.")
        return

    create_template(db, title, description, time_start, time_end, reminder)
    await state.clear()
    await message.answer("✅ Шаблон сохранён.")
    await _send_templates_menu(message, db)


@router.callback_query(F.data.startswith("tpl:"))
async def cb_template_card(callback: CallbackQuery, db: UserDB) -> None:
    template_id = int((callback.data or "").split(":", 1)[1])
    template = get_template(db, template_id)
    if template is None:
        await callback.answer("Шаблон уже удалён", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            _template_text(template),
            reply_markup=template_card_keyboard(template_id),
        )


async def _apply_template(
    message: Message, db: UserDB, template, d: date
) -> None:
    add_plan(
        db,
        d,
        template["title"],
        template["time_start"],
        template["time_end"],
        template["description"],
        template["reminder_minutes"],
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📅 Открыть день", callback_data=f"day:{d.isoformat()}"
        )
    )
    await message.answer(
        "✅ Задача создана по шаблону:\n\n"
        f"📅 {format_date_full_ru(d)} ({weekday_name(d)})\n"
        f"🕐 {esc(_time_label(template))}\n"
        f"📝 <b>{esc(template['title'], MAX_TITLE)}</b>",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("tpl_use:"))
async def cb_template_use(callback: CallbackQuery, db: UserDB) -> None:
    _, template_str, when = (callback.data or "").split(":", 2)
    template_id = int(template_str)
    template = get_template(db, template_id)
    if template is None:
        await callback.answer("Шаблон уже удалён", show_alert=True)
        return
    today = today_for_user(db)
    d = today if when == "today" else today + timedelta(days=1)
    await callback.answer("Добавлено")
    if callback.message:
        await _apply_template(callback.message, db, template, d)


@router.callback_query(F.data.startswith("tpl_use_date:"))
async def cb_template_use_date(
    callback: CallbackQuery, state: FSMContext
) -> None:
    template_id = int((callback.data or "").split(":", 1)[1])
    await callback.answer()
    await state.set_state(TemplateStates.waiting_date)
    await state.update_data(template_id=template_id)
    if callback.message:
        await callback.message.answer(
            "📅 На какую дату создать задачу по шаблону? "
            "Напиши, например <code>19.10</code> или «завтра»."
        )


@router.message(
    StateFilter(TemplateStates.waiting_date),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_template_date(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    parsed = parse_natural_date(
        (message.text or "").strip(), today=today_for_user(db)
    )
    if parsed is None:
        await message.answer("Не понял дату. Напиши, например, <code>19.10</code>.")
        return
    data = await state.get_data()
    template = get_template(db, int(data["template_id"]))
    if template is None:
        await message.answer("Шаблон уже удалён.")
        await state.clear()
        return
    await state.clear()
    await _apply_template(message, db, template, parsed)


@router.callback_query(F.data.startswith("tpl_delete:"))
async def cb_template_delete(callback: CallbackQuery, db: UserDB) -> None:
    template_id = int((callback.data or "").split(":", 1)[1])
    template = get_template(db, template_id)
    if template is None:
        await callback.answer("Шаблон уже удалён", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            f"🗑 Удалить шаблон «<b>{esc(template['title'], MAX_TITLE)}</b>»?",
            reply_markup=template_delete_confirm_keyboard(template_id),
        )


@router.callback_query(F.data.startswith("tpl_delete_yes:"))
async def cb_template_delete_yes(
    callback: CallbackQuery, db: UserDB
) -> None:
    template_id = int((callback.data or "").split(":", 1)[1])
    delete_template(db, template_id)
    await callback.answer("🗑 Шаблон удалён")
    templates = list_templates(db)
    if callback.message:
        await callback.message.edit_text(
            "✅ Шаблон удалён.\n\n📋 <b>Шаблоны задач</b>",
            reply_markup=templates_menu_keyboard(templates),
        )


@router.callback_query(F.data.startswith("tpl_save:"))
async def cb_save_template(callback: CallbackQuery, db: UserDB) -> None:
    _, kind, source_id_str, iso_date = (callback.data or "").split(":", 3)
    source_id = int(source_id_str)
    row = get_plan_row(db, source_id) if kind == "plan" else get_rule_row(db, source_id)
    if row is None:
        await callback.answer("Задача уже удалена", show_alert=True)
        return
    reminders = get_reminders(db, kind, source_id)
    reminder = max(reminders) if reminders else row["reminder_minutes"]
    create_template(
        db,
        row["title"],
        row["description"],
        row["time_start"],
        row["time_end"],
        reminder,
    )
    await callback.answer("💾 Сохранено")
    if callback.message:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="📋 Шаблоны", callback_data="tpl_menu")
        )
        await callback.message.answer(
            f"💾 Шаблон «<b>{esc(row['title'], MAX_TITLE)}</b>» сохранён.",
            reply_markup=builder.as_markup(),
        )
