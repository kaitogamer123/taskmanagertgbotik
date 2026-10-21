"""
Работа с планами (разовыми и повторяющимися) внутри базы данных пользователя.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from database.db_manager import UserDB


@dataclass
class PlanItem:
    """Единая обёртка над обычным планом и повторяющейся задачей для вывода в день."""

    kind: str  # "plan" | "recur"
    source_id: int
    time_start: Optional[str]
    time_end: Optional[str]
    title: str
    description: Optional[str]
    reminder_minutes: Optional[int] = None

    def sort_key(self):
        return (0 if self.time_start else 1, self.time_start or "99:99")

    def time_label(self) -> str:
        if self.time_start and self.time_end:
            return f"{self.time_start}-{self.time_end}"
        if self.time_start:
            return self.time_start
        return "Без времени"


def add_plan(
    db: UserDB,
    plan_date: date,
    title: str,
    time_start: Optional[str],
    time_end: Optional[str],
    description: Optional[str],
    reminder_minutes: Optional[int] = None,
) -> int:
    cur = db.conn.execute(
        """
        INSERT INTO plans (plan_date, time_start, time_end, title, description, reminder_minutes, reminder_sent)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (plan_date.isoformat(), time_start, time_end, title, description, reminder_minutes or None),
    )
    db.conn.commit()
    return cur.lastrowid


def add_recurring_rule(
    db: UserDB,
    title: str,
    description: Optional[str],
    time_start: Optional[str],
    time_end: Optional[str],
    start_date: date,
    rule_type: str,
    rule_value: str,
    reminder_minutes: Optional[int] = None,
) -> int:
    cur = db.conn.execute(
        """
        INSERT INTO recurring_rules
            (title, description, time_start, time_end, start_date, rule_type, rule_value, created_at, reminder_minutes)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
        """,
        (
            title,
            description,
            time_start,
            time_end,
            start_date.isoformat(),
            rule_type,
            rule_value,
            reminder_minutes or None,
        ),
    )
    db.conn.commit()
    return cur.lastrowid


def update_plan_reminder(db: UserDB, plan_id: int, reminder_minutes: Optional[int]) -> None:
    db.conn.execute(
        "UPDATE plans SET reminder_minutes = ?, reminder_sent = 0 WHERE id = ?",
        (reminder_minutes or None, plan_id),
    )
    db.conn.commit()


def update_rule_reminder(db: UserDB, rule_id: int, reminder_minutes: Optional[int]) -> None:
    db.conn.execute(
        "UPDATE recurring_rules SET reminder_minutes = ?, last_reminder_date = NULL WHERE id = ?",
        (reminder_minutes or None, rule_id),
    )
    db.conn.commit()


def _rule_occurs_on(rule: sqlite3.Row, d: date) -> bool:
    start_date = datetime.strptime(rule["start_date"], "%Y-%m-%d").date()
    if d < start_date:
        return False

    rule_type = rule["rule_type"]
    rule_value = rule["rule_value"]

    if rule_type == "interval":
        n = int(rule_value)
        if n <= 0:
            return False
        return (d - start_date).days % n == 0

    if rule_type == "weekday":
        allowed = {int(x) for x in rule_value.split(",") if x != ""}
        return d.weekday() in allowed

    if rule_type == "monthly":
        day_of_month = int(rule_value)
        return d.day == day_of_month

    if rule_type == "yearly":
        day_, month_ = (int(x) for x in rule_value.split("-"))
        return d.day == day_ and d.month == month_

    return False


def get_plans_for_date(db: UserDB, d: date) -> list[PlanItem]:
    items: list[PlanItem] = []

    plan_rows = db.conn.execute(
        "SELECT * FROM plans WHERE plan_date = ? ORDER BY id", (d.isoformat(),)
    ).fetchall()
    for row in plan_rows:
        items.append(
            PlanItem(
                kind="plan",
                source_id=row["id"],
                time_start=row["time_start"],
                time_end=row["time_end"],
                title=row["title"],
                description=row["description"],
                reminder_minutes=row["reminder_minutes"],
            )
        )

    rule_rows = db.conn.execute("SELECT * FROM recurring_rules").fetchall()
    for rule in rule_rows:
        if _rule_occurs_on(rule, d):
            items.append(
                PlanItem(
                    kind="recur",
                    source_id=rule["id"],
                    time_start=rule["time_start"],
                    time_end=rule["time_end"],
                    title=rule["title"],
                    description=rule["description"],
                    reminder_minutes=rule["reminder_minutes"],
                )
            )

    items.sort(key=lambda it: it.sort_key())
    return items


def get_plan_row(db: UserDB, plan_id: int) -> Optional[sqlite3.Row]:
    return db.conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()


def get_rule_row(db: UserDB, rule_id: int) -> Optional[sqlite3.Row]:
    return db.conn.execute(
        "SELECT * FROM recurring_rules WHERE id = ?", (rule_id,)
    ).fetchone()


def delete_plan(db: UserDB, plan_id: int) -> None:
    db.conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    db.conn.commit()


def delete_rule(db: UserDB, rule_id: int) -> None:
    db.conn.execute("DELETE FROM recurring_rules WHERE id = ?", (rule_id,))
    db.conn.commit()
