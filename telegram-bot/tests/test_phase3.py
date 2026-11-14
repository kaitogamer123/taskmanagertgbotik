from __future__ import annotations

from datetime import date
from pathlib import Path

import database.db_manager as dm
from database.plans_repo import add_plan, add_recurring_rule
from database.settings_repo import (
    get_settings,
    set_user_timezone_name,
    set_user_timezone_offset,
)
import handlers.myplans as myplans
from utils.clock import format_zone_offset, get_zone, now_for_user
from utils.timezones import normalize_zone_input, zone_label
from keyboards.inline import timezone_picker_keyboard


def test_timezone_aliases_and_offset() -> None:
    assert get_zone("Europe/Moscow") is not None
    assert normalize_zone_input("Москва") == "Europe/Moscow"
    assert normalize_zone_input("москва") == "Europe/Moscow"
    assert normalize_zone_input("Europe/Moscow") == "Europe/Moscow"
    assert normalize_zone_input(" new york ") == "America/New_York"
    assert normalize_zone_input("Алматы") == "Asia/Almaty"
    assert normalize_zone_input("ерунда") is None
    assert zone_label("Asia/Almaty") == "Алматы"
    # Полутонный пояс должен показывать минуты
    assert ":" in format_zone_offset("Asia/Kolkata", None)


def test_timezone_name_in_db(temp_env: Path) -> None:
    db = dm.ensure_user_db(1, "tz", "TZ")
    set_user_timezone_name(db, "Asia/Kolkata", 5)
    settings = get_settings(db)
    assert settings.timezone_name == "Asia/Kolkata"
    assert now_for_user(db) is not None

    set_user_timezone_offset(db, 3)
    assert get_settings(db).timezone_name is None
    db.close()

    kb = timezone_picker_keyboard()
    for row in kb.inline_keyboard:
        for button in row:
            assert len((button.callback_data or "").encode()) <= 64


def test_calendar_and_ics(temp_env: Path) -> None:
    db = dm.ensure_user_db(2, "cal", "Cal")
    today = date.today()
    add_plan(
        db,
        today,
        "Созвон, обсуждение; тест",
        "10:00",
        "11:30",
        "Описание\nвторая строка",
        30,
    )
    add_plan(db, today, "Без времени", None, None, None)
    add_recurring_rule(db, "Ежедневная", None, "08:00", None, today, "interval", "1")

    text, kb = myplans.build_calendar_view(db, today.year, today.month)
    assert "📆" in text
    assert kb.inline_keyboard
    assert len(kb.inline_keyboard[0]) == 7

    ics = myplans._build_ics(db).decode("utf-8")
    assert "BEGIN:VCALENDAR" in ics and "END:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics and "END:VEVENT" in ics
    assert "DTSTART" in ics and "SUMMARY:" in ics
    assert "Созвон\\, обсуждение\\; тест" in ics
    assert "Описание\\nвторая строка" in ics
    assert myplans._ics_escape("a,b;c\n") == "a\\,b\\;c\\n"
    db.close()
