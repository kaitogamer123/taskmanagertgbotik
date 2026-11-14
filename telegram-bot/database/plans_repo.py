"""
Работа с планами (разовыми и повторяющимися) внутри базы данных пользователя.
"""
from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass, field
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
    done_at: Optional[str] = None
    reminders: list[int] = field(default_factory=list)

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
    if reminder_minutes and reminder_minutes > 0:
        add_reminder(db, "plan", int(cur.lastrowid), int(reminder_minutes))
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
    if reminder_minutes and reminder_minutes > 0:
        add_reminder(db, "recur", int(cur.lastrowid), int(reminder_minutes))
    return cur.lastrowid


def _insert_reminder_row(
    db: UserDB, kind: str, source_id: int, minutes: int
) -> None:
    if minutes <= 0:
        return
    db.conn.execute(
        """
        INSERT OR IGNORE INTO task_reminders
            (kind, source_id, minutes, created_at)
        VALUES (?, ?, ?, datetime('now','localtime'))
        """,
        (kind, source_id, int(minutes)),
    )


def get_reminders(db: UserDB, kind: str, source_id: int) -> list[int]:
    rows = db.conn.execute(
        "SELECT minutes FROM task_reminders "
        "WHERE kind = ? AND source_id = ? ORDER BY minutes DESC",
        (kind, source_id),
    ).fetchall()
    return [int(row["minutes"]) for row in rows]


def _sync_legacy_reminder(db: UserDB, kind: str, source_id: int) -> None:
    values = get_reminders(db, kind, source_id)
    legacy = max(values) if values else None
    table = "plans" if kind == "plan" else "recurring_rules"
    db.conn.execute(
        f"UPDATE {table} SET reminder_minutes = ? WHERE id = ?",
        (legacy, source_id),
    )


def add_reminder(db: UserDB, kind: str, source_id: int, minutes: int) -> None:
    _insert_reminder_row(db, kind, source_id, int(minutes))
    _sync_legacy_reminder(db, kind, source_id)
    db.conn.commit()


def _clear_reminders(db: UserDB, kind: str, source_id: int) -> None:
    db.conn.execute(
        "DELETE FROM reminder_sent WHERE reminder_id IN "
        "(SELECT id FROM task_reminders WHERE kind = ? AND source_id = ?)",
        (kind, source_id),
    )
    db.conn.execute(
        "DELETE FROM task_reminders WHERE kind = ? AND source_id = ?",
        (kind, source_id),
    )


def set_reminders(
    db: UserDB, kind: str, source_id: int, minutes_list: list[int]
) -> None:
    _clear_reminders(db, kind, source_id)
    for minutes in sorted({int(m) for m in minutes_list if int(m) > 0}):
        _insert_reminder_row(db, kind, source_id, minutes)
    _sync_legacy_reminder(db, kind, source_id)
    db.conn.commit()


def delete_reminder(
    db: UserDB, kind: str, source_id: int, minutes: int
) -> None:
    row = db.conn.execute(
        "SELECT id FROM task_reminders "
        "WHERE kind = ? AND source_id = ? AND minutes = ?",
        (kind, source_id, int(minutes)),
    ).fetchone()
    if row is None:
        return
    db.conn.execute(
        "DELETE FROM reminder_sent WHERE reminder_id = ?", (row["id"],)
    )
    db.conn.execute("DELETE FROM task_reminders WHERE id = ?", (row["id"],))
    _sync_legacy_reminder(db, kind, source_id)
    db.conn.commit()


def mark_reminder_sent(
    db: UserDB, reminder_id: int, occurrence_date: str
) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO reminder_sent
            (reminder_id, occurrence_date, sent_at)
        VALUES (?, ?, datetime('now','localtime'))
        """,
        (reminder_id, occurrence_date),
    )
    db.conn.commit()


def is_reminder_sent(
    db: UserDB, reminder_id: int, occurrence_date: str
) -> bool:
    row = db.conn.execute(
        "SELECT 1 FROM reminder_sent "
        "WHERE reminder_id = ? AND occurrence_date = ?",
        (reminder_id, occurrence_date),
    ).fetchone()
    return row is not None


def clear_reminder_marks(
    db: UserDB, kind: str, source_id: int, occurrence_date: Optional[str] = None
) -> None:
    if occurrence_date is None:
        db.conn.execute(
            "DELETE FROM reminder_sent WHERE reminder_id IN "
            "(SELECT id FROM task_reminders WHERE kind = ? AND source_id = ?)",
            (kind, source_id),
        )
    else:
        db.conn.execute(
            "DELETE FROM reminder_sent WHERE occurrence_date = ? AND reminder_id IN "
            "(SELECT id FROM task_reminders WHERE kind = ? AND source_id = ?)",
            (occurrence_date, kind, source_id),
        )
    db.conn.commit()


def update_plan_reminder(
    db: UserDB, plan_id: int, reminder_minutes: Optional[int]
) -> None:
    set_reminders(
        db, "plan", plan_id, [int(reminder_minutes)] if reminder_minutes and reminder_minutes > 0 else []
    )
    db.conn.execute(
        "UPDATE plans SET reminder_minutes = ?, reminder_sent = 0 WHERE id = ?",
        (reminder_minutes or None, plan_id),
    )
    db.conn.commit()


def update_rule_reminder(
    db: UserDB, rule_id: int, reminder_minutes: Optional[int]
) -> None:
    set_reminders(
        db, "recur", rule_id, [int(reminder_minutes)] if reminder_minutes and reminder_minutes > 0 else []
    )
    db.conn.execute(
        "UPDATE recurring_rules SET reminder_minutes = ?, last_reminder_date = NULL "
        "WHERE id = ?",
        (reminder_minutes or None, rule_id),
    )
    db.conn.commit()


def _excluded_set(rule: sqlite3.Row) -> set[str]:
    raw = rule["excluded_dates"] if "excluded_dates" in rule.keys() else ""
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _rule_occurs_on(rule: sqlite3.Row, d: date) -> bool:
    if "active" in rule.keys() and not rule["active"]:
        return False

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
        if not 1 <= day_of_month <= 31:
            return False
        # 31-е число в коротких месяцах — это последний день месяца
        last_day = calendar.monthrange(d.year, d.month)[1]
        return d.day == min(day_of_month, last_day)

    if rule_type == "yearly":
        day_, month_ = (int(x) for x in rule_value.split("-"))
        return d.day == day_ and d.month == month_

    return False


def get_plans_for_date(
    db: UserDB, d: date, rules: Optional[list[sqlite3.Row]] = None
) -> list[PlanItem]:
    items: list[PlanItem] = []

    reminders_map: dict[tuple[str, int], list[int]] = {}
    for reminder in db.conn.execute(
        "SELECT kind, source_id, minutes FROM task_reminders "
        "ORDER BY minutes DESC"
    ):
        reminders_map.setdefault(
            (reminder["kind"], int(reminder["source_id"])), []
        ).append(int(reminder["minutes"]))

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
                done_at=row["done_at"],
                reminders=reminders_map.get(("plan", int(row["id"])), []),
            )
        )

    # Если правила уже загружены вызывающим кодом — не читаем их из БД повторно
    rule_rows = rules if rules is not None else get_all_recurring_rules(db)
    done_rules = {
        int(row["rule_id"]): row["done_at"]
        for row in db.conn.execute(
            "SELECT rule_id, done_at FROM rule_completions WHERE occurrence_date = ?",
            (d.isoformat(),),
        ).fetchall()
    }
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
                    done_at=done_rules.get(int(rule["id"])),
                    reminders=reminders_map.get(("recur", int(rule["id"])), []),
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
    _clear_reminders(db, "plan", plan_id)
    db.conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    db.conn.commit()


def delete_rule(db: UserDB, rule_id: int) -> None:
    _clear_reminders(db, "recur", rule_id)
    db.conn.execute("DELETE FROM rule_completions WHERE rule_id = ?", (rule_id,))
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
    db.conn.execute(
        "DELETE FROM reminder_sent WHERE occurrence_date = ? AND reminder_id IN "
        "(SELECT id FROM task_reminders WHERE kind = 'recur' AND source_id = ?)",
        (d.isoformat(), rule_id),
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
    plan_ids = [
        int(row["id"])
        for row in db.conn.execute(
            "SELECT id FROM plans WHERE plan_date = ?", (d.isoformat(),)
        ).fetchall()
    ]
    for plan_id in plan_ids:
        _clear_reminders(db, "plan", plan_id)
    db.conn.execute(
        "DELETE FROM reminder_sent WHERE occurrence_date = ?", (d.isoformat(),)
    )
    db.conn.execute("DELETE FROM plans WHERE plan_date = ?", (d.isoformat(),))
    db.conn.execute(
        "DELETE FROM rule_completions WHERE occurrence_date = ?", (d.isoformat(),)
    )
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
         - плюс ближайшие `recurring_horizon_days` дней для всех повторяющихся
           правил (включая ежедневные);
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
    if rules:
        # Ежедневные и любые другие правила добавляем на весь горизонт.
        # Раньше daily-rules терялись, если у пользователя была хоть одна
        # разовая задача (условие `and not candidate_dates`).
        for offset in range(recurring_horizon_days):
            d = today + timedelta(days=offset)
            if any(_rule_occurs_on(r, d) for r in rules):
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


def toggle_plan_done(db: UserDB, plan_id: int, done: bool) -> None:
    if done:
        db.conn.execute(
            "UPDATE plans SET done_at = datetime('now','localtime') WHERE id = ?",
            (plan_id,),
        )
    else:
        db.conn.execute(
            "UPDATE plans SET done_at = NULL WHERE id = ?", (plan_id,)
        )
    db.conn.commit()


def is_rule_done(db: UserDB, rule_id: int, d: date) -> bool:
    row = db.conn.execute(
        "SELECT 1 FROM rule_completions WHERE rule_id = ? AND occurrence_date = ?",
        (rule_id, d.isoformat()),
    ).fetchone()
    return row is not None


def toggle_rule_done(db: UserDB, rule_id: int, d: date, done: bool) -> None:
    if done:
        db.conn.execute(
            """
            INSERT OR REPLACE INTO rule_completions
                (rule_id, occurrence_date, done_at)
            VALUES (?, ?, datetime('now','localtime'))
            """,
            (rule_id, d.isoformat()),
        )
    else:
        db.conn.execute(
            "DELETE FROM rule_completions WHERE rule_id = ? AND occurrence_date = ?",
            (rule_id, d.isoformat()),
        )
    db.conn.commit()


def toggle_rule_active(db: UserDB, rule_id: int) -> Optional[bool]:
    row = db.conn.execute(
        "SELECT active FROM recurring_rules WHERE id = ?", (rule_id,)
    ).fetchone()
    if row is None:
        return None
    new_active = 0 if row["active"] else 1
    db.conn.execute(
        "UPDATE recurring_rules SET active = ? WHERE id = ?", (new_active, rule_id)
    )
    db.conn.commit()
    return bool(new_active)


def search_plans(db: UserDB, query: str, limit: int = 10) -> list[sqlite3.Row]:
    like = f"%{query.strip()}%"
    return db.conn.execute(
        """
        SELECT * FROM plans
        WHERE title LIKE ? OR description LIKE ?
        ORDER BY plan_date DESC, id DESC
        LIMIT ?
        """,
        (like, like, limit),
    ).fetchall()


def search_rules(db: UserDB, query: str, limit: int = 10) -> list[sqlite3.Row]:
    like = f"%{query.strip()}%"
    return db.conn.execute(
        """
        SELECT * FROM recurring_rules
        WHERE title LIKE ? OR description LIKE ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (like, like, limit),
    ).fetchall()


def count_done_plans(db: UserDB, since: date) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) AS cnt FROM plans WHERE done_at IS NOT NULL AND done_at >= ?",
        (since.isoformat(),),
    ).fetchone()
    return int(row["cnt"])


def count_done_rules(db: UserDB, since: date) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) AS cnt FROM rule_completions WHERE done_at >= ?",
        (since.isoformat(),),
    ).fetchone()
    return int(row["cnt"])


def count_active_plans(db: UserDB, today: date) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) AS cnt FROM plans WHERE done_at IS NULL AND plan_date >= ?",
        (today.isoformat(),),
    ).fetchone()
    return int(row["cnt"])


def count_active_rules(db: UserDB) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) AS cnt FROM recurring_rules WHERE active = 1"
    ).fetchone()
    return int(row["cnt"])


def add_snooze(
    db: UserDB,
    kind: str,
    source_id: int,
    occurrence_date: Optional[str],
    title: str,
    start_time: Optional[str],
    remind_at: str,
) -> int:
    cur = db.conn.execute(
        """
        INSERT INTO snoozes
            (kind, source_id, occurrence_date, title, start_time, remind_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        """,
        (kind, source_id, occurrence_date, title, start_time, remind_at),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def due_snoozes(db: UserDB, now_iso: str) -> list[sqlite3.Row]:
    return db.conn.execute(
        "SELECT * FROM snoozes WHERE remind_at <= ? ORDER BY remind_at, id",
        (now_iso,),
    ).fetchall()


def delete_snooze(db: UserDB, snooze_id: int) -> None:
    db.conn.execute("DELETE FROM snoozes WHERE id = ?", (snooze_id,))
    db.conn.commit()


_UNSET = object()


def update_plan(
    db: UserDB,
    plan_id: int,
    title: object = _UNSET,
    description: object = _UNSET,
    plan_date: object = _UNSET,
    time_start: object = _UNSET,
    time_end: object = _UNSET,
) -> None:
    sets: list[str] = []
    params: list[object] = []
    reset_reminder = False
    if title is not _UNSET:
        sets.append("title = ?")
        params.append(title)
    if description is not _UNSET:
        sets.append("description = ?")
        params.append(description)
    if plan_date is not _UNSET:
        sets.append("plan_date = ?")
        params.append(
            plan_date.isoformat() if isinstance(plan_date, date) else plan_date
        )
        reset_reminder = True
    if time_start is not _UNSET:
        sets.append("time_start = ?")
        params.append(time_start)
        reset_reminder = True
    if time_end is not _UNSET:
        sets.append("time_end = ?")
        params.append(time_end)
    if reset_reminder:
        sets.append("reminder_sent = 0")
    params.append(plan_id)
    if sets:
        db.conn.execute(f"UPDATE plans SET {', '.join(sets)} WHERE id = ?", params)
        if reset_reminder:
            db.conn.execute(
                "DELETE FROM reminder_sent WHERE reminder_id IN "
                "(SELECT id FROM task_reminders WHERE kind = 'plan' AND source_id = ?)",
                (plan_id,),
            )
        db.conn.commit()


def update_rule(
    db: UserDB,
    rule_id: int,
    title: object = _UNSET,
    description: object = _UNSET,
    start_date: object = _UNSET,
    time_start: object = _UNSET,
    time_end: object = _UNSET,
) -> None:
    sets: list[str] = []
    params: list[object] = []
    reset_reminder = False
    if title is not _UNSET:
        sets.append("title = ?")
        params.append(title)
    if description is not _UNSET:
        sets.append("description = ?")
        params.append(description)
    if start_date is not _UNSET:
        sets.append("start_date = ?")
        params.append(
            start_date.isoformat() if isinstance(start_date, date) else start_date
        )
    if time_start is not _UNSET:
        sets.append("time_start = ?")
        params.append(time_start)
        sets.append("last_reminder_date = NULL")
        reset_reminder = True
    if time_end is not _UNSET:
        sets.append("time_end = ?")
        params.append(time_end)
    params.append(rule_id)
    if sets:
        db.conn.execute(
            f"UPDATE recurring_rules SET {', '.join(sets)} WHERE id = ?", params
        )
        if reset_reminder:
            db.conn.execute(
                "DELETE FROM reminder_sent WHERE reminder_id IN "
                "(SELECT id FROM task_reminders WHERE kind = 'recur' AND source_id = ?)",
                (rule_id,),
            )
        db.conn.commit()
