"""Шаблоны задач: сохранённые заготовки названия/описания/времени."""
from __future__ import annotations

import sqlite3
from typing import Optional

from database.db_manager import UserDB


def create_template(
    db: UserDB,
    title: str,
    description: Optional[str],
    time_start: Optional[str],
    time_end: Optional[str],
    reminder_minutes: Optional[int] = None,
) -> int:
    cur = db.conn.execute(
        """
        INSERT INTO task_templates
            (title, description, time_start, time_end, reminder_minutes, created_at)
        VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))
        """,
        (title, description, time_start, time_end, reminder_minutes or None),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def list_templates(db: UserDB) -> list[sqlite3.Row]:
    return db.conn.execute(
        "SELECT * FROM task_templates ORDER BY id DESC"
    ).fetchall()


def get_template(db: UserDB, template_id: int) -> Optional[sqlite3.Row]:
    return db.conn.execute(
        "SELECT * FROM task_templates WHERE id = ?", (template_id,)
    ).fetchone()


def delete_template(db: UserDB, template_id: int) -> None:
    db.conn.execute("DELETE FROM task_templates WHERE id = ?", (template_id,))
    db.conn.commit()
