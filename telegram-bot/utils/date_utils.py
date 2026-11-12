"""
Утилиты для разбора дат/времени, которые пишет пользователь на русском языке.

Поддерживаемые форматы (примеры):
    19.10 / 19.10.26 / 19.10.2026 / 19/10
    сегодня / завтра / послезавтра / вчера
    четверг / в четверг / на четверг
    на следующей неделе в четверг / на след неделе четверг
    через 3 дня / через неделю
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from utils.clock import now_local

RU_WEEKDAYS = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]

RU_WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

# разные формы слова (родительный/винительный падеж и т.п.), которые
# пользователи реально пишут в чате
_WEEKDAY_FORMS = {
    "понедельник": 0, "понедельника": 0, "пн": 0,
    "вторник": 1, "вторника": 1, "вт": 1,
    "среда": 2, "среду": 2, "среды": 2, "ср": 2,
    "четверг": 3, "четверга": 3, "чт": 3,
    "пятница": 4, "пятницу": 4, "пятницы": 4, "пт": 4,
    "суббота": 5, "субботу": 5, "субботы": 5, "сб": 5,
    "воскресенье": 6, "воскресенья": 6, "вс": 6,
}

MONTHS_RU = {
    "январь": 1, "января": 1, "янв": 1,
    "февраль": 2, "февраля": 2, "фев": 2,
    "март": 3, "марта": 3,
    "апрель": 4, "апреля": 4, "апр": 4,
    "май": 5, "мая": 5,
    "июнь": 6, "июня": 6,
    "июль": 7, "июля": 7,
    "август": 8, "августа": 8, "авг": 8,
    "сентябрь": 9, "сентября": 9, "сен": 9,
    "октябрь": 10, "октября": 10, "окт": 10,
    "ноябрь": 11, "ноября": 11, "ноя": 11,
    "декабрь": 12, "декабря": 12, "дек": 12,
}


def weekday_name(d: date, short: bool = False) -> str:
    return (RU_WEEKDAYS_SHORT if short else RU_WEEKDAYS)[d.weekday()]


def format_date_ru(d: date) -> str:
    """19.10"""
    return d.strftime("%d.%m")


def format_date_full_ru(d: date) -> str:
    """19.10.2026"""
    return d.strftime("%d.%m.%Y")


def parse_natural_date(text: str, today: Optional[date] = None) -> Optional[date]:
    """
    Пытается распознать дату в произвольном тексте на русском.
    Возвращает date или None, если распознать не удалось.
    """
    if today is None:
        today = now_local().date()

    raw = text.strip().lower()
    raw = raw.replace("ё", "е")
    if not raw:
        return None

    # 1. простые относительные слова
    simple_map = {
        "сегодня": 0,
        "сейчас": 0,
        "завтра": 1,
        "послезавтра": 2,
        "вчера": -1,
        "позавчера": -2,
    }
    if raw in simple_map:
        return today + timedelta(days=simple_map[raw])

    # 2. "через N дней/дня/день" / "через неделю" / "через N недель"
    m = re.search(r"через\s+(\d+)\s*(день|дня|дней)", raw)
    if m:
        return today + timedelta(days=int(m.group(1)))
    m = re.search(r"через\s+неделю", raw)
    if m:
        return today + timedelta(days=7)
    m = re.search(r"через\s+(\d+)\s*недел", raw)
    if m:
        return today + timedelta(weeks=int(m.group(1)))

    # 3. числовой формат дд.мм, дд.мм.гг(гг), дд/мм, дд-мм
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b", raw)
    if m:
        day_ = int(m.group(1))
        month_ = int(m.group(2))
        year_group = m.group(3)
        try:
            if year_group:
                year_ = int(year_group)
                if year_ < 100:
                    year_ += 2000
            else:
                year_ = today.year
                candidate = date(year_, month_, day_)
                # если дата с текущим годом уже прошла больше чем на месяц назад,
                # предполагаем, что речь про следующий год
                if candidate < today - timedelta(days=31):
                    year_ += 1
            return date(year_, month_, day_)
        except ValueError:
            pass

    # 4. "19 октября" / "19 окт" / "19 октября 2026"
    m = re.search(
        r"\b(\d{1,2})\s+(" + "|".join(MONTHS_RU.keys()) + r")(?:\s+(\d{4}))?\b", raw
    )
    if m:
        day_ = int(m.group(1))
        month_ = MONTHS_RU[m.group(2)]
        year_ = int(m.group(3)) if m.group(3) else today.year
        try:
            candidate = date(year_, month_, day_)
            if not m.group(3) and candidate < today - timedelta(days=31):
                candidate = date(year_ + 1, month_, day_)
            return candidate
        except ValueError:
            return None

    # 5. упоминание дня недели
    weekday_idx = None
    for word, idx in _WEEKDAY_FORMS.items():
        if re.search(rf"\b{word}\b", raw):
            weekday_idx = idx
            break

    if weekday_idx is not None:
        next_week = bool(
            re.search(r"следующ", raw) or re.search(r"будущ", raw)
        )
        this_week = bool(re.search(r"этой\s+недел", raw) or re.search(r"текущ", raw))

        if next_week:
            monday_this_week = today - timedelta(days=today.weekday())
            monday_next_week = monday_this_week + timedelta(days=7)
            return monday_next_week + timedelta(days=weekday_idx)

        days_ahead = (weekday_idx - today.weekday()) % 7
        if this_week and days_ahead == 0:
            days_ahead = 0
        return today + timedelta(days=days_ahead)

    return None


TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*[:.\-\s]\s*([0-5]\d)(?!\d)")

_NO_TIME_MARKERS = (
    "без врем",
    "без оконч",
    "без начала",
    "без конкретн",
    "не знаю",
    "неизвестно",
    "пропустить",
)


def is_skip_time_phrase(text: str) -> bool:
    """Проверяет, написал ли пользователь явно, что времени нет / нужно пропустить."""
    raw = (text or "").strip().lower().replace("ё", "е")
    if raw in {"нет", "-", "не надо"}:
        return True
    return any(marker in raw for marker in _NO_TIME_MARKERS)


def parse_time(text: str) -> Optional[str]:
    """Вытаскивает время HH:MM из текста. Возвращает строку '14:30' или None."""
    raw = (text or "").strip().lower().replace("ё", "е")
    if not raw or is_skip_time_phrase(raw):
        return None
    m = TIME_RE.search(raw)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        return f"{hour:02d}:{minute:02d}"
    # "9" / "14" / "в 14" / "9ч" / "14 часов" -> считаем часом
    m2 = re.fullmatch(r"(?:в\s+)?(\d{1,2})\s*(?:ч|час|часа|часов)?", raw)
    if m2:
        hour = int(m2.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
    return None


def get_week_window(start: date, days: int = 7) -> list[date]:
    """Список дат начиная с start (включительно) на `days` дней вперёд."""
    return [start + timedelta(days=i) for i in range(days)]
