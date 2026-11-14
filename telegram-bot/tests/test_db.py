from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import database.db_manager as dm
from database.plans_repo import (
    _rule_occurs_on,
    add_plan,
    add_recurring_rule,
    get_plan_counts_for_dates,
    get_plans_for_date,
    get_scheduled_days,
)


def _old_database(path: Path, telegram_id: int = 999) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE user_meta (
            telegram_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            created_at TEXT, last_checked REAL
        );
        CREATE TABLE plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT, plan_date TEXT NOT NULL,
            time_start TEXT, time_end TEXT, title TEXT NOT NULL, description TEXT
        );
        CREATE TABLE recurring_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT, time_start TEXT, time_end TEXT,
            start_date TEXT NOT NULL, rule_type TEXT NOT NULL,
            rule_value TEXT NOT NULL, created_at TEXT
        );
        CREATE TABLE user_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            morning_enabled INTEGER NOT NULL DEFAULT 1,
            morning_time TEXT NOT NULL DEFAULT '08:00',
            evening_enabled INTEGER NOT NULL DEFAULT 1,
            evening_time TEXT NOT NULL DEFAULT '20:00',
            last_morning_sent TEXT, last_evening_sent TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO user_meta (telegram_id, username) VALUES (?, 'olduser')",
        (telegram_id,),
    )
    conn.execute(
        "INSERT INTO plans (plan_date, time_start, title) "
        "VALUES ('2026-01-01', '10:00', 'Старая задача')"
    )
    conn.execute("INSERT INTO user_settings (id) VALUES (1)")
    conn.commit()
    conn.close()


def test_migration_keeps_data(temp_env: Path) -> None:
    path = temp_env / "olduser.db"
    _old_database(path)

    db = dm.ensure_user_db(999, "olduser", "Old")
    try:
        plans_cols = {
            r[1] for r in db.conn.execute("PRAGMA table_info(plans)").fetchall()
        }
        rules_cols = {
            r[1]
            for r in db.conn.execute("PRAGMA table_info(recurring_rules)").fetchall()
        }
        settings_cols = {
            r[1]
            for r in db.conn.execute("PRAGMA table_info(user_settings)").fetchall()
        }
        assert {"reminder_minutes", "reminder_sent", "done_at"} <= plans_cols
        assert "active" in rules_cols
        assert {"blocked", "skip_empty_digest", "quiet_enabled"} <= settings_cols

        items = get_plans_for_date(db, date(2026, 1, 1))
        assert any(item.title == "Старая задача" for item in items)
    finally:
        db.close()


def test_monthly_31_uses_last_day(temp_env: Path) -> None:
    db = dm.ensure_user_db(1, "user", "User")
    try:
        rule_id = add_recurring_rule(
            db, "31-е", None, "10:00", None, date(2026, 1, 1), "monthly", "31"
        )
        row = db.conn.execute(
            "SELECT * FROM recurring_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        assert _rule_occurs_on(row, date(2026, 2, 28)) is True
        assert _rule_occurs_on(row, date(2026, 3, 31)) is True
        assert _rule_occurs_on(row, date(2026, 4, 30)) is True
    finally:
        db.close()


def test_daily_rules_are_not_lost(temp_env: Path) -> None:
    db = dm.ensure_user_db(1, "user", "User")
    try:
        today = date(2026, 1, 10)
        add_plan(db, today, "Разовая", "09:00", None, None)
        add_recurring_rule(db, "Каждый день", None, "08:00", None, today, "interval", "1")

        days, rules = get_scheduled_days(db, today, recurring_horizon_days=5)
        day_set = {d for d, _ in days}
        assert rules
        assert today in day_set
        assert today + timedelta(days=4) in day_set

        counts = get_plan_counts_for_dates(db, [today, today + timedelta(days=1)])
        assert counts[today] == 2  # разовая + ежедневная
        assert counts[today + timedelta(days=1)] == 1
    finally:
        db.close()


def test_demo_cleanup_on_migration(temp_env: Path) -> None:
    path = temp_env / "demos.db"
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
        INSERT INTO user_meta (telegram_id, username) VALUES (7, 'demos');
        INSERT INTO plans (plan_date, time_start, time_end, title)
            VALUES ('2026-01-01', '08:30', NULL, 'сво');
        INSERT INTO plans (plan_date, time_start, time_end, title)
            VALUES ('2026-01-01', '12:00', NULL, 'Настоящая');
        INSERT INTO user_settings (id) VALUES (1);
        """
    )
    conn.commit()
    conn.close()

    db = dm.ensure_user_db(7, "demos", "D")
    titles = [item.title for item in get_plans_for_date(db, date(2026, 1, 1))]
    assert "сво" not in titles
    assert "Настоящая" in titles
    assert db.conn.execute(
        "SELECT demo_cleaned FROM user_settings WHERE id = 1"
    ).fetchone()[0] == 1
    db.close()


def test_index_rebuild_and_identity(temp_env: Path) -> None:
    db = dm.ensure_user_db(111, "alice", "Alice")
    db.close()
    db = dm.ensure_user_db(222, "bob", "Bob")
    db.close()

    dm.INDEX_FILE.unlink(missing_ok=True)
    dm._INDEX_CACHE = None
    dm._INDEX_MTIME = None
    index = dm.ensure_index()
    assert index["111"] == "alice.db"
    assert index["222"] == "bob.db"

    # Ломаем индекс: 111 указывает на чужую базу
    index["111"] = "bob.db"
    dm._save_index(index)
    db = dm.ensure_user_db(111, "alice", "Alice")
    try:
        uid = db.conn.execute("SELECT telegram_id FROM user_meta LIMIT 1").fetchone()[0]
        assert uid == 111
        assert db.path.name != "bob.db"
    finally:
        db.close()
