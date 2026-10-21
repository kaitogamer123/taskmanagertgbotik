"""
Фоновый планировщик уведомлений.

Каждые config.NOTIFIER_POLL_INTERVAL секунд проверяет базы данных всех
пользователей и:
  1) отправляет утреннюю сводку (планы на сегодня) в настроенное время;
  2) отправляет вечернюю сводку (планы на завтра) в настроенное время;
  3) отправляет напоминания "через N у тебя задача ..." для разовых и
     повторяющихся задач, у которых настроено напоминание.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound

from config import NOTIFIER_POLL_INTERVAL
from database.db_manager import UserDB, iter_all_user_ids, open_user_db_by_id
from database.plans_repo import PlanItem, _rule_occurs_on, get_plans_for_date
from database.settings_repo import get_settings, mark_evening_sent, mark_morning_sent
from utils.clock import now_local
from utils.date_utils import format_date_full_ru, weekday_name
from utils.reminder_utils import format_minutes_label

logger = logging.getLogger(__name__)

# Если бот был недоступен дольше этого времени, старые просроченные
# напоминания/сводки уже не досылаем, чтобы не "накрыть" пользователя
# устаревшими сообщениями после долгого простоя.
GRACE_WINDOW = timedelta(minutes=15)


def _digest_body(items: list[PlanItem]) -> str:
    if not items:
        return "На этот день пока ничего не запланировано 🙂"
    lines = []
    for item in items:
        lines.append(f"🕐 {item.time_label()} — {item.title}")
    return "\n".join(lines)


async def _send_morning_digest(bot: Bot, telegram_id: int, db: UserDB, today: date) -> None:
    items = get_plans_for_date(db, today)
    text = (
        f"🌅 Доброе утро! Вот что запланировано на сегодня, "
        f"{format_date_full_ru(today)} ({weekday_name(today)}):\n\n"
        f"{_digest_body(items)}"
    )
    await bot.send_message(telegram_id, text)


async def _send_evening_digest(bot: Bot, telegram_id: int, db: UserDB, tomorrow: date) -> None:
    items = get_plans_for_date(db, tomorrow)
    text = (
        f"🌙 Добрый вечер! Вот что запланировано на завтра, "
        f"{format_date_full_ru(tomorrow)} ({weekday_name(tomorrow)}):\n\n"
        f"{_digest_body(items)}"
    )
    await bot.send_message(telegram_id, text)


def _parse_hhmm(value: str) -> Optional[tuple[int, int]]:
    try:
        hh, mm = value.split(":")
        return int(hh), int(mm)
    except (ValueError, AttributeError):
        return None


async def _check_daily_digests(bot: Bot, telegram_id: int, db: UserDB, now: datetime) -> None:
    settings = get_settings(db)
    today_iso = now.date().isoformat()

    if settings.morning_enabled and settings.last_morning_sent != today_iso:
        parsed = _parse_hhmm(settings.morning_time)
        if parsed:
            hh, mm = parsed
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now <= target + GRACE_WINDOW:
                try:
                    await _send_morning_digest(bot, telegram_id, db, now.date())
                except (TelegramForbiddenError, TelegramNotFound):
                    pass
                mark_morning_sent(db.conn, today_iso)

    if settings.evening_enabled and settings.last_evening_sent != today_iso:
        parsed = _parse_hhmm(settings.evening_time)
        if parsed:
            hh, mm = parsed
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now <= target + GRACE_WINDOW:
                try:
                    await _send_evening_digest(bot, telegram_id, db, now.date() + timedelta(days=1))
                except (TelegramForbiddenError, TelegramNotFound):
                    pass
                mark_evening_sent(db.conn, today_iso)


async def _check_plan_reminders(bot: Bot, telegram_id: int, db: UserDB, now: datetime) -> None:
    rows = db.conn.execute(
        """
        SELECT id, plan_date, time_start, title, reminder_minutes FROM plans
        WHERE reminder_sent = 0
          AND reminder_minutes IS NOT NULL
          AND reminder_minutes > 0
          AND time_start IS NOT NULL
        """
    ).fetchall()

    for row in rows:
        try:
            plan_date = date.fromisoformat(row["plan_date"])
            hh, mm = (int(x) for x in row["time_start"].split(":"))
        except (ValueError, AttributeError):
            continue

        start_dt = datetime.combine(plan_date, datetime.min.time()).replace(hour=hh, minute=mm)
        target_dt = start_dt - timedelta(minutes=row["reminder_minutes"] or 0)

        if target_dt <= now <= target_dt + GRACE_WINDOW:
            label = format_minutes_label(_remaining_minutes(now, start_dt))
            text = f'⏰ Через {label} у тебя задача "{row["title"]}"!'
            try:
                await bot.send_message(telegram_id, text)
            except (TelegramForbiddenError, TelegramNotFound):
                pass
            db.conn.execute("UPDATE plans SET reminder_sent = 1 WHERE id = ?", (row["id"],))
            db.conn.commit()


async def _check_rule_reminders(bot: Bot, telegram_id: int, db: UserDB, now: datetime) -> None:
    rows = db.conn.execute(
        """
        SELECT * FROM recurring_rules
        WHERE reminder_minutes IS NOT NULL
          AND reminder_minutes > 0
          AND time_start IS NOT NULL
        """
    ).fetchall()

    for row in rows:
        for offset_days in (0, 1):
            candidate_date = now.date() + timedelta(days=offset_days)
            if row["last_reminder_date"] == candidate_date.isoformat():
                continue
            if not _rule_occurs_on(row, candidate_date):
                continue
            try:
                hh, mm = (int(x) for x in row["time_start"].split(":"))
            except (ValueError, AttributeError):
                continue

            start_dt = datetime.combine(candidate_date, datetime.min.time()).replace(hour=hh, minute=mm)
            target_dt = start_dt - timedelta(minutes=row["reminder_minutes"] or 0)

            if target_dt <= now <= target_dt + GRACE_WINDOW:
                label = format_minutes_label(_remaining_minutes(now, start_dt))
                text = f'⏰ Через {label} у тебя задача "{row["title"]}"!'
                try:
                    await bot.send_message(telegram_id, text)
                except (TelegramForbiddenError, TelegramNotFound):
                    pass
                db.conn.execute(
                    "UPDATE recurring_rules SET last_reminder_date = ? WHERE id = ?",
                    (candidate_date.isoformat(), row["id"]),
                )
                db.conn.commit()


def _remaining_minutes(now: datetime, start_dt: datetime) -> int:
    delta = start_dt - now
    minutes = int(delta.total_seconds() // 60)
    return max(minutes, 0)


async def _process_user(bot: Bot, telegram_id: int, now: datetime) -> None:
    db = open_user_db_by_id(telegram_id)
    if db is None:
        return
    try:
        await _check_daily_digests(bot, telegram_id, db, now)
        await _check_plan_reminders(bot, telegram_id, db, now)
        await _check_rule_reminders(bot, telegram_id, db, now)
    except Exception:  # noqa: BLE001 - один сбой не должен останавливать весь цикл
        logger.exception("Ошибка при обработке уведомлений для пользователя %s", telegram_id)
    finally:
        db.close()


async def run_notifier(bot: Bot) -> None:
    logger.info("Планировщик уведомлений запущен (интервал %s сек.)", NOTIFIER_POLL_INTERVAL)
    while True:
        try:
            now = now_local()
            for telegram_id in list(iter_all_user_ids()):
                await _process_user(bot, telegram_id, now)
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка в цикле планировщика уведомлений")
        await asyncio.sleep(NOTIFIER_POLL_INTERVAL)
