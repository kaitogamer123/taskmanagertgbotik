"""Настройки уведомлений пользователя (таблица user_settings, одна строка id=1)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from database.db_manager import UserDB


@dataclass
class NotifySettings:
    morning_enabled: bool
    morning_time: str
    evening_enabled: bool
    evening_time: str
    last_morning_sent: Optional[str]
    last_evening_sent: Optional[str]


def get_settings(db: UserDB) -> NotifySettings:
    row = db.conn.execute(
        "SELECT morning_enabled, morning_time, evening_enabled, evening_time, "
        "last_morning_sent, last_evening_sent FROM user_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        db.conn.execute(
            "INSERT OR IGNORE INTO user_settings (id, morning_time, evening_time) VALUES (1, '08:00', '20:00')"
        )
        db.conn.commit()
        return get_settings(db)
    return NotifySettings(
        morning_enabled=bool(row["morning_enabled"]),
        morning_time=row["morning_time"],
        evening_enabled=bool(row["evening_enabled"]),
        evening_time=row["evening_time"],
        last_morning_sent=row["last_morning_sent"],
        last_evening_sent=row["last_evening_sent"],
    )


def set_morning_time(db: UserDB, time_str: str) -> None:
    db.conn.execute(
        "UPDATE user_settings SET morning_time = ?, morning_enabled = 1 WHERE id = 1",
        (time_str,),
    )
    db.conn.commit()


def set_evening_time(db: UserDB, time_str: str) -> None:
    db.conn.execute(
        "UPDATE user_settings SET evening_time = ?, evening_enabled = 1 WHERE id = 1",
        (time_str,),
    )
    db.conn.commit()


def toggle_morning(db: UserDB, enabled: bool) -> None:
    db.conn.execute(
        "UPDATE user_settings SET morning_enabled = ? WHERE id = 1", (1 if enabled else 0,)
    )
    db.conn.commit()


def toggle_evening(db: UserDB, enabled: bool) -> None:
    db.conn.execute(
        "UPDATE user_settings SET evening_enabled = ? WHERE id = 1", (1 if enabled else 0,)
    )
    db.conn.commit()


def mark_morning_sent(conn: sqlite3.Connection, today_iso: str) -> None:
    conn.execute("UPDATE user_settings SET last_morning_sent = ? WHERE id = 1", (today_iso,))
    conn.commit()


def mark_evening_sent(conn: sqlite3.Connection, today_iso: str) -> None:
    conn.execute("UPDATE user_settings SET last_evening_sent = ? WHERE id = 1", (today_iso,))
    conn.commit()
