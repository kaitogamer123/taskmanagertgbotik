"""
Разбор текстовых триггеров для повторяющихся задач (/everyN), например:
    "каждый день" / "ежедневно"
    "каждые 3 дня"
    "каждый понедельник" / "по понедельникам и средам"
    "каждый месяц 15 числа" / "каждое 1 число"
    "каждый год 1 января" / "каждый год 05.03"
"""
from __future__ import annotations

import re
from typing import Optional

from utils.date_utils import MONTHS_RU, _WEEKDAY_FORMS

WEEKDAY_PLURAL_FORMS = {
    "понедельникам": 0,
    "вторникам": 1,
    "средам": 2,
    "четвергам": 3,
    "пятницам": 4,
    "субботам": 5,
    "воскресеньям": 6,
}


class RepeatParseResult:
    def __init__(self, rule_type: str, rule_value: Optional[str]):
        self.rule_type = rule_type
        self.rule_value = rule_value  # None значит "нужно уточнить у пользователя"

    def is_complete(self) -> bool:
        return self.rule_value is not None


def parse_repeat_phrase(text: str) -> Optional[RepeatParseResult]:
    raw = text.strip().lower().replace("ё", "е")
    if not raw:
        return None

    # ежедневно / каждый день
    if re.search(r"кажд\w*\s*день\b", raw) or "ежедневно" in raw:
        return RepeatParseResult("interval", "1")

    # каждые N дней
    m = re.search(r"кажд\w*\s*(\d+)\s*дн", raw)
    if m and int(m.group(1)) > 0:
        return RepeatParseResult("interval", m.group(1))

    # дни недели (одиночные или множественные упоминания)
    weekdays_found: set[int] = set()
    for word, idx in {**_WEEKDAY_FORMS, **WEEKDAY_PLURAL_FORMS}.items():
        if re.search(rf"\b{word}\b", raw):
            weekdays_found.add(idx)
    if weekdays_found and ("кажд" in raw or "по " in raw):
        value = ",".join(str(i) for i in sorted(weekdays_found))
        return RepeatParseResult("weekday", value)

    # ежемесячно / каждый месяц
    if re.search(r"кажд\w*\s*месяц", raw):
        m = re.search(r"(\d{1,2})\s*(?:числ\w*)?", raw.split("месяц", 1)[-1])
        if m:
            day = int(m.group(1))
            if 1 <= day <= 31:
                return RepeatParseResult("monthly", str(day))
        return RepeatParseResult("monthly", None)

    # каждое N число
    m = re.search(r"кажд\w*\s*(\d{1,2})\s*числ", raw)
    if m and 1 <= int(m.group(1)) <= 31:
        return RepeatParseResult("monthly", m.group(1))

    # ежегодно / каждый год
    if re.search(r"кажд\w*\s*год", raw) or "ежегодно" in raw:
        tail = raw.split("год", 1)[-1]
        m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})\b", tail)
        if m:
            day_, month_ = int(m.group(1)), int(m.group(2))
            if 1 <= month_ <= 12 and 1 <= day_ <= 31:
                return RepeatParseResult("yearly", f"{day_}-{month_}")
        m = re.search(r"\b(\d{1,2})\s+(" + "|".join(MONTHS_RU.keys()) + r")\b", tail)
        if m:
            day = int(m.group(1))
            month = MONTHS_RU[m.group(2)]
            if 1 <= day <= 31:
                return RepeatParseResult("yearly", f"{day}-{month}")
        return RepeatParseResult("yearly", None)

    return None


def describe_rule(rule_type: str, rule_value: str) -> str:
    from utils.date_utils import RU_WEEKDAYS

    if rule_type == "interval":
        n = int(rule_value)
        return "каждый день" if n == 1 else f"каждые {n} дн."
    if rule_type == "weekday":
        names = [RU_WEEKDAYS[int(i)].capitalize() for i in rule_value.split(",") if i != ""]
        return "по дням: " + ", ".join(names)
    if rule_type == "monthly":
        return f"каждый месяц, {rule_value} числа"
    if rule_type == "yearly":
        day, month = rule_value.split("-")
        return f"каждый год, {int(day):02d}.{int(month):02d}"
    return rule_value
