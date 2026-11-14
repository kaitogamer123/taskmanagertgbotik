"""
Разбор и форматирование "за сколько времени напомнить о задаче".

Напоминание хранится в базе как целое число минут:
    0     — напоминание выключено
    None  — пользователь ещё не настраивал (в этом случае считаем "выключено")
    >0    — напомнить за столько минут до начала задачи
"""
from __future__ import annotations

import re
from typing import Optional

_DISABLE_WORDS = {
    "без напоминания",
    "не напоминать",
    "нет",
    "выключить",
    "отключить",
    "не надо",
    "-",
}

# (регулярка, сколько минут в одной единице)
_REMINDER_PARTS: tuple[tuple[str, int], ...] = (
    (r"(\d+(?:[.,]\d+)?)\s*(?:день|дня|дней|сутки|суток)", 24 * 60),
    (r"(\d+(?:[.,]\d+)?)\s*(?:недел\w*)", 7 * 24 * 60),
    (r"(\d+(?:[.,]\d+)?)\s*(?:месяц\w*)", 30 * 24 * 60),
    (r"(\d+(?:[.,]\d+)?)\s*(?:ч\b|час\w*)", 60),
    (r"(\d+(?:[.,]\d+)?)\s*(?:м\b|мин\w*)", 1),
)

MAX_REMINDER_MINUTES = 366 * 24 * 60


def parse_reminder_offset(text: str) -> Optional[int]:
    """
    Пытается превратить фразу пользователя в число минут.
    Возвращает:
        0    — если пользователь явно попросил не напоминать;
        int  — количество минут до задачи;
        None — если не удалось распознать фразу.

    Поддерживает комбинации: "1 час 30 минут", "2 дня", "за неделю",
    "за 1.5 часа" и т.п.
    """
    raw = text.strip().lower().replace("ё", "е")
    if not raw:
        return None

    if raw in _DISABLE_WORDS:
        return 0

    total = 0.0
    found = False
    for pattern, multiplier in _REMINDER_PARTS:
        for match in re.finditer(pattern, raw):
            total += float(match.group(1).replace(",", ".")) * multiplier
            found = True

    if found:
        return min(int(total), MAX_REMINDER_MINUTES)

    if "полтора часа" in raw or "полторы часа" in raw:
        return 90
    if "полчаса" in raw:
        return 30
    if re.fullmatch(r"(?:за\s+)?час", raw):
        return 60
    if "недел" in raw:
        return 7 * 24 * 60
    if "месяц" in raw:
        return 30 * 24 * 60
    if "день" in raw or "сутки" in raw:
        return 24 * 60
    if "полдня" in raw:
        return 12 * 60

    # просто число -> считаем минутами
    m = re.fullmatch(r"(\d+)", raw)
    if m:
        return min(int(m.group(1)), MAX_REMINDER_MINUTES)

    return None


def format_minutes_label(minutes: int) -> str:
    """Человекочитаемое описание интервала, например '1 час', '90 минут', '2 дня'."""
    if minutes <= 0:
        return "0 минут"

    if minutes % (24 * 60) == 0 and minutes >= 24 * 60:
        days = minutes // (24 * 60)
        return f"{days} {_plural(days, 'день', 'дня', 'дней')}"

    if minutes % 60 == 0 and minutes >= 60:
        hours = minutes // 60
        return f"{hours} {_plural(hours, 'час', 'часа', 'часов')}"

    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        parts = [f"{hours} {_plural(hours, 'час', 'часа', 'часов')}"]
        if mins:
            parts.append(f"{mins} {_plural(mins, 'минуту', 'минуты', 'минут')}")
        return " ".join(parts)

    return f"{minutes} {_plural(minutes, 'минуту', 'минуты', 'минут')}"


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def describe_reminder(minutes: Optional[int]) -> str:
    if not minutes:
        return "🔕 Напоминание выключено"
    return f"⏰ Напомню за {format_minutes_label(minutes)} до начала"
