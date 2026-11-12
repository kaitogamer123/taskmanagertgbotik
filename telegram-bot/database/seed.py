"""
Тестовое (демонстрационное) расписание, которое автоматически
добавляется в базу данных каждого нового пользователя (с учётом его
настроенного часового пояса), чтобы сразу было что посмотреть в /MyPlans.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Optional

from utils.clock import now_local


def seed_demo_data(conn: sqlite3.Connection, today: Optional[date] = None) -> None:
    """
    Наполняет свежесозданную базу тестовым расписанием на ближайшую неделю
    относительно сегодняшнего дня пользователя `today`.
    """
    base = today or now_local().date()
    day0 = base
    day1 = base + timedelta(days=1)
    # day2 (base + 2 дня) — специально без планов (пример свободного дня)
    day3 = base + timedelta(days=3)
    day4 = base + timedelta(days=4)

    rows = [
        # plan_date, time_start, time_end, title, description
        (day0.isoformat(), "08:30", None, "сво", None),
        (day1.isoformat(), "08:00", "08:30", "сво", None),
        (day1.isoformat(), "08:30", "09:00", "математика", None),
        (day1.isoformat(), "14:10", "15:00", "Русский диктант", None),
        (
            day3.isoformat(),
            None,
            None,
            "Погулять со Славой если сможет + убрать пол+диван",
            None,
        ),
        (
            day4.isoformat(),
            None,
            None,
            "В понедельник проверочная по русскому",
            "Сделать дз, подготовиться к проверочной.",
        ),
    ]

    conn.executemany(
        """
        INSERT INTO plans (plan_date, time_start, time_end, title, description)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
