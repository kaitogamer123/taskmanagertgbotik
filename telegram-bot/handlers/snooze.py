"""Кнопки «напомнить позже» под напоминаниями."""
from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery

from database.db_manager import UserDB
from database.plans_repo import add_snooze, get_plan_row, get_rule_row
from utils.clock import now_for_user

router = Router(name="snooze")

ALLOWED_MINUTES = {10, 30, 60}


@router.callback_query(F.data.startswith("snz:"))
async def cb_snooze(callback: CallbackQuery, db: UserDB) -> None:
    parts = (callback.data or "").split(":", 4)
    if len(parts) != 5:
        await callback.answer("Кнопка устарела", show_alert=True)
        return
    _, kind, source_id_str, date_part, minutes_str = parts
    try:
        source_id = int(source_id_str)
        minutes = int(minutes_str)
    except ValueError:
        await callback.answer("Кнопка устарела", show_alert=True)
        return

    if kind not in {"plan", "recur"} or minutes not in ALLOWED_MINUTES:
        await callback.answer("Кнопка устарела", show_alert=True)
        return

    if kind == "plan":
        row = get_plan_row(db, source_id)
    else:
        row = get_rule_row(db, source_id)
    if row is None:
        await callback.answer("Задача уже удалена", show_alert=True)
        return

    occurrence = None if date_part == "-" else date_part
    remind_at = now_for_user(db) + timedelta(minutes=minutes)
    add_snooze(
        db,
        kind,
        source_id,
        occurrence,
        row["title"],
        row["time_start"],
        remind_at.strftime("%Y-%m-%d %H:%M"),
    )
    await callback.answer(f"⏰ Ок, напомню в {remind_at:%H:%M}")
