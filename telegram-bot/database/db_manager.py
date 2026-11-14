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
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Iterator, Optional

from config import (
    DEFAULT_EVENING_TIME,
    DEFAULT_MORNING_TIME,
    PLANES_USER_DIR,
    USERNAME_RECHECK_INTERVAL,
)

INDEX_FILE = PLANES_USER_DIR / "_index.json"

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_\-.а-яА-ЯёЁ]")

# Кэш _index.json: раньше файл читался с диска на каждое сообщение/кнопку
# и на каждый тик планировщика, теперь читаем только при его изменении.
_INDEX_CACHE: dict | None = None
_INDEX_MTIME: float | None = None

# Схема/миграции каждой базы выполняются один раз за запуск процесса.
_SCHEMA_READY: set = set()


def _safe_filename_part(value: str) -> str:
    value = value.strip()
    value = _SAFE_CHARS_RE.sub("_", value)
    return value or "user"


def _load_index() -> dict:
    global _INDEX_CACHE, _INDEX_MTIME

    try:
        mtime = INDEX_FILE.stat().st_mtime
    except OSError:
        _INDEX_CACHE = {}
        _INDEX_MTIME = None
        return _INDEX_CACHE

    if _INDEX_CACHE is not None and _INDEX_MTIME == mtime:
        return _INDEX_CACHE

    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (json.JSONDecodeError, OSError):
        # При битом файле не теряем ранее загруженный индекс
        data = _INDEX_CACHE or {}

    _INDEX_CACHE = data
    _INDEX_MTIME = mtime
    return data


def _save_index(data: dict) -> None:
    global _INDEX_CACHE, _INDEX_MTIME

    tmp_path = INDEX_FILE.with_name(INDEX_FILE.name + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Атомарная замена: файл индекса не побьётся при падении/перезапуске
    os.replace(tmp_path, INDEX_FILE)
    _INDEX_CACHE = data
    try:
        _INDEX_MTIME = INDEX_FILE.stat().st_mtime
    except OSError:
        _INDEX_MTIME = None


def _expected_filename(telegram_id: int, username: Optional[str]) -> str:
    base = username if username else str(telegram_id)
    return f"{_safe_filename_part(base)}.db"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _create_schema(conn: sqlite3.Connection, is_existing_file: bool = False) -> None:
    had_demo_col_before = "demo_seeded" in _table_columns(conn, "user_settings")
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
            reminder_sent INTEGER NOT NULL DEFAULT 0,
            done_at TEXT
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
            last_reminder_date TEXT,
            excluded_dates TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            morning_enabled INTEGER NOT NULL DEFAULT 1,
            morning_time TEXT NOT NULL DEFAULT '08:00',
            evening_enabled INTEGER NOT NULL DEFAULT 1,
            evening_time TEXT NOT NULL DEFAULT '20:00',
            last_morning_sent TEXT,
            last_evening_sent TEXT,
            utc_offset INTEGER,
            timezone_configured INTEGER NOT NULL DEFAULT 0,
            demo_seeded INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0,
            skip_empty_digest INTEGER NOT NULL DEFAULT 0,
            quiet_enabled INTEGER NOT NULL DEFAULT 0,
            quiet_start TEXT NOT NULL DEFAULT '23:00',
            quiet_end TEXT NOT NULL DEFAULT '08:00'
        );

        CREATE TABLE IF NOT EXISTS note_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_note_folders_name
            ON note_folders(name COLLATE NOCASE);

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER,
            title TEXT,
            body TEXT NOT NULL DEFAULT '',
            note_date TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_notes_folder ON notes(folder_id);

        CREATE TABLE IF NOT EXISTS note_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_note_items_note ON note_items(note_id);

        CREATE TABLE IF NOT EXISTS note_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            file_unique_id TEXT,
            file_type TEXT NOT NULL,
            file_name TEXT,
            caption TEXT,
            message_id INTEGER,
            chat_id INTEGER,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_note_files_note ON note_files(note_id);

        CREATE TABLE IF NOT EXISTS rule_completions (
            rule_id INTEGER NOT NULL,
            occurrence_date TEXT NOT NULL,
            done_at TEXT NOT NULL,
            PRIMARY KEY (rule_id, occurrence_date)
        );

        CREATE TABLE IF NOT EXISTS snoozes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            occurrence_date TEXT,
            title TEXT NOT NULL,
            start_time TEXT,
            remind_at TEXT NOT NULL,
            created_at TEXT
        );
        """
    )
    conn.commit()
    _migrate_schema(
        conn,
        is_existing_file=is_existing_file,
        had_demo_col_before=had_demo_col_before,
    )


def _migrate_schema(
    conn: sqlite3.Connection,
    is_existing_file: bool = False,
    had_demo_col_before: bool = False,
) -> None:
    """Автоматически добавляет недостающие колонки в уже существующие базы пользователей."""
    plans_cols = _table_columns(conn, "plans")
    if "reminder_minutes" not in plans_cols:
        conn.execute("ALTER TABLE plans ADD COLUMN reminder_minutes INTEGER")
    if "reminder_sent" not in plans_cols:
        conn.execute(
            "ALTER TABLE plans ADD COLUMN reminder_sent INTEGER NOT NULL DEFAULT 0"
        )
    if "done_at" not in plans_cols:
        conn.execute("ALTER TABLE plans ADD COLUMN done_at TEXT")

    rules_cols = _table_columns(conn, "recurring_rules")
    if "reminder_minutes" not in rules_cols:
        conn.execute("ALTER TABLE recurring_rules ADD COLUMN reminder_minutes INTEGER")
    if "last_reminder_date" not in rules_cols:
        conn.execute("ALTER TABLE recurring_rules ADD COLUMN last_reminder_date TEXT")
    if "excluded_dates" not in rules_cols:
        conn.execute(
            "ALTER TABLE recurring_rules ADD COLUMN excluded_dates TEXT NOT NULL DEFAULT ''"
        )
    if "active" not in rules_cols:
        conn.execute(
            "ALTER TABLE recurring_rules ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
        )

    settings_cols = _table_columns(conn, "user_settings")
    if "utc_offset" not in settings_cols:
        conn.execute("ALTER TABLE user_settings ADD COLUMN utc_offset INTEGER")
    if "timezone_configured" not in settings_cols:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN timezone_configured INTEGER NOT NULL DEFAULT 0"
        )
    if "demo_seeded" not in settings_cols:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN demo_seeded INTEGER NOT NULL DEFAULT 0"
        )
    if "blocked" not in settings_cols:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0"
        )
    if "skip_empty_digest" not in settings_cols:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN skip_empty_digest INTEGER NOT NULL DEFAULT 0"
        )
    if "quiet_enabled" not in settings_cols:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN quiet_enabled INTEGER NOT NULL DEFAULT 0"
        )
    if "quiet_start" not in settings_cols:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN quiet_start TEXT NOT NULL DEFAULT '23:00'"
        )
    if "quiet_end" not in settings_cols:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN quiet_end TEXT NOT NULL DEFAULT '08:00'"
        )

    # Индексы заметно ускоряют планировщик уведомлений и выборку планов по дню
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_date ON plans(plan_date)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_plans_reminder "
        "ON plans(reminder_sent, reminder_minutes)"
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO user_settings (id, morning_time, evening_time)
        VALUES (1, ?, ?)
        """,
        (DEFAULT_MORNING_TIME, DEFAULT_EVENING_TIME),
    )

    # Если база была создана старой версией бота — не подмешиваем демо-данные поверх планов юзера
    if is_existing_file and not had_demo_col_before:
        conn.execute("UPDATE user_settings SET demo_seeded = 1 WHERE id = 1")

    conn.commit()


class UserDB:
    """Небольшая обёртка над sqlite3.Connection для одного пользователя."""

    def __init__(self, path: Path):
        self.path = path
        # timeout/busy_timeout защищают от "database is locked", если базу
        # в этот момент читает/пишет другая часть бота.
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 5000")
        # NORMAL вместо FULL: меньше fsync на каждый commit. Данные при сбое
        # не портятся, может потеряться только самая последняя транзакция.
        self.conn.execute("PRAGMA synchronous = NORMAL")

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


def _ensure_schema(db: UserDB, is_existing_file: bool, force: bool = False) -> None:
    """
    Выполняет CREATE TABLE / миграции только ОДИН раз за запуск процесса
    для каждого файла БД. Раньше схема пересоздавалась на каждое сообщение,
    на каждую кнопку и на каждый тик планировщика — это давало постоянные
    записи на диск и лишнюю нагрузку на CPU.

    force=True нужен, если файл БД только что создан заново (например, его
    удалили с сервера) — тогда схему надо накатить, несмотря на кэш.
    """
    if not force and db.path in _SCHEMA_READY:
        return
    _create_schema(db.conn, is_existing_file=is_existing_file)
    _SCHEMA_READY.add(db.path)


def _rebuild_index_dict() -> dict:
    """Собирает индекс ID→файл по всем базам в PlanesUser/."""
    index: dict = {}
    for path in sorted(PLANES_USER_DIR.glob("*.db")):
        try:
            conn = sqlite3.connect(path, timeout=5)
            row = conn.execute("SELECT telegram_id FROM user_meta LIMIT 1").fetchone()
            conn.close()
        except (sqlite3.Error, OSError):
            continue
        if row and row[0] is not None:
            index[str(int(row[0]))] = path.name
    return index


def ensure_index() -> dict:
    """
    Гарантирует, что _index.json содержит всех пользователей, у которых есть
    база. Если индекс потерян/побит — пересобирает его по файлам.
    """
    index = _load_index()
    rebuilt = _rebuild_index_dict()
    # Выбрасываем записи, которые указывают на уже удалённые файлы
    merged = {
        key: name
        for key, name in index.items()
        if (PLANES_USER_DIR / name).exists()
    }
    merged.update(rebuilt)  # данные из файлов считаем более достоверными
    if merged and merged != index:
        _save_index(merged)
    return merged


def find_db_for_user(telegram_id: int) -> Optional[Path]:
    """Ищет файл БД пользователя сканированием PlanesUser/ (на случай битого индекса)."""
    for path in sorted(PLANES_USER_DIR.glob("*.db")):
        try:
            conn = sqlite3.connect(path, timeout=5)
            row = conn.execute(
                "SELECT telegram_id FROM user_meta WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            conn.close()
        except (sqlite3.Error, OSError):
            continue
        if row is not None:
            return path
    return None


def _unique_user_path(telegram_id: int) -> Path:
    base = PLANES_USER_DIR / f"{telegram_id}.db"
    path = base
    counter = 1
    while path.exists():
        path = base.with_name(f"{base.stem}_{counter}{base.suffix}")
        counter += 1
    return path


def ensure_user_db(
    telegram_id: int, username: Optional[str], first_name: Optional[str]
) -> UserDB:
    """Открывает (создавая при необходимости) базу данных пользователя."""
    path = get_db_path(telegram_id, username)
    if not path.exists():
        # Индекс мог устареть/потеряться — пробуем найти базу по user_meta
        found = find_db_for_user(telegram_id)
        if found is not None:
            path = found
            index = _load_index()
            index[str(telegram_id)] = path.name
            _save_index(index)
    is_new = not path.exists()

    db = UserDB(path)
    _ensure_schema(db, is_existing_file=not is_new, force=is_new)

    row = db.conn.execute("SELECT telegram_id FROM user_meta LIMIT 1").fetchone()
    if row is not None and int(row["telegram_id"]) != int(telegram_id):
        # Файл принадлежит другому пользователю (битый индекс/коллизия имён).
        # Открываем отдельный файл, чтобы не смешать данные.
        db.close()
        path = _unique_user_path(telegram_id)
        db = UserDB(path)
        _ensure_schema(db, is_existing_file=False, force=True)
        index = _load_index()
        index[str(telegram_id)] = path.name
        _save_index(index)
        row = None

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
    (используется фоновым планировщиком уведомлений).
    """
    index = _load_index()
    filename = index.get(str(telegram_id))
    if not filename:
        return None
    path = PLANES_USER_DIR / filename
    if not path.exists():
        found = find_db_for_user(telegram_id)
        if found is None:
            return None
        path = found
        index = _load_index()
        index[str(telegram_id)] = path.name
        _save_index(index)
    db = UserDB(path)
    _ensure_schema(db, is_existing_file=True)
    return db
