"""Инлайн-клавиатуры бота."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db_manager import UserDB
from database.plans_repo import (
    PlanItem,
    get_plan_counts_for_dates,
    get_plans_for_date,
)
from database.settings_repo import NotifySettings
from utils.clock import format_utc_offset
from utils.date_utils import format_date_ru, get_week_window, weekday_name


def hour_picker_keyboard(allow_cancel: bool = False) -> InlineKeyboardMarkup:
    """Сетка часов 0..23 для быстрой настройки часового пояса в 1 нажатие."""
    builder = InlineKeyboardBuilder()
    for hour in range(24):
        builder.button(text=f"{hour:02d}:xx", callback_data=f"tz_hour:{hour}")
    builder.adjust(6)
    if allow_cancel:
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data="tz_cancel")
        )
    return builder.as_markup()


def week_days_keyboard(
    start: date, db: Optional[UserDB] = None
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    window = get_week_window(start)
    counts: dict[date, int] = {}
    if db is not None:
        # Считаем все 7 дней сразу (2 запроса вместо 14)
        counts = get_plan_counts_for_dates(db, window)

    for d in window:
        label = f"{weekday_name(d).capitalize()} {format_date_ru(d)}"
        if d == start:
            label += " (сегодня)"
        if counts.get(d, 0) > 0:
            label += f" • {counts[d]}"
        builder.row(
            InlineKeyboardButton(text=label, callback_data=f"day:{d.isoformat()}")
        )

    builder.row(
        InlineKeyboardButton(
            text="📋 В какие дни есть задачи", callback_data="all_days:0"
        )
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить задачу", callback_data="del_menu"),
        InlineKeyboardButton(text="⚙️ Настройка времени", callback_data="time_menu"),
    )
    return builder.as_markup()


def all_days_keyboard(
    days_list: list[tuple[date, list[PlanItem]]],
    today: date,
    page: int = 0,
    page_size: int = 10,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total = len(days_list)
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total)

    for d, items in days_list[start_idx:end_idx]:
        suffix = " (сегодня)" if d == today else ""
        label = (
            f"📅 {weekday_name(d).capitalize()} {format_date_ru(d)}{suffix} "
            f"— задач: {len(items)}"
        )
        builder.row(
            InlineKeyboardButton(text=label, callback_data=f"day:{d.isoformat()}")
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"all_days:{page - 1}")
        )
    if end_idx < total:
        nav_row.append(
            InlineKeyboardButton(text="Далее ➡️", callback_data=f"all_days:{page + 1}")
        )
    if nav_row:
        builder.row(*nav_row)

    builder.row(
        InlineKeyboardButton(text="🗑 Удалить задачу", callback_data="del_menu"),
        InlineKeyboardButton(text="⬅️ К неделе", callback_data="week_menu"),
    )
    return builder.as_markup()


def day_plans_keyboard(d: date, items: list[PlanItem]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        prefix = "🔁 " if item.kind == "recur" else "🕐 "
        label = f"{prefix}{item.time_label()} — {item.title}"
        callback_data = f"view:{item.kind}:{item.source_id}:{d.isoformat()}"
        builder.row(InlineKeyboardButton(text=label, callback_data=callback_data))

    action_row = [
        InlineKeyboardButton(
            text="➕ Добавить задачу", callback_data=f"addto:{d.isoformat()}"
        )
    ]
    if items:
        action_row.append(
            InlineKeyboardButton(
                text="🗑 Удалить задачу",
                callback_data=f"del_day_menu:{d.isoformat()}",
            )
        )
    builder.row(*action_row)

    builder.row(
        InlineKeyboardButton(text="⬅️ К списку дней", callback_data="week_menu")
    )
    return builder.as_markup()


def item_detail_keyboard(d: date, item: PlanItem) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⏰ Изменить время оповещения",
            callback_data=f"remind_edit:{item.kind}:{item.source_id}:{d.isoformat()}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить задачу",
            callback_data=f"del_item:{item.kind}:{item.source_id}:{d.isoformat()}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"day:{d.isoformat()}")
    )
    return builder.as_markup()


def recur_delete_confirm_keyboard(
    d: date, rule_id: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"📅 Удалить только на {format_date_ru(d)}",
            callback_data=f"del_skip:{rule_id}:{d.isoformat()}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить все повторения навсегда",
            callback_data=f"del_rule_full:{rule_id}:{d.isoformat()}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"day:{d.isoformat()}")
    )
    return builder.as_markup()


def day_delete_keyboard(d: date, items: list[PlanItem]) -> InlineKeyboardMarkup:
    """Клавиатура выбора конкретной задачи для удаления внутри выбранного дня."""
    builder = InlineKeyboardBuilder()
    for item in items:
        prefix = "🔁" if item.kind == "recur" else "🗑"
        builder.row(
            InlineKeyboardButton(
                text=f"{prefix} {item.time_label()} — {item.title}",
                callback_data=f"del_item:{item.kind}:{item.source_id}:{d.isoformat()}",
            )
        )
    if len(items) > 1:
        builder.row(
            InlineKeyboardButton(
                text=f"💥 Удалить все задачи за {format_date_ru(d)}",
                callback_data=f"del_day_all:{d.isoformat()}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад к дню", callback_data=f"day:{d.isoformat()}"
        )
    )
    return builder.as_markup()


def global_delete_menu_keyboard(
    days_list: list[tuple[date, list[PlanItem]]],
    rules: list[sqlite3.Row],
    today: date,
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """Общее меню удаления задач: выбор дня с задачами или повторяющегося правила."""
    builder = InlineKeyboardBuilder()
    total = len(days_list)
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total)

    for d, items in days_list[start_idx:end_idx]:
        suffix = " (сегодня)" if d == today else ""
        builder.row(
            InlineKeyboardButton(
                text=f"🗓 {weekday_name(d).capitalize()} {format_date_ru(d)}{suffix} ({len(items)})",
                callback_data=f"del_day_menu:{d.isoformat()}",
            )
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"del_page:{page - 1}")
        )
    if end_idx < total:
        nav_row.append(
            InlineKeyboardButton(text="➡️", callback_data=f"del_page:{page + 1}")
        )
    if nav_row:
        builder.row(*nav_row)

    for rule in rules[:5]:
        builder.row(
            InlineKeyboardButton(
                text=f"🔁 Удалить повтор: {rule['title']}",
                callback_data=f"del_rule_now:{rule['id']}",
            )
        )

    builder.row(
        InlineKeyboardButton(text="⬅️ К неделе", callback_data="week_menu")
    )
    return builder.as_markup()


def skip_keyboard(callback_data: str, label: str = "Пропустить") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=label, callback_data=callback_data))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_flow"))
    return builder.as_markup()


def cancel_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_flow"))
    return builder.as_markup()


def every_n_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Каждый день", callback_data="everyn_type:daily")
    )
    builder.row(
        InlineKeyboardButton(text="Каждые N дней", callback_data="everyn_type:interval")
    )
    builder.row(
        InlineKeyboardButton(text="По дням недели", callback_data="everyn_type:weekday")
    )
    builder.row(
        InlineKeyboardButton(
            text="Каждый месяц (число)", callback_data="everyn_type:monthly"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Каждый год (дата)", callback_data="everyn_type:yearly"
        )
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_flow"))
    return builder.as_markup()


def weekday_multiselect_keyboard(selected: set[int]) -> InlineKeyboardMarkup:
    from utils.date_utils import RU_WEEKDAYS

    builder = InlineKeyboardBuilder()
    for idx, name in enumerate(RU_WEEKDAYS):
        mark = "✅ " if idx in selected else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{mark}{name.capitalize()}", callback_data=f"wd_toggle:{idx}"
            )
        )
    builder.row(InlineKeyboardButton(text="Готово ✔️", callback_data="wd_done"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_flow"))
    return builder.as_markup()


REMINDER_PRESETS: list[tuple[str, int]] = [
    ("15 минут", 15),
    ("30 минут", 30),
    ("1 час", 60),
    ("2 часа", 120),
    ("1 день", 24 * 60),
]


def reminder_choice_keyboard(prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, minutes in REMINDER_PRESETS:
        builder.row(
            InlineKeyboardButton(
                text=f"⏰ {label}", callback_data=f"{prefix}:{minutes}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="🔕 Без напоминания", callback_data=f"{prefix}:off")
    )
    return builder.as_markup()


def settings_keyboard(
    settings: NotifySettings, current_time_str: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    tz_str = format_utc_offset(settings.utc_offset)
    morning_mark = "✅" if settings.morning_enabled else "🚫"
    evening_mark = "✅" if settings.evening_enabled else "🚫"

    builder.row(
        InlineKeyboardButton(
            text=f"🌍 Часовой пояс: {tz_str} (сейчас {current_time_str})",
            callback_data="tz_change",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🌅 Утром в {settings.morning_time} ({morning_mark})",
            callback_data="settings_edit:morning",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Выключить утро" if settings.morning_enabled else "Включить утро",
            callback_data="settings_toggle:morning",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🌙 Вечером в {settings.evening_time} ({evening_mark})",
            callback_data="settings_edit:evening",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="Выключить вечер" if settings.evening_enabled else "Включить вечер",
            callback_data="settings_toggle:evening",
        )
    )
    return builder.as_markup()
