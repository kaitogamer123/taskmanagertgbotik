from __future__ import annotations

from datetime import date

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.plans_repo import PlanItem
from database.settings_repo import NotifySettings
from utils.date_utils import format_date_ru, get_week_window, weekday_name


def week_days_keyboard(start: date) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    today = date.today()
    for d in get_week_window(start):
        label = f"{weekday_name(d).capitalize()} {format_date_ru(d)}"
        if d == today:
            label += " (сегодня)"
        builder.row(
            InlineKeyboardButton(text=label, callback_data=f"day:{d.isoformat()}")
        )
    return builder.as_markup()


def day_plans_keyboard(d: date, items: list[PlanItem]):
    builder = InlineKeyboardBuilder()
    for item in items:
        label = f"{item.time_label()}\n{item.title}"
        callback_data = f"view:{item.kind}:{item.source_id}:{d.isoformat()}"
        builder.row(InlineKeyboardButton(text=label, callback_data=callback_data))
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить задачу", callback_data=f"addto:{d.isoformat()}"
        )
    )
    return builder.as_markup()


def item_detail_keyboard(d: date, item: PlanItem):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⏰ Изменить время оповещения",
            callback_data=f"remind_edit:{item.kind}:{item.source_id}:{d.isoformat()}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"day:{d.isoformat()}")
    )
    return builder.as_markup()


def back_to_day_keyboard(d: date):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"day:{d.isoformat()}")
    )
    return builder.as_markup()


def skip_keyboard(callback_data: str, label: str = "Пропустить"):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=label, callback_data=callback_data))
    return builder.as_markup()


def every_n_type_keyboard():
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
        InlineKeyboardButton(text="Каждый месяц (число)", callback_data="everyn_type:monthly")
    )
    builder.row(
        InlineKeyboardButton(text="Каждый год (дата)", callback_data="everyn_type:yearly")
    )
    return builder.as_markup()


def weekday_multiselect_keyboard(selected: set[int]):
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
    return builder.as_markup()


# --- Напоминания ("за сколько времени до задачи напомнить") ---

REMINDER_PRESETS: list[tuple[str, int]] = [
    ("15 минут", 15),
    ("30 минут", 30),
    ("1 час", 60),
    ("2 часа", 120),
    ("1 день", 24 * 60),
]


def reminder_choice_keyboard(prefix: str):
    """
    prefix — префикс callback_data, например "np_rem" / "en_rem" / "redit_rem".
    Итоговые callback_data: "{prefix}:{minutes}" и "{prefix}:off".
    """
    builder = InlineKeyboardBuilder()
    for label, minutes in REMINDER_PRESETS:
        builder.row(InlineKeyboardButton(text=f"⏰ {label}", callback_data=f"{prefix}:{minutes}"))
    builder.row(InlineKeyboardButton(text="🔕 Без напоминания", callback_data=f"{prefix}:off"))
    return builder.as_markup()


# --- Настройки ежедневных уведомлений (/notify) ---


def settings_keyboard(settings: NotifySettings):
    builder = InlineKeyboardBuilder()
    morning_mark = "✅" if settings.morning_enabled else "🚫"
    evening_mark = "✅" if settings.evening_enabled else "🚫"
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
