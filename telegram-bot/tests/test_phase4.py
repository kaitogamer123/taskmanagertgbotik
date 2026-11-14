from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import database.db_manager as dm
import services.notifier as notifier
import handlers.myplans as myplans
from database.plans_repo import (
    add_plan,
    add_reminder,
    delete_reminder,
    get_history_dates,
    get_plans_for_date,
    get_reminders,
    set_reminders,
)
from database.settings_repo import (
    set_user_timezone_offset,
    toggle_evening,
    toggle_morning,
)
from database.templates_repo import (
    create_template,
    delete_template,
    get_template,
    list_templates,
)
from keyboards.inline import reminders_menu_keyboard, templates_menu_keyboard


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text, kwargs))


def _user(temp_env: Path, telegram_id: int) -> None:
    db = dm.ensure_user_db(telegram_id, f"u{telegram_id}", "U")
    set_user_timezone_offset(db, 0)
    toggle_morning(db, False)
    toggle_evening(db, False)
    db.close()


def test_multiple_reminders_repo(temp_env: Path) -> None:
    db = dm.ensure_user_db(1, "rem", "R")
    today = date(2026, 2, 10)
    plan_id = add_plan(db, today, "Мульти", "10:00", None, None, 30)
    assert get_reminders(db, "plan", plan_id) == [30]
    add_reminder(db, "plan", plan_id, 60)
    assert get_reminders(db, "plan", plan_id) == [60, 30]
    item = next(i for i in get_plans_for_date(db, today) if i.source_id == plan_id)
    assert item.reminders == [60, 30]

    delete_reminder(db, "plan", plan_id, 60)
    assert get_reminders(db, "plan", plan_id) == [30]
    set_reminders(db, "plan", plan_id, [15, 30])
    assert get_reminders(db, "plan", plan_id) == [30, 15]

    kb = reminders_menu_keyboard("plan", plan_id, today.isoformat(), [30, 15])
    for row in kb.inline_keyboard:
        for button in row:
            assert len((button.callback_data or "").encode()) <= 64
    db.close()


@pytest.mark.asyncio
async def test_multiple_reminders_notifier(
    temp_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user(temp_env, 2)
    db = dm.open_user_db_by_id(2)
    assert db is not None
    today = date(2026, 2, 10)
    plan_id = add_plan(db, today, "Мульти", "10:00", None, None, 30)
    add_reminder(db, "plan", plan_id, 60)
    db.close()

    bot = FakeBot()
    monkeypatch.setattr(
        notifier, "now_in_zone", lambda name, offset: datetime(2026, 2, 10, 9, 0)
    )
    await notifier._process_user(bot, 2)
    assert any("Мульти" in text for _, text, _ in bot.messages)

    monkeypatch.setattr(
        notifier, "now_in_zone", lambda name, offset: datetime(2026, 2, 10, 9, 30)
    )
    await notifier._process_user(bot, 2)
    texts = [text for _, text, _ in bot.messages]
    assert sum("Мульти" in text for text in texts) == 2

    # повторный тик не дублирует
    await notifier._process_user(bot, 2)
    assert sum("Мульти" in text for text in [m[1] for m in bot.messages]) == 2


def test_active_vs_history(temp_env: Path) -> None:
    db = dm.ensure_user_db(5, "hist", "H")
    today = date.today()
    add_plan(db, today - timedelta(days=3), "Старый план", "09:00", None, None)
    add_plan(db, today + timedelta(days=2), "Новый план", "10:00", None, None)

    history = get_history_dates(db, today)
    assert today - timedelta(days=3) in history

    active_text, _ = myplans.build_all_days_view(db)
    assert "Новый план" in active_text
    assert "Старый план" not in active_text

    history_text, _ = myplans.build_history_view(db)
    assert "Старый план" in history_text
    db.close()


def test_templates(temp_env: Path) -> None:
    db = dm.ensure_user_db(3, "tpl", "T")
    template_id = create_template(
        db, "Шаблон", "Описание", "09:00", "10:00", 30
    )
    template = get_template(db, template_id)
    assert template is not None
    assert template["title"] == "Шаблон"
    assert list_templates(db)

    kb = templates_menu_keyboard(list_templates(db))
    for row in kb.inline_keyboard:
        for button in row:
            assert len((button.callback_data or "").encode()) <= 64

    delete_template(db, template_id)
    assert get_template(db, template_id) is None
    db.close()


def test_legacy_reminder_migration(temp_env: Path) -> None:
    path = temp_env / "oldrem.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE user_meta (
            telegram_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            created_at TEXT, last_checked REAL
        );
        CREATE TABLE plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT, plan_date TEXT NOT NULL,
            time_start TEXT, time_end TEXT, title TEXT NOT NULL, description TEXT,
            reminder_minutes INTEGER, reminder_sent INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE recurring_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT, time_start TEXT, time_end TEXT,
            start_date TEXT NOT NULL, rule_type TEXT NOT NULL,
            rule_value TEXT NOT NULL, created_at TEXT,
            reminder_minutes INTEGER, last_reminder_date TEXT,
            excluded_dates TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE user_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            morning_enabled INTEGER NOT NULL DEFAULT 1,
            morning_time TEXT NOT NULL DEFAULT '08:00',
            evening_enabled INTEGER NOT NULL DEFAULT 1,
            evening_time TEXT NOT NULL DEFAULT '20:00',
            last_morning_sent TEXT, last_evening_sent TEXT,
            utc_offset INTEGER, timezone_configured INTEGER NOT NULL DEFAULT 0,
            demo_seeded INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO user_meta (telegram_id, username) VALUES (4, 'oldrem');
        INSERT INTO plans (plan_date, time_start, title, reminder_minutes)
            VALUES ('2026-01-01', '10:00', 'Старая', 30);
        INSERT INTO recurring_rules
            (title, start_date, rule_type, rule_value, reminder_minutes)
            VALUES ('Старый повтор', '2026-01-01', 'interval', '1', 60);
        INSERT INTO user_settings (id) VALUES (1);
        """
    )
    conn.commit()
    conn.close()

    db = dm.ensure_user_db(4, "oldrem", "Old")
    plan_id = db.conn.execute("SELECT id FROM plans LIMIT 1").fetchone()["id"]
    rule_id = db.conn.execute("SELECT id FROM recurring_rules LIMIT 1").fetchone()["id"]
    assert get_reminders(db, "plan", plan_id) == [30]
    assert get_reminders(db, "recur", rule_id) == [60]
    db.close()
