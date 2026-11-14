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
)
from database.settings_repo import NotifySettings
from utils.clock import format_utc_offset
from utils.date_utils import format_date_ru, get_week_window, weekday_name
from utils.text import clip, clip_button


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
        InlineKeyboardButton(text="📊 Статистика", callback_data="stats")
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
    # Telegram не любит очень много кнопок; 50 задач на день более чем достаточно
    for item in items[:50]:
        if item.done_at:
            prefix = "✅ "
        elif item.kind == "recur":
            prefix = "🔁 "
        else:
            prefix = "🕐 "
        label = clip_button(f"{prefix}{item.time_label()} — {item.title}")
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
    done_label = "↩️ Вернуть" if item.done_at else "✅ Готово"
    builder.row(
        InlineKeyboardButton(
            text=done_label,
            callback_data=f"toggle_done:{item.kind}:{item.source_id}:{d.isoformat()}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Редактировать",
            callback_data=f"edit_menu:{item.kind}:{item.source_id}:{d.isoformat()}",
        )
    )
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


def edit_item_keyboard(d: date, item: PlanItem) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    base = f"edit_field:{item.kind}:{item.source_id}:{d.isoformat()}"
    builder.row(
        InlineKeyboardButton(text="📝 Название", callback_data=f"{base}:title")
    )
    builder.row(
        InlineKeyboardButton(text="💬 Описание", callback_data=f"{base}:description")
    )
    if item.kind == "plan":
        builder.row(
            InlineKeyboardButton(text="📅 Дата", callback_data=f"{base}:date")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="📅 С даты", callback_data=f"{base}:start_date")
        )
    builder.row(
        InlineKeyboardButton(text="🕐 Начало", callback_data=f"{base}:time_start"),
        InlineKeyboardButton(text="🏁 Окончание", callback_data=f"{base}:time_end"),
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"view:{item.kind}:{item.source_id}:{d.isoformat()}",
        )
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
    for item in items[:50]:
        prefix = "🔁" if item.kind == "recur" else "🗑"
        builder.row(
            InlineKeyboardButton(
                text=clip_button(f"{prefix} {item.time_label()} — {item.title}"),
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
                text=clip_button(f"🔁 Удалить повтор: {rule['title']}"),
                callback_data=f"del_rule_now:{rule['id']}",
            )
        )

    if len(rules) > 5:
        builder.row(
            InlineKeyboardButton(
                text=f"🔁 Все повторяющиеся ({len(rules)})",
                callback_data="del_rules:0",
            )
        )

    builder.row(
        InlineKeyboardButton(text="⬅️ К неделе", callback_data="week_menu")
    )
    return builder.as_markup()


def rules_delete_keyboard(
    rules: list[sqlite3.Row], page: int = 0, page_size: int = 8
) -> InlineKeyboardMarkup:
    """Список всех повторяющихся правил с постраничной навигацией."""
    builder = InlineKeyboardBuilder()
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, len(rules))
    for rule in rules[start_idx:end_idx]:
        mark = "⏸" if rule["active"] else "▶️"
        builder.row(
            InlineKeyboardButton(
                text=clip_button(f"{mark} {rule['title']}"),
                callback_data=f"rule_toggle:{rule['id']}:{page}",
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"del_rule_now:{rule['id']}",
            ),
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"del_rules:{page - 1}")
        )
    if end_idx < len(rules):
        nav_row.append(
            InlineKeyboardButton(text="➡️", callback_data=f"del_rules:{page + 1}")
        )
    if nav_row:
        builder.row(*nav_row)

    builder.row(
        InlineKeyboardButton(text="⬅️ К удалению", callback_data="del_menu")
    )
    return builder.as_markup()


def del_plan_confirm_keyboard(d: date, plan_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Да, удалить задачу",
            callback_data=f"del_plan_yes:{plan_id}:{d.isoformat()}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"day:{d.isoformat()}")
    )
    return builder.as_markup()


def del_day_confirm_keyboard(d: date) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💥 Да, удалить все задачи",
            callback_data=f"del_day_all_yes:{d.isoformat()}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"day:{d.isoformat()}")
    )
    return builder.as_markup()


def del_rule_confirm_keyboard(rule_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Да, удалить все повторения",
            callback_data=f"del_rule_yes:{rule_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Отмена", callback_data="del_menu")
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

    skip_mark = "✅" if settings.skip_empty_digest else "🚫"
    quiet_mark = "✅" if settings.quiet_enabled else "🚫"
    builder.row(
        InlineKeyboardButton(
            text=f"🔕 Пустые сводки: {skip_mark}",
            callback_data="settings_toggle:skip_empty",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🌙 Тихие часы: {quiet_mark} ({settings.quiet_start}–{settings.quiet_end})",
            callback_data="settings_toggle:quiet",
        )
    )
    if settings.quiet_enabled:
        builder.row(
            InlineKeyboardButton(
                text=f"🌙 Начало тихих часов: {settings.quiet_start}",
                callback_data="settings_edit:quiet_start",
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=f"🌙 Конец тихих часов: {settings.quiet_end}",
                callback_data="settings_edit:quiet_end",
            )
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ В меню", callback_data="week_menu")
    )
    return builder.as_markup()


# ─── Заметки ─────────────────────────────────────────────────────────────────


def notes_folders_keyboard(folders: list[sqlite3.Row]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📂 Все заметки", callback_data="notes_page:-1:0")
    )
    for folder in folders[:20]:
        builder.row(
            InlineKeyboardButton(
                text=clip_button(f"📁 {folder['name']} ({folder['note_count']})"),
                callback_data=f"notes_page:{folder['id']}:0",
            )
        )
    builder.row(
        InlineKeyboardButton(text="📁 Без папки", callback_data="notes_page:0:0")
    )
    builder.row(
        InlineKeyboardButton(text="➕ Новая заметка", callback_data="note_new:-1"),
        InlineKeyboardButton(text="📁 Новая папка", callback_data="note_folder_new"),
    )
    builder.row(InlineKeyboardButton(text="🔎 Поиск", callback_data="note_search"))
    builder.row(
        InlineKeyboardButton(text="⬅️ В меню", callback_data="week_menu")
    )
    return builder.as_markup()


def notes_list_keyboard(
    notes: list,
    folder_id: int,
    page: int,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * page_size
    for note in notes[start : start + page_size]:
        date_part = (note.updated_at or "")[:10]
        label = f"📝 {clip(note.display_title, 40)}"
        if date_part:
            label += f" • {date_part}"
        builder.row(
            InlineKeyboardButton(
                text=clip_button(label), callback_data=f"note:{note.id}"
            )
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=f"notes_page:{folder_id}:{page - 1}"
            )
        )
    if start + page_size < len(notes):
        nav.append(
            InlineKeyboardButton(
                text="➡️", callback_data=f"notes_page:{folder_id}:{page + 1}"
            )
        )
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(
            text="➕ Новая заметка", callback_data=f"note_new:{folder_id}"
        ),
        InlineKeyboardButton(text="⬅️ К папкам", callback_data="notes_menu"),
    )
    return builder.as_markup()


def note_card_keyboard(note, folder_id: int = -1) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in note.items[:10]:
        mark = "✅" if item["done"] else "⬜"
        builder.row(
            InlineKeyboardButton(
                text=clip_button(f"{mark} {item['text']}"),
                callback_data=f"note_item:{item['id']}:{note.id}",
            )
        )

    builder.row(
        InlineKeyboardButton(text="✏️ Текст", callback_data=f"note_text:{note.id}"),
        InlineKeyboardButton(
            text="📝 Заголовок", callback_data=f"note_title:{note.id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="☑️ + Пункт", callback_data=f"note_item_add:{note.id}"
        ),
        InlineKeyboardButton(
            text="📎 + Файл", callback_data=f"note_file_add:{note.id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="📁 Папка", callback_data=f"note_move:{note.id}"),
        InlineKeyboardButton(text="📅 Дата", callback_data=f"note_date:{note.id}"),
    )
    if note.files:
        builder.row(
            InlineKeyboardButton(
                text=f"📎 Показать файлы ({len(note.files)})",
                callback_data=f"note_files:{note.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="📤 Экспорт", callback_data=f"note_export:{note.id}"
        ),
        InlineKeyboardButton(
            text="🗑 Удалить", callback_data=f"note_delete:{note.id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ К списку", callback_data=f"notes_page:{folder_id}:0"
        )
    )
    return builder.as_markup()


def note_move_keyboard(note_id: int, folders: list[sqlite3.Row]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📁 Без папки", callback_data=f"note_move_to:{note_id}:0"
        )
    )
    for folder in folders[:20]:
        builder.row(
            InlineKeyboardButton(
                text=clip_button(f"📁 {folder['name']}"),
                callback_data=f"note_move_to:{note_id}:{folder['id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"note:{note_id}")
    )
    return builder.as_markup()


def note_delete_confirm_keyboard(note_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Да, удалить заметку",
            callback_data=f"note_delete_yes:{note_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"note:{note_id}")
    )
    return builder.as_markup()


def note_date_keyboard(note_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📅 Убрать дату", callback_data=f"note_date_clear:{note_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_flow")
    )
    return builder.as_markup()


def snooze_keyboard(
    kind: str, source_id: int, occurrence_date: str | None = None
) -> InlineKeyboardMarkup:
    date_part = occurrence_date or "-"
    builder = InlineKeyboardBuilder()
    for label, minutes in (("+10 мин", 10), ("+30 мин", 30), ("+1 час", 60)):
        builder.button(
            text=label,
            callback_data=f"snz:{kind}:{source_id}:{date_part}:{minutes}",
        )
    builder.adjust(3)
    return builder.as_markup()


def stats_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ К неделе", callback_data="week_menu")
    )
    return builder.as_markup()
