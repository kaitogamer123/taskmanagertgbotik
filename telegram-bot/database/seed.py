"""
Тестовое (демонстрационное) расписание, которое автоматически
добавляется в базу данных каждого нового пользователя,
чтобы сразу было что посмотреть в /MyPlans.
"""
from __future__ import annotations

import sqlite3
from datetime import date


def _nearest_future_date(month: int, day: int, weekday: int) -> date:
    """
    Находит ближайший год, в котором `month`.`day` выпадает на
    указанный день недели (weekday, 0=понедельник).
    """
    year = date.today().year
    for offset in range(0, 15):
        candidate_year = year + offset
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if candidate.weekday() == weekday and candidate >= date.today().replace(year=candidate_year) - candidate.resolution:
            return candidate
    # fallback - просто текущий год
    return date(year, month, day)


def seed_demo_data(conn: sqlite3.Connection) -> None:
    """Наполняет свежесозданную базу тестовым расписанием пользователя."""

    # Среда 21.10, Четверг 22.10, Пятница 23.10, Суббота 24.10, Воскресенье 25.10
    # подбираем год, в котором 21.10 выпадает на среду, чтобы всё совпадало
    wednesday = _nearest_future_date(10, 21, weekday=2)
    thursday = wednesday.replace(day=22)
    saturday = wednesday.replace(day=24)
    sunday = wednesday.replace(day=25)

    rows = [
        # plan_date, time_start, time_end, title, description
        (wednesday.isoformat(), "08:30", None, "сво", None),
        (thursday.isoformat(), "08:00", "08:30", "сво", None),
        (thursday.isoformat(), "08:30", "09:00", "математика", None),
        (thursday.isoformat(), "14:10", "15:00", "Русский диктант", None),
        # пятница 23.10 — специально без планов (пример свободного дня)
        (
            saturday.isoformat(),
            None,
            None,
            "Погулять со Славой если сможет + убрать пол+диван",
            None,
        ),
        (
            sunday.isoformat(),
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
