"""Работа с текущим временем и персональным часовым поясом пользователя."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

from config import TIMEZONE

if TYPE_CHECKING:
    from database.db_manager import UserDB

_ZONE_CACHE: dict[str, Optional[ZoneInfo]] = {}


def get_zone(name: Optional[str]) -> Optional[ZoneInfo]:
    """Возвращает ZoneInfo по имени, либо None, если имя неизвестно."""
    if not name:
        return None
    if name in _ZONE_CACHE:
        return _ZONE_CACHE[name]
    try:
        zone: Optional[ZoneInfo] = ZoneInfo(name)
    except Exception:  # noqa: BLE001 - неизвестная зона
        zone = None
    _ZONE_CACHE[name] = zone
    return zone


def now_in_zone(name: Optional[str] = None, utc_offset: Optional[int] = None) -> datetime:
    """
    Текущее локальное время (naive) по IANA-зоне.
    Если зона не задана — fallback на старое целое смещение UTC.
    """
    zone = get_zone(name)
    if zone is not None:
        return datetime.now(zone).replace(tzinfo=None)
    if utc_offset is not None:
        return (datetime.now(timezone.utc) + timedelta(hours=int(utc_offset))).replace(
            tzinfo=None
        )
    return now_local()


def format_zone_offset(name: Optional[str], utc_offset: Optional[int]) -> str:
    """Смещение для отображения: UTC+3, UTC+5:30 и т.п."""
    zone = get_zone(name)
    if zone is not None:
        offset = datetime.now(zone).utcoffset()
        if offset is not None:
            total_minutes = int(offset.total_seconds() // 60)
            sign = "+" if total_minutes >= 0 else "-"
            total_minutes = abs(total_minutes)
            hours, minutes = divmod(total_minutes, 60)
            if minutes:
                return f"UTC{sign}{hours}:{minutes:02d}"
            return f"UTC{sign}{hours}"
    return format_utc_offset(utc_offset)


def zone_utc_offset_hours(name: Optional[str]) -> Optional[int]:
    """Текущее смещение зоны в целых часах — для старого поля utc_offset."""
    zone = get_zone(name)
    if zone is None:
        return None
    offset = datetime.now(zone).utcoffset()
    if offset is None:
        return None
    return int(offset.total_seconds() // 3600)


def now_local() -> datetime:
    """Резервное серверное время с учётом config.TIMEZONE (naive datetime)."""
    return datetime.now(TIMEZONE).replace(tzinfo=None)


def calc_utc_offset_hours(user_hour: int, utc_now: Optional[datetime] = None) -> int:
    """
    По текущему часу у пользователя (0..23) и текущему времени UTC определяет
    смещение часового пояса в часах (в диапазоне от -11 до +12).
    """
    if utc_now is None:
        utc_now = datetime.now(timezone.utc)
    diff = (user_hour - utc_now.hour) % 24
    if diff > 12:
        diff -= 24
    return diff


def format_utc_offset(offset: Optional[int]) -> str:
    """Форматирует смещение в человекочитаемый вид, например 'UTC+3' или 'UTC-5'."""
    if offset is None:
        return "не настроен"
    if offset >= 0:
        return f"UTC+{offset}"
    return f"UTC{offset}"


def parse_user_hour(text: str) -> Optional[int]:
    """
    Извлекает текущий час пользователя (0..23) из произвольного ответа.
    Поддерживает:
      - '17', '0', '09', '23', '24' (-> 0)
      - '17:30', '17.30', '17 30', '9:05'
      - '5 вечера' / '5 дня' (-> 17), '9 утра' (-> 9), '12 ночи' (-> 0)
      - 'сейчас 14', 'у меня 19 часов', '19ч'
    """
    raw = (text or "").strip().lower().replace("ё", "е")
    if not raw:
        return None

    # Явный формат ЧЧ:ММ / ЧЧ.ММ / ЧЧ-ММ / ЧЧ ММ
    m_time = re.search(r"(?<!\d)(\d{1,2})\s*[:.\-]\s*([0-5]\d)(?!\d)", raw)
    if m_time:
        hour = int(m_time.group(1))
        if hour == 24:
            return 0
        if 0 <= hour <= 23:
            return hour
        return None

    # Два числа через пробел, например "17 30"
    m_space = re.fullmatch(r"(\d{1,2})\s+([0-5]\d)", raw)
    if m_space:
        hour = int(m_space.group(1))
        if hour == 24:
            return 0
        if 0 <= hour <= 23:
            return hour
        return None

    # Одно число в сообщении (возможно со словами "час/утра/вечера/дня/ночи")
    numbers = re.findall(r"-?\d+", raw)
    if len(numbers) != 1:
        return None

    hour = int(numbers[0])
    if hour < 0 or hour > 24:
        return None
    if hour == 24:
        return 0

    if any(w in raw for w in ("вечер", "дня")) and 1 <= hour <= 11:
        hour += 12
    elif "ноч" in raw and hour == 12:
        hour = 0

    return hour if 0 <= hour <= 23 else None


def now_for_offset(utc_offset: Optional[int]) -> datetime:
    """Возвращает текущее локальное время (naive datetime) для заданного смещения UTC."""
    if utc_offset is None:
        return now_local()
    return (datetime.now(timezone.utc) + timedelta(hours=utc_offset)).replace(tzinfo=None)


def now_for_user(db: "UserDB") -> datetime:
    """Текущие дата и время конкретно у данного пользователя."""
    row = db.conn.execute(
        "SELECT utc_offset, timezone_name, timezone_configured "
        "FROM user_settings WHERE id = 1"
    ).fetchone()
    if row is not None and row["timezone_configured"]:
        if row["timezone_name"] or row["utc_offset"] is not None:
            return now_in_zone(row["timezone_name"], row["utc_offset"])
    return now_local()


def today_for_user(db: "UserDB") -> date:
    """Сегодняшняя дата по часовому поясу пользователя."""
    return now_for_user(db).date()
