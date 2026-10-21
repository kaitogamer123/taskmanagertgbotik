"""
Менеджер персональных баз данных пользователей.

У каждого пользователя своя SQLite база в папке PlanesUser/.
Имя файла — его username (без @) или, если username нет, его telegram id.
Первая запись в базе (таблица user_meta) — это id пользователя.

Если username пользователя поменялся, файл базы переименовывается,
но проверка на изменение username делается не чаще раза в 5 минут.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Iterator, Optional

from config import DEFAULT_EVENING_TIME, DEFAULT_MORNING_TIME, PLANES_USER_DIR, USERNAME_RECHECK_INTERVAL
from database.seed import seed_demo_data

INDEX_FILE = PLANES_USER_DIR / "_index.json"

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_\-.а-яА-ЯёЁ]")


def _safe_filename_part(value: str) -> str:
    value = value.strip()
    value = _SAFE_CHARS_RE.sub("_", value)
    return value or "user"


def _load_index() -> dict:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_index(data: dict) -> None:
    INDEX_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _expected_filename(telegram_id: int, username: Optional[str]) -> str:
    base = username if username else str(telegram_id)
    return f"{_safe_filename_part(base)}.db"


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_meta (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT,
            last_checked REAL
        );

        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date TEXT NOT NULL,
            time_start TEXT,
            time_end TEXT,
            title TEXT NOT NULL,
            description TEXT,
            reminder_minutes INTEGER,
            reminder_sent INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS recurring_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            time_start TEXT,
            time_end TEXT,
            start_date TEXT NOT NULL,
            rule_type TEXT NOT NULL,     -- interval | weekday | monthly | yearly
            rule_value TEXT NOT NULL,
            created_at TEXT,
            reminder_minutes INTEGER,
            last_reminder_date TEXT
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            morning_enabled INTEGER NOT NULL DEFAULT 1,
            morning_time TEXT NOT NULL DEFAULT '08:00',
            evening_enabled INTEGER NOT NULL DEFAULT 1,
            evening_time TEXT NOT NULL DEFAULT '20:00',
            last_morning_sent TEXT,
            last_evening_sent TEXT
        );
        """
    )
    conn.commit()
    _migrate_schema(conn)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Добавляет новые колонки в базы, созданные до появления напоминаний."""
    plans_cols = _table_columns(conn, "plans")
    if "reminder_minutes" not in plans_cols:
        conn.execute("ALTER TABLE plans ADD COLUMN reminder_minutes INTEGER")
    if "reminder_sent" not in plans_cols:
        conn.execute("ALTER TABLE plans ADD COLUMN reminder_sent INTEGER NOT NULL DEFAULT 0")

    rules_cols = _table_columns(conn, "recurring_rules")
    if "reminder_minutes" not in rules_cols:
        conn.execute("ALTER TABLE recurring_rules ADD COLUMN reminder_minutes INTEGER")
    if "last_reminder_date" not in rules_cols:
        conn.execute("ALTER TABLE recurring_rules ADD COLUMN last_reminder_date TEXT")

    conn.execute(
        """
        INSERT OR IGNORE INTO user_settings (id, morning_time, evening_time)
        VALUES (1, ?, ?)
        """,
        (DEFAULT_MORNING_TIME, DEFAULT_EVENING_TIME),
    )
    conn.commit()


class UserDB:
    """Небольшая обёртка над sqlite3.Connection для одного пользователя."""

    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "UserDB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def get_db_path(telegram_id: int, username: Optional[str] = None) -> Path:
    index = _load_index()
    key = str(telegram_id)
    if key in index:
        filename = index[key]
    else:
        filename = _expected_filename(telegram_id, username)
        index[key] = filename
        _save_index(index)
    return PLANES_USER_DIR / filename


def ensure_user_db(
    telegram_id: int, username: Optional[str], first_name: Optional[str]
) -> UserDB:
    """Открывает (создавая при необходимости) базу данных пользователя."""
    path = get_db_path(telegram_id, username)
    is_new = not path.exists()

    db = UserDB(path)
    _create_schema(db.conn)

    if is_new:
        db.conn.execute(
            """
            INSERT INTO user_meta (telegram_id, username, first_name, created_at, last_checked)
            VALUES (?, ?, ?, datetime('now'), ?)
            """,
            (telegram_id, username, first_name, time.time()),
        )
        db.conn.commit()
        seed_demo_data(db.conn)
    else:
        row = db.conn.execute(
            "SELECT telegram_id FROM user_meta LIMIT 1"
        ).fetchone()
        if row is None:
            db.conn.execute(
                """
                INSERT INTO user_meta (telegram_id, username, first_name, created_at, last_checked)
                VALUES (?, ?, ?, datetime('now'), ?)
                """,
                (telegram_id, username, first_name, time.time()),
            )
            db.conn.commit()

    return db


def maybe_refresh_username(
    db: UserDB, telegram_id: int, username: Optional[str], first_name: Optional[str]
) -> UserDB:
    """
    Проверяет (не чаще раза в 5 минут), не изменился ли username пользователя.
    Если изменился — переименовывает файл базы данных и обновляет индекс.
    Возвращает (возможно новый) объект UserDB, т.к. при переименовании файла
    соединение нужно переоткрыть.
    """
    row = db.conn.execute(
        "SELECT username, first_name, last_checked FROM user_meta WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()

    now = time.time()
    if row is None:
        db.conn.execute(
            """
            INSERT OR REPLACE INTO user_meta (telegram_id, username, first_name, created_at, last_checked)
            VALUES (?, ?, ?, COALESCE((SELECT created_at FROM user_meta WHERE telegram_id = ?), datetime('now')), ?)
            """,
            (telegram_id, username, first_name, telegram_id, now),
        )
        db.conn.commit()
        return db

    last_checked = row["last_checked"] or 0
    if now - last_checked < USERNAME_RECHECK_INTERVAL:
        return db

    stored_username = row["username"]
    needs_rename = (stored_username or None) != (username or None)

    if not needs_rename:
        db.conn.execute(
            "UPDATE user_meta SET last_checked = ?, first_name = ? WHERE telegram_id = ?",
            (now, first_name, telegram_id),
        )
        db.conn.commit()
        return db

    # username поменялся -> переименовываем файл базы данных
    old_path = db.path
    new_filename = _expected_filename(telegram_id, username)
    new_path = old_path.parent / new_filename

    db.conn.execute(
        "UPDATE user_meta SET username = ?, first_name = ?, last_checked = ? WHERE telegram_id = ?",
        (username, first_name, now, telegram_id),
    )
    db.conn.commit()
    db.close()

    if new_path != old_path:
        counter = 1
        final_path = new_path
        while final_path.exists() and final_path != old_path:
            final_path = new_path.parent / f"{new_path.stem}_{counter}{new_path.suffix}"
            counter += 1
        old_path.rename(final_path)
        new_path = final_path

        index = _load_index()
        index[str(telegram_id)] = new_path.name
        _save_index(index)

    return UserDB(new_path)


def iter_all_user_ids() -> Iterator[int]:
    """Перечисляет telegram_id всех пользователей, у которых есть база данных."""
    for key in _load_index().keys():
        try:
            yield int(key)
        except ValueError:
            continue


def open_user_db_by_id(telegram_id: int) -> Optional[UserDB]:
    """
    Открывает базу данных пользователя по его telegram_id без создания новой
    (используется фоновым планировщиком уведомлений). Возвращает None, если
    пользователь ещё никогда не писал боту.
    """
    index = _load_index()
    filename = index.get(str(telegram_id))
    if not filename:
        return None
    path = PLANES_USER_DIR / filename
    if not path.exists():
        return None
    db = UserDB(path)
    _create_schema(db.conn)
    return db
