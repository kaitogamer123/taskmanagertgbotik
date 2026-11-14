from __future__ import annotations

from datetime import date

import pytest

from utils.date_utils import parse_day_month, parse_natural_date, parse_time
from utils.reminder_utils import parse_reminder_offset
from utils.repeat_parser import parse_repeat_phrase


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("21:00", "21:00"),
        ("9 вечера", "21:00"),
        ("9:30 утра", "09:30"),
        ("12 ночи", "00:00"),
        ("11 ночи", "23:00"),
        ("2 ночи", "02:00"),
        ("полдень", "12:00"),
        ("полночь", "00:00"),
        ("14", "14:00"),
        ("в 9 вечера", "21:00"),
    ],
)
def test_parse_time(raw: str, expected: str) -> None:
    assert parse_time(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 час 30 минут", 90),
        ("2 дня", 2 * 24 * 60),
        ("за неделю", 7 * 24 * 60),
        ("полтора часа", 90),
        ("1,5 часа", 90),
        ("за 45 минут", 45),
        ("за 2 дня 3 часа", 2 * 24 * 60 + 180),
    ],
)
def test_parse_reminder_offset(raw: str, expected: int) -> None:
    assert parse_reminder_offset(raw) == expected


def test_parse_day_month() -> None:
    assert parse_day_month("29 февраля") == (29, 2)
    assert parse_day_month("29.02") == (29, 2)
    assert parse_day_month("31.04") is None
    assert parse_day_month("1 января") == (1, 1)


def test_parse_natural_date_months() -> None:
    assert parse_natural_date("через месяц", today=date(2026, 1, 15)) == date(
        2026, 2, 15
    )
    assert parse_natural_date("через 2 месяца", today=date(2026, 1, 15)) == date(
        2026, 3, 15
    )


def test_repeat_parser() -> None:
    result = parse_repeat_phrase("каждый год 29 февраля")
    assert result is not None
    assert result.rule_type == "yearly"
    assert result.rule_value == "29-2"

    result = parse_repeat_phrase("каждые 3 дня")
    assert result is not None
    assert result.rule_value == "3"

    result = parse_repeat_phrase("по понедельникам и средам")
    assert result is not None
    assert result.rule_type == "weekday"
    assert result.rule_value == "0,2"
