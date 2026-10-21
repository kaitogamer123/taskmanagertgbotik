"""Текущее время с учётом часового пояса, заданного в config.TIMEZONE."""
from __future__ import annotations

from datetime import datetime

from config import TIMEZONE


def now_local() -> datetime:
    """Текущие дата и время в часовом поясе бота (naive datetime, без tzinfo)."""
    return datetime.now(TIMEZONE).replace(tzinfo=None)
