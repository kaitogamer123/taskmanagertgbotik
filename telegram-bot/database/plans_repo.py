"""
Работа с планами (разовыми и повторяющимися) внутри базы данных пользователя.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
    rule_type: Optional[str] = None
    rule_value: Optional[str] = None

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
        (
            plan_date.isoformat(),
            time_start,
            time_end,
            title,
            description,
            reminder_minutes or None,
        ),
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
            (title, description, time_start, time_end, start_date, rule_type, rule_value, created_at, reminder_minutes, excluded_dates)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, '')
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


def update_plan_reminder(
    db: UserDB, plan_id: int, reminder_minutes: Optional[int]
) -> None:
    db.conn.execute(
        "UPDATE plans SET reminder_minutes = ?, reminder_sent = 0 WHERE id = ?",
        (reminder_minutes or None, plan_id),
    )
    db.conn.commit()


def update_rule_reminder(
    db: UserDB, rule_id: int, reminder_minutes: Optional[int]
) -> None:
    db.conn.execute(
        "UPDATE recurring_rules SET reminder_minutes = ?, last_reminder_date = NULL WHERE id = ?",
        (reminder_minutes or None, rule_id),
    )
    db.conn.commit()


def _excluded_set(rule: sqlite3.Row) -> set[str]:
    raw = rule["excluded_dates"] if "excluded_dates" in rule.keys() else ""
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _rule_occurs_on(rule: sqlite3.Row, d: date) -> bool:
    if d.isoformat() in _excluded_set(rule):
        return False

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


def get_plans_for_date(
    db: UserDB, d: date, rules: Optional[list[sqlite3.Row]] = None
) -> list[PlanItem]:
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

    # Если правила уже загружены вызывающим кодом — не читаем их из БД повторно
    rule_rows = rules if rules is not None else get_all_recurring_rules(db)
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
                    rule_type=rule["rule_type"],
                    rule_value=rule["rule_value"],
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


def get_all_recurring_rules(db: UserDB) -> list[sqlite3.Row]:
    return db.conn.execute("SELECT * FROM recurring_rules ORDER BY id").fetchall()


def delete_plan(db: UserDB, plan_id: int) -> None:
    db.conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    db.conn.commit()


def delete_rule(db: UserDB, rule_id: int) -> None:
    db.conn.execute("DELETE FROM recurring_rules WHERE id = ?", (rule_id,))
    db.conn.commit()


def exclude_rule_date(db: UserDB, rule_id: int, d: date) -> None:
    """Скрывает повторяющуюся задачу только на одну конкретную дату d."""
    row = get_rule_row(db, rule_id)
    if row is None:
        return
    excluded = _excluded_set(row)
    excluded.add(d.isoformat())
    db.conn.execute(
        "UPDATE recurring_rules SET excluded_dates = ? WHERE id = ?",
        (",".join(sorted(excluded)), rule_id),
    )
    db.conn.commit()


def delete_all_for_date(db: UserDB, d: date) -> int:
    """
    Удаляет все задачи на конкретный день `d`
    (разовые удаляются из таблицы plans, повторяющиеся скрываются на этот день).
    Возвращает количество удалённых задач.
    """
    items = get_plans_for_date(db, d)
    if not items:
        return 0
    db.conn.execute("DELETE FROM plans WHERE plan_date = ?", (d.isoformat(),))
    for item in items:
        if item.kind == "recur":
            exclude_rule_date(db, item.source_id, d)
    db.conn.commit()
    return len(items)


def get_scheduled_days(
    db: UserDB, today: date, recurring_horizon_days: int = 14
) -> tuple[list[tuple[date, list[PlanItem]]], list[sqlite3.Row]]:
    """
    Возвращает:
      1) отсортированный список (date, items) для всех дней, где есть задачи:
         - все даты из таблицы разовых задач `plans` (включая будущие на любой срок);
         - плюс ближайшие `recurring_horizon_days` дней для неповторяющихся-ежедневно
           правил (а если разовых задач нет вообще — и для ежедневных на неделю вперёд,
           чтобы пользователь сразу видел ближайшие дни кнопками);
      2) полный список всех повторяющихся правил `recurring_rules`.
    """
    candidate_dates: set[date] = set()

    plan_date_rows = db.conn.execute(
        "SELECT DISTINCT plan_date FROM plans ORDER BY plan_date"
    ).fetchall()
    for row in plan_date_rows:
        try:
            candidate_dates.add(date.fromisoformat(row["plan_date"]))
        except ValueError:
            continue

    rules = get_all_recurring_rules(db)
    non_daily_rules = [
        r for r in rules if not (r["rule_type"] == "interval" and r["rule_value"] == "1")
    ]
    daily_rules = [
        r for r in rules if (r["rule_type"] == "interval" and r["rule_value"] == "1")
    ]

    if non_daily_rules:
        for offset in range(recurring_horizon_days):
            d = today + timedelta(days=offset)
            if any(_rule_occurs_on(r, d) for r in non_daily_rules):
                candidate_dates.add(d)

    if daily_rules and not candidate_dates:
        for offset in range(7):
            d = today + timedelta(days=offset)
            if any(_rule_occurs_on(r, d) for r in daily_rules):
                candidate_dates.add(d)

    # Сначала показываем сегодня и будущие дни по возрастанию, затем (если остались) прошлые
    upcoming = sorted(d for d in candidate_dates if d >= today)
    past = sorted(d for d in candidate_dates if d < today)
    ordered_dates = upcoming + past

    result: list[tuple[date, list[PlanItem]]] = []
    for d in ordered_dates:
        items = get_plans_for_date(db, d, rules=rules)
        if items:
            result.append((d, items))

    return result, rules


def get_plan_counts_for_dates(db: UserDB, dates: list[date]) -> dict[date, int]:
    """
    Возвращает количество задач для каждой даты из `dates` за 2 SQL-запроса
    (раньше клавиатура недели вызывала get_plans_for_date 7 раз, и каждый
    раз заново читала ВСЕ повторяющиеся правила).
    """
    counts: dict[date, int] = {d: 0 for d in dates}
    if not dates:
        return counts

    placeholders = ",".join("?" for _ in dates)
    rows = db.conn.execute(
        f"""
        SELECT plan_date, COUNT(*) AS cnt
        FROM plans
        WHERE plan_date IN ({placeholders})
        GROUP BY plan_date
        """,
        [d.isoformat() for d in dates],
    ).fetchall()
    for row in rows:
        try:
            counts[date.fromisoformat(row["plan_date"])] = int(row["cnt"])
        except ValueError:
            continue

    rules = get_all_recurring_rules(db)
    if rules:
        for d in dates:
            counts[d] += sum(1 for rule in rules if _rule_occurs_on(rule, d))

    return counts
