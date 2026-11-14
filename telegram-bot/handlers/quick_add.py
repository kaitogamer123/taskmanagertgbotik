"""Быстрое добавление задачи одной строкой: /add завтра 10:00-11:00 Созвон."""
from __future__ import annotations

import re
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db_manager import UserDB
from database.plans_repo import add_plan
from utils.clock import today_for_user
from utils.date_utils import (
    format_date_full_ru,
    parse_natural_date,
    parse_time,
    weekday_name,
)
from utils.text import MAX_TITLE, esc

router = Router(name="quick_add")

_TIME_RANGE_RE = re.compile(
    r"(?<!\d)(\d{1,2}(?::\d{2})?)\s*[-–—]\s*(\d{1,2}(?::\d{2})?)(?!\d)"
)
_SINGLE_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}[:.]\d{2})(?!\d)")


def _split_date_title(raw: str, today: date) -> tuple[date, str]:
    """Ищет самый короткий префикс, который парсится как дата."""
    words = raw.split()
    for i in range(1, len(words) + 1):
        prefix = " ".join(words[:i])
        parsed = parse_natural_date(prefix, today=today)
        if parsed is not None:
            title = " ".join(words[i:]).strip()
            return parsed, title
    return today, raw.strip()


@router.message(Command("add", ignore_case=True))
async def cmd_add(message: Message, db: UserDB) -> None:
    parts = (message.text or "").split(maxsplit=1)
    raw = parts[1].strip() if len(parts) > 1 else ""
    if not raw:
        await message.answer(
            "Напиши одной строкой, например:\n"
            "<code>/add завтра 10:00-11:00 Созвон</code>\n"
            "<code>/add 19.10 14:30 Позвонить</code>"
        )
        return

    today = today_for_user(db)
    time_start = None
    time_end = None

    match = _TIME_RANGE_RE.search(raw)
    if match:
        time_start = parse_time(match.group(1))
        time_end = parse_time(match.group(2))
        raw = (raw[: match.start()] + " " + raw[match.end() :]).strip()
    else:
        match = _SINGLE_TIME_RE.search(raw)
        if match:
            time_start = parse_time(match.group(1))
            raw = (raw[: match.start()] + " " + raw[match.end() :]).strip()

    plan_date, title = _split_date_title(raw, today)
    title = re.sub(r"^в\s+", "", title, flags=re.IGNORECASE).strip()
    title = title or "Без названия"
    if len(title) > MAX_TITLE:
        await message.answer(f"Слишком длинное название, максимум {MAX_TITLE} символов.")
        return

    add_plan(db, plan_date, title, time_start, time_end, None, None)

    time_label = time_start or "без времени"
    if time_start and time_end:
        time_label = f"{time_start}-{time_end}"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📅 Открыть день",
            callback_data=f"day:{plan_date.isoformat()}",
        )
    )
    await message.answer(
        "✅ Задача добавлена:\n\n"
        f"📅 {format_date_full_ru(plan_date)} ({weekday_name(plan_date)})\n"
        f"🕐 {esc(time_label)}\n"
        f"📝 <b>{esc(title, MAX_TITLE)}</b>",
        reply_markup=builder.as_markup(),
    )
