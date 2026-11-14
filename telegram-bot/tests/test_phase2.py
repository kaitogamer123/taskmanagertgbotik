from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import database.db_manager as dm
import services.notifier as notifier
from database.notes_repo import (
    add_file,
    add_item,
    create_folder,
    create_note,
    get_note,
    list_notes,
    search_notes,
    toggle_item,
)
from database.plans_repo import (
    add_plan,
    add_recurring_rule,
    add_snooze,
    count_active_rules,
    count_done_plans,
    count_done_rules,
    due_snoozes,
    get_plan_row,
    get_plans_for_date,
    get_rule_row,
    toggle_plan_done,
    toggle_rule_active,
    toggle_rule_done,
    update_plan,
    update_rule,
)
from database.settings_repo import (
    set_user_timezone_offset,
    toggle_evening,
    toggle_morning,
)
from keyboards.inline import edit_item_keyboard, snooze_keyboard


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text, kwargs))


def _user(temp_env: Path, telegram_id: int) -> None:
    db = dm.ensure_user_db(telegram_id, f"u{telegram_id}", "U")
    set_user_timezone_offset(db, 0)
    toggle_morning(db, False)
    toggle_evening(db, False)
    db.close()


def test_notes_crud(temp_env: Path) -> None:
    db = dm.ensure_user_db(1, "notes", "N")
    folder = create_folder(db, "Идеи")
    note_id = create_note(db, folder, None, "Первая мысль\nвторая строка")
    add_item(db, note_id, "Купить молоко")
    add_file(db, note_id, "F", "U", "photo", None, "caption", 1, 2)

    note = get_note(db, note_id)
    assert note is not None
    assert note.display_title == "Первая мысль"
    assert len(note.items) == 1 and len(note.files) == 1

    assert list_notes(db, folder)
    assert search_notes(db, "молоко")
    item_id = note.items[0]["id"]
    assert toggle_item(db, item_id, note_id) is True
    assert toggle_item(db, item_id, note_id) is False
    db.close()


def test_edit_done_pause_stats(temp_env: Path) -> None:
    db = dm.ensure_user_db(2, "plans", "P")
    today = date(2026, 2, 10)

    plan_id = add_plan(db, today, "Старое", "09:00", None, None, 30)
    update_plan(db, plan_id, title="Новое", time_start="11:00")
    row = get_plan_row(db, plan_id)
    assert row["title"] == "Новое" and row["time_start"] == "11:00"

    rule_id = add_recurring_rule(
        db, "Повтор", None, "10:00", None, today, "interval", "1"
    )
    update_rule(db, rule_id, title="Повтор 2", time_start="12:00")
    assert get_rule_row(db, rule_id)["title"] == "Повтор 2"

    assert toggle_rule_active(db, rule_id) is False
    assert toggle_rule_active(db, rule_id) is True

    toggle_plan_done(db, plan_id, True)
    toggle_rule_done(db, rule_id, today, True)
    since = today - timedelta(days=6)
    assert count_done_plans(db, since) == 1
    assert count_done_rules(db, since) == 1
    assert count_active_rules(db) >= 1

    items = get_plans_for_date(db, today)
    assert any(item.done_at for item in items if item.kind == "plan")
    kb = edit_item_keyboard(today, items[0])
    for row_buttons in kb.inline_keyboard:
        for button in row_buttons:
            assert len(button.callback_data or "") <= 64
    db.close()


@pytest.mark.asyncio
async def test_snooze(temp_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _user(temp_env, 3)
    db = dm.open_user_db_by_id(3)
    assert db is not None
    plan_id = add_plan(db, date(2026, 2, 10), "Snooze", "09:00", None, None, 30)
    add_snooze(db, "plan", plan_id, None, "Snooze", "09:00", "2026-02-10 14:59")
    db.close()

    now = datetime(2026, 2, 10, 15, 0)
    monkeypatch.setattr(notifier, "now_in_zone", lambda name, offset: now)
    bot = FakeBot()
    await notifier._process_user(bot, 3)
    assert any("Snooze" in text for _, text, _ in bot.messages)
    check_db = dm.open_user_db_by_id(3)
    assert check_db is not None
    assert due_snoozes(check_db, "2026-02-10 15:00") == []
    check_db.close()

    kb = snooze_keyboard("plan", plan_id)
    for row_buttons in kb.inline_keyboard:
        for button in row_buttons:
            assert len(button.callback_data or "") <= 64
