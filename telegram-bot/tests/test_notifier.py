from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

import database.db_manager as dm
from database.plans_repo import add_plan, add_recurring_rule
from database.settings_repo import (
    get_settings,
    set_morning_time,
    set_quiet_hours,
    set_skip_empty_digest,
    set_user_timezone_offset,
    toggle_evening,
    toggle_morning,
)
import services.notifier as notifier


class FakeForbidden(Exception):
    pass


class FakeNotFound(Exception):
    pass


class FakeRetryAfter(Exception):
    def __init__(self, retry_after: int = 0) -> None:
        self.retry_after = retry_after


class FakeBot:
    def __init__(self, error: Exception | None = None, retry_once: bool = False) -> None:
        self.messages: list[tuple[int, str]] = []
        self.error = error
        self.retry_once = retry_once
        self.retried = False

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        if self.retry_once and not self.retried:
            self.retried = True
            raise FakeRetryAfter(retry_after=-1)
        if self.error:
            raise self.error
        self.messages.append((chat_id, text))


@pytest.fixture(autouse=True)
def patch_notifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notifier, "TelegramForbiddenError", FakeForbidden)
    monkeypatch.setattr(notifier, "TelegramNotFound", FakeNotFound)
    monkeypatch.setattr(notifier, "TelegramRetryAfter", FakeRetryAfter)


def _user(
    temp_env: Path,
    telegram_id: int,
    *,
    morning: str = "08:00",
    digests: bool = True,
) -> None:
    db = dm.ensure_user_db(telegram_id, f"user{telegram_id}", "User")
    set_user_timezone_offset(db, 0)
    set_morning_time(db, morning)
    if not digests:
        toggle_morning(db, False)
        toggle_evening(db, False)
    db.close()


def _set_now(monkeypatch: pytest.MonkeyPatch, value: datetime) -> None:
    monkeypatch.setattr(notifier, "now_for_offset", lambda offset: value)


@pytest.mark.asyncio
async def test_digest_and_reminders(temp_env: Path, monkeypatch) -> None:
    _user(temp_env, 333)
    today = date(2026, 1, 5)
    db = dm.open_user_db_by_id(333)
    assert db is not None
    add_plan(db, today, "Созвон", "09:00", "09:30", None, 30)
    add_recurring_rule(db, "Зарядка", None, "10:00", None, today, "interval", "1", 30)
    db.close()

    bot = FakeBot()
    _set_now(monkeypatch, datetime(2026, 1, 5, 8, 0))
    await notifier._process_user(bot, 333)
    assert len(bot.messages) == 1
    assert "Доброе утро" in bot.messages[0][1]

    db = dm.open_user_db_by_id(333)
    assert db is not None
    add_plan(db, today, "Старт", "08:10", None, None, 10)
    db.close()

    _set_now(monkeypatch, datetime(2026, 1, 5, 8, 11))
    await notifier._process_user(bot, 333)
    assert "начинается сейчас" in "\n".join(t for _, t in bot.messages)

    _set_now(monkeypatch, datetime(2026, 1, 5, 8, 30))
    await notifier._process_user(bot, 333)
    assert any("Созвон" in t for _, t in bot.messages)

    _set_now(monkeypatch, datetime(2026, 1, 5, 9, 30))
    await notifier._process_user(bot, 333)
    assert any("Зарядка" in t for _, t in bot.messages)


@pytest.mark.asyncio
async def test_recurring_reminder_two_days(temp_env: Path, monkeypatch) -> None:
    _user(temp_env, 444, digests=False)
    db = dm.open_user_db_by_id(444)
    assert db is not None
    today = date(2026, 1, 5)
    add_recurring_rule(db, "Через два дня", None, "08:00", None, today, "interval", "1", 2880)
    db.close()

    bot = FakeBot()
    _set_now(monkeypatch, datetime(2026, 1, 5, 8, 0))
    await notifier._process_user(bot, 444)
    assert any("Через два дня" in t for _, t in bot.messages)


@pytest.mark.asyncio
async def test_quiet_hours_postpone(temp_env: Path, monkeypatch) -> None:
    _user(temp_env, 555, digests=False)
    db = dm.open_user_db_by_id(555)
    assert db is not None
    add_plan(db, date(2026, 1, 7), "Ночная", "02:00", None, None, 30)
    set_quiet_hours(db, enabled=True, start="23:00", end="08:00")
    db.close()

    bot = FakeBot()
    _set_now(monkeypatch, datetime(2026, 1, 7, 8, 0))
    await notifier._process_user(bot, 555)
    assert any("Ночная" in t for _, t in bot.messages)


@pytest.mark.asyncio
async def test_skip_empty_digest(temp_env: Path, monkeypatch) -> None:
    _user(temp_env, 666)
    db = dm.open_user_db_by_id(666)
    assert db is not None
    set_skip_empty_digest(db, True)
    db.close()

    bot = FakeBot()
    _set_now(monkeypatch, datetime(2026, 1, 5, 8, 0))
    await notifier._process_user(bot, 666)
    assert not bot.messages

    db = dm.open_user_db_by_id(666)
    assert db is not None
    assert get_settings(db).last_morning_sent == "2026-01-05"
    db.close()


@pytest.mark.asyncio
async def test_blocked_user_is_skipped(temp_env: Path, monkeypatch) -> None:
    _user(temp_env, 777, digests=False)
    db = dm.open_user_db_by_id(777)
    assert db is not None
    add_plan(db, date(2026, 1, 5), "Задача", "09:00", None, None, 30)
    db.close()

    _set_now(monkeypatch, datetime(2026, 1, 5, 8, 30))
    await notifier._process_user(FakeBot(error=FakeForbidden()), 777)

    db = dm.open_user_db_by_id(777)
    assert db is not None
    assert get_settings(db).blocked is True
    db.close()

    bot = FakeBot()
    await notifier._process_user(bot, 777)
    assert not bot.messages


@pytest.mark.asyncio
async def test_retry_after(temp_env: Path, monkeypatch) -> None:
    _user(temp_env, 888, digests=False)
    db = dm.open_user_db_by_id(888)
    assert db is not None
    add_plan(db, date(2026, 1, 5), "Retry", "09:00", None, None, 30)
    db.close()

    bot = FakeBot(retry_once=True)
    _set_now(monkeypatch, datetime(2026, 1, 5, 8, 30))
    await notifier._process_user(bot, 888)
    assert any("Retry" in t for _, t in bot.messages)


@pytest.mark.asyncio
async def test_long_digest_is_split(temp_env: Path, monkeypatch) -> None:
    _user(temp_env, 999)
    today = date(2026, 1, 5)
    db = dm.open_user_db_by_id(999)
    assert db is not None
    for i in range(60):
        add_plan(db, today, f"Очень длинная задача номер {i} " + "X" * 80, "09:00", None, None)
    db.close()

    bot = FakeBot()
    _set_now(monkeypatch, datetime(2026, 1, 5, 8, 0))
    await notifier._process_user(bot, 999)
    assert len(bot.messages) > 1
    assert all(len(text) <= 4096 for _, text in bot.messages)
