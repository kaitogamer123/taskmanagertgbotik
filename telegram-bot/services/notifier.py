"""
Фоновый планировщик уведомлений.

Каждые config.NOTIFIER_POLL_INTERVAL секунд проверяет базы данных всех
пользователей с учётом ИНДИВИДУАЛЬНОГО часового пояса каждого пользователя и:
  1) отправляет утреннюю сводку (планы на сегодня) в настроенное время;
  2) отправляет вечернюю сводку (планы на завтра) в настроенное время;
  3) отправляет напоминания "через N у тебя задача ..." для разовых и
     повторяющихся задач, у которых настроено напоминание.

Учитывает:
  * тихие часы (напоминания переносятся на утро);
  * пустые сводки (можно отключить);
  * заблокировавших бота пользователей;
  * TelegramRetryAfter (flood control);
  * напоминания повторяющихся задач за любое число дней (не только 0/1).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)

from config import NOTIFIER_POLL_INTERVAL
from database.db_manager import UserDB, iter_all_user_ids, open_user_db_by_id
from database.plans_repo import (
    PlanItem,
    _rule_occurs_on,
    delete_snooze,
    due_snoozes,
    get_plans_for_date,
    is_rule_done,
)
from database.settings_repo import (
    NotifySettings,
    get_settings,
    mark_evening_sent,
    mark_morning_sent,
    mark_user_blocked,
)
from utils.clock import now_for_offset
from utils.date_utils import format_date_full_ru, weekday_name
from utils.reminder_utils import format_minutes_label
from utils.text import MAX_TITLE, esc, paginate_lines
from keyboards.inline import snooze_keyboard

logger = logging.getLogger(__name__)

# Если бот был недоступен дольше этого времени, старые просроченные
# напоминания/сводки уже не досылаем.
GRACE_WINDOW = timedelta(minutes=15)


class UserBlocked(Exception):
    """Пользователь заблокировал бота — прекращаем обработку до следующего тика."""


def _digest_lines(items: list[PlanItem]) -> list[str]:
    if not items:
        return ["На этот день пока ничего не запланировано 🙂"]
    undone = [item for item in items if not item.done_at]
    if not undone:
        return ["На этот день всё выполнено ✅"]
    return [
        f"🕐 {esc(item.time_label())} — {esc(item.title, MAX_TITLE)}"
        for item in undone
    ]


async def _send_with_retry(
    bot: Bot, chat_id: int, text: str, reply_markup=None
) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except TelegramRetryAfter as exc:
        # Flood control: ждём столько, сколько просит Telegram (но не бесконечно)
        await asyncio.sleep(min(exc.retry_after, 30) + 1)
        await bot.send_message(chat_id, text, reply_markup=reply_markup)


async def _send_chunks(
    bot: Bot, chat_id: int, header: str, lines: list[str]
) -> None:
    for chunk in paginate_lines([header] + lines):
        if chunk.strip():
            await _send_with_retry(bot, chat_id, chunk)


async def _send_morning_digest(
    bot: Bot, telegram_id: int, items: list[PlanItem], today: date
) -> None:
    header = (
        f"🌅 Доброе утро! Вот что запланировано на сегодня, "
        f"<b>{format_date_full_ru(today)} ({weekday_name(today)})</b>:\n"
    )
    await _send_chunks(bot, telegram_id, header, _digest_lines(items))


async def _send_evening_digest(
    bot: Bot, telegram_id: int, items: list[PlanItem], tomorrow: date
) -> None:
    header = (
        f"🌙 Добрый вечер! Вот что запланировано на завтра, "
        f"<b>{format_date_full_ru(tomorrow)} ({weekday_name(tomorrow)})</b>:\n"
    )
    await _send_chunks(bot, telegram_id, header, _digest_lines(items))


def _parse_hhmm(value: str) -> Optional[tuple[int, int]]:
    try:
        hh, mm = value.split(":")
        return int(hh), int(mm)
    except (ValueError, AttributeError):
        return None


def _quiet_bounds(settings: NotifySettings) -> Optional[tuple[dtime, dtime]]:
    if not settings.quiet_enabled:
        return None
    start = _parse_hhmm(settings.quiet_start)
    end = _parse_hhmm(settings.quiet_end)
    if not start or not end:
        return None
    return dtime(start[0], start[1]), dtime(end[0], end[1])


def _time_in_quiet(t: dtime, start: dtime, end: dtime) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= t < end
    return t >= start or t < end


def _adjust_for_quiet(target: datetime, settings: NotifySettings) -> datetime:
    """Если время попадает в тихие часы — переносим на их окончание."""
    bounds = _quiet_bounds(settings)
    if bounds is None:
        return target
    start, end = bounds
    if not _time_in_quiet(target.time(), start, end):
        return target
    adjusted = target.replace(
        hour=end.hour, minute=end.minute, second=0, microsecond=0
    )
    if adjusted <= target:
        adjusted += timedelta(days=1)
    return adjusted


def _reminder_text(title: str, now: datetime, start_dt: datetime) -> str:
    delta_minutes = int((start_dt - now).total_seconds() // 60)
    safe_title = esc(title, MAX_TITLE)
    if delta_minutes > 0:
        return (
            f"⏰ Через {format_minutes_label(delta_minutes)} у тебя задача "
            f"«<b>{safe_title}</b>»!"
        )
    if now - start_dt <= GRACE_WINDOW:
        return f"⏰ Задача «<b>{safe_title}</b>» начинается сейчас!"
    return f"⏰ Задача «<b>{safe_title}</b>» уже началась."


def _reminder_horizon_days(minutes: int) -> int:
    """Сколько дней вперёд проверять повторяющиеся задачи для напоминания."""
    if minutes <= 0:
        return 1
    days = (minutes + 1439) // 1440 + 1
    return max(1, min(days, 14))


async def _check_daily_digests(
    bot: Bot,
    telegram_id: int,
    db: UserDB,
    now: datetime,
    settings: NotifySettings,
) -> None:
    today_iso = now.date().isoformat()
    today = now.date()

    if settings.morning_enabled and settings.last_morning_sent != today_iso:
        parsed = _parse_hhmm(settings.morning_time)
        if parsed:
            hh, mm = parsed
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now <= target + GRACE_WINDOW:
                items = get_plans_for_date(db, today)
                if not (settings.skip_empty_digest and not items):
                    try:
                        await _send_morning_digest(bot, telegram_id, items, today)
                    except (TelegramForbiddenError, TelegramNotFound):
                        mark_user_blocked(db.conn)
                        raise UserBlocked
                mark_morning_sent(db.conn, today_iso)

    if settings.evening_enabled and settings.last_evening_sent != today_iso:
        parsed = _parse_hhmm(settings.evening_time)
        if parsed:
            hh, mm = parsed
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now <= target + GRACE_WINDOW:
                tomorrow = today + timedelta(days=1)
                items = get_plans_for_date(db, tomorrow)
                if not (settings.skip_empty_digest and not items):
                    try:
                        await _send_evening_digest(bot, telegram_id, items, tomorrow)
                    except (TelegramForbiddenError, TelegramNotFound):
                        mark_user_blocked(db.conn)
                        raise UserBlocked
                mark_evening_sent(db.conn, today_iso)


async def _check_plan_reminders(
    bot: Bot,
    telegram_id: int,
    db: UserDB,
    now: datetime,
    settings: NotifySettings,
) -> None:
    rows = db.conn.execute(
        """
        SELECT id, plan_date, time_start, title, reminder_minutes FROM plans
        WHERE reminder_sent = 0
          AND reminder_minutes IS NOT NULL
          AND reminder_minutes > 0
          AND time_start IS NOT NULL
          AND done_at IS NULL
        """
    ).fetchall()

    changed = False
    for row in rows:
        try:
            plan_date = date.fromisoformat(row["plan_date"])
            hh, mm = (int(x) for x in row["time_start"].split(":"))
        except (ValueError, AttributeError):
            continue

        start_dt = datetime.combine(plan_date, datetime.min.time()).replace(
            hour=hh, minute=mm
        )
        target_dt = start_dt - timedelta(minutes=row["reminder_minutes"] or 0)
        target_dt = _adjust_for_quiet(target_dt, settings)

        # Просроченное напоминание больше не сканируем каждый тик
        if now > target_dt + GRACE_WINDOW:
            db.conn.execute(
                "UPDATE plans SET reminder_sent = 1 WHERE id = ?", (row["id"],)
            )
            changed = True
            continue

        if target_dt <= now <= target_dt + GRACE_WINDOW:
            text = _reminder_text(row["title"], now, start_dt)
            try:
                await _send_with_retry(
                    bot,
                    telegram_id,
                    text,
                    reply_markup=snooze_keyboard("plan", int(row["id"])),
                )
            except (TelegramForbiddenError, TelegramNotFound):
                mark_user_blocked(db.conn)
                raise UserBlocked
            db.conn.execute(
                "UPDATE plans SET reminder_sent = 1 WHERE id = ?", (row["id"],)
            )
            changed = True

    if changed:
        db.conn.commit()


async def _check_rule_reminders(
    bot: Bot,
    telegram_id: int,
    db: UserDB,
    now: datetime,
    settings: NotifySettings,
) -> None:
    rows = db.conn.execute(
        """
        SELECT * FROM recurring_rules
        WHERE reminder_minutes IS NOT NULL
          AND reminder_minutes > 0
          AND time_start IS NOT NULL
        """
    ).fetchall()

    changed = False
    for row in rows:
        try:
            hh, mm = (int(x) for x in row["time_start"].split(":"))
        except (ValueError, AttributeError):
            continue

        horizon = _reminder_horizon_days(int(row["reminder_minutes"] or 0))
        for offset_days in range(horizon):
            candidate_date = now.date() + timedelta(days=offset_days)
            if row["last_reminder_date"] == candidate_date.isoformat():
                continue
            if not _rule_occurs_on(row, candidate_date):
                continue
            if is_rule_done(db, int(row["id"]), candidate_date):
                continue

            start_dt = datetime.combine(
                candidate_date, datetime.min.time()
            ).replace(hour=hh, minute=mm)
            target_dt = start_dt - timedelta(minutes=row["reminder_minutes"] or 0)
            target_dt = _adjust_for_quiet(target_dt, settings)

            if target_dt <= now <= target_dt + GRACE_WINDOW:
                text = _reminder_text(row["title"], now, start_dt)
                try:
                    await _send_with_retry(
                        bot,
                        telegram_id,
                        text,
                        reply_markup=snooze_keyboard(
                            "recur", int(row["id"]), candidate_date.isoformat()
                        ),
                    )
                except (TelegramForbiddenError, TelegramNotFound):
                    mark_user_blocked(db.conn)
                    raise UserBlocked
                db.conn.execute(
                    "UPDATE recurring_rules SET last_reminder_date = ? WHERE id = ?",
                    (candidate_date.isoformat(), row["id"]),
                )
                changed = True
                break

    if changed:
        db.conn.commit()


async def _check_snoozes(
    bot: Bot,
    telegram_id: int,
    db: UserDB,
    now: datetime,
    settings: NotifySettings,
) -> None:
    rows = due_snoozes(db, now.strftime("%Y-%m-%d %H:%M"))
    for row in rows:
        try:
            target = datetime.strptime(row["remind_at"], "%Y-%m-%d %H:%M")
        except ValueError:
            delete_snooze(db, int(row["id"]))
            continue

        target = _adjust_for_quiet(target, settings)
        if now > target + GRACE_WINDOW:
            delete_snooze(db, int(row["id"]))
            continue
        if target <= now <= target + GRACE_WINDOW:
            text = f'⏰ Напоминание: «<b>{esc(row["title"], MAX_TITLE)}</b>»'
            try:
                await _send_with_retry(
                    bot,
                    telegram_id,
                    text,
                    reply_markup=snooze_keyboard(
                        row["kind"],
                        int(row["source_id"]),
                        row["occurrence_date"],
                    ),
                )
            except (TelegramForbiddenError, TelegramNotFound):
                mark_user_blocked(db.conn)
                raise UserBlocked
            delete_snooze(db, int(row["id"]))


async def _process_user(bot: Bot, telegram_id: int) -> None:
    db = open_user_db_by_id(telegram_id)
    if db is None:
        return
    try:
        settings = get_settings(db)
        if settings.blocked:
            return
        if settings.timezone_configured and settings.utc_offset is not None:
            user_now = now_for_offset(int(settings.utc_offset))
        else:
            user_now = now_for_offset(None)

        await _check_daily_digests(bot, telegram_id, db, user_now, settings)
        await _check_plan_reminders(bot, telegram_id, db, user_now, settings)
        await _check_rule_reminders(bot, telegram_id, db, user_now, settings)
        await _check_snoozes(bot, telegram_id, db, user_now, settings)
    except UserBlocked:
        logger.info("Пользователь %s заблокировал бота — пропускаем", telegram_id)
    except Exception:  # noqa: BLE001 - один сбой не должен останавливать весь цикл
        logger.exception(
            "Ошибка при обработке уведомлений для пользователя %s", telegram_id
        )
    finally:
        db.close()


async def run_notifier(bot: Bot) -> None:
    logger.info(
        "Планировщик уведомлений запущен (интервал %s сек.)", NOTIFIER_POLL_INTERVAL
    )
    while True:
        started = time.monotonic()
        try:
            for telegram_id in list(iter_all_user_ids()):
                await _process_user(bot, telegram_id)
                # Даём event loop обработать входящие сообщения, чтобы при
                # большом числе пользователей бот не «замирал» на этом цикле.
                await asyncio.sleep(0)
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка в цикле планировщика уведомлений")

        elapsed = time.monotonic() - started
        await asyncio.sleep(max(1.0, NOTIFIER_POLL_INTERVAL - elapsed))
