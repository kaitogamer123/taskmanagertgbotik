"""Список популярных IANA-зон и разбор ввода пользователя."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from zoneinfo import available_timezones

from utils.clock import format_zone_offset


@dataclass(frozen=True)
class ZoneOption:
    name: str
    label: str


COMMON_ZONES: list[ZoneOption] = [
    ZoneOption("Europe/Kaliningrad", "Калининград"),
    ZoneOption("Europe/Moscow", "Москва"),
    ZoneOption("Europe/Kyiv", "Киев"),
    ZoneOption("Europe/Minsk", "Минск"),
    ZoneOption("Europe/Chisinau", "Кишинёв"),
    ZoneOption("Asia/Yerevan", "Ереван"),
    ZoneOption("Asia/Tbilisi", "Тбилиси"),
    ZoneOption("Asia/Baku", "Баку"),
    ZoneOption("Asia/Almaty", "Алматы"),
    ZoneOption("Asia/Tashkent", "Ташкент"),
    ZoneOption("Asia/Yekaterinburg", "Екатеринбург"),
    ZoneOption("Asia/Novosibirsk", "Новосибирск"),
    ZoneOption("Asia/Krasnoyarsk", "Красноярск"),
    ZoneOption("Asia/Irkutsk", "Иркутск"),
    ZoneOption("Asia/Vladivostok", "Владивосток"),
    ZoneOption("Asia/Dubai", "Дубай"),
    ZoneOption("Asia/Bangkok", "Бангкок"),
    ZoneOption("Europe/Berlin", "Берлин"),
    ZoneOption("Europe/London", "Лондон"),
    ZoneOption("America/New_York", "Нью-Йорк"),
    ZoneOption("America/Los_Angeles", "Лос-Анджелес"),
    ZoneOption("UTC", "UTC"),
]

_ALIASES: dict[str, str] = {
    "москва": "Europe/Moscow",
    "мск": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "питер": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "киев": "Europe/Kyiv",
    "kyiv": "Europe/Kyiv",
    "kiev": "Europe/Kyiv",
    "минск": "Europe/Minsk",
    "minsk": "Europe/Minsk",
    "ереван": "Asia/Yerevan",
    "yerevan": "Asia/Yerevan",
    "тбилиси": "Asia/Tbilisi",
    "tbilisi": "Asia/Tbilisi",
    "баку": "Asia/Baku",
    "baku": "Asia/Baku",
    "алматы": "Asia/Almaty",
    "алма-ата": "Asia/Almaty",
    "almaty": "Asia/Almaty",
    "ташкент": "Asia/Tashkent",
    "tashkent": "Asia/Tashkent",
    "екатеринбург": "Asia/Yekaterinburg",
    "новосибирск": "Asia/Novosibirsk",
    "красноярск": "Asia/Krasnoyarsk",
    "иркутск": "Asia/Irkutsk",
    "владивосток": "Asia/Vladivostok",
    "дубай": "Asia/Dubai",
    "dubai": "Asia/Dubai",
    "банкгок": "Asia/Bangkok",
    "berlin": "Europe/Berlin",
    "берлин": "Europe/Berlin",
    "лондон": "Europe/London",
    "london": "Europe/London",
    "нью-йорк": "America/New_York",
    "нью йорк": "America/New_York",
    "new york": "America/New_York",
    "лос-анджелес": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles",
    "utc": "UTC",
    "gmt": "UTC",
}

try:
    _LOWER_TO_CANONICAL: dict[str, str] = {
        name.lower(): name for name in available_timezones()
    }
except Exception:  # noqa: BLE001 - если tzdata нет, останутся только алиасы
    _LOWER_TO_CANONICAL = {}


def zone_label(name: Optional[str]) -> str:
    if not name:
        return "не настроен"
    for option in COMMON_ZONES:
        if option.name == name:
            return option.label
    return name


def normalize_zone_input(text: str) -> Optional[str]:
    """Принимает 'Москва', 'Europe/Moscow', 'new york' и т.п."""
    raw = (text or "").strip().replace("ё", "е")
    if not raw:
        return None
    key = raw.lower()
    if key in _ALIASES:
        return _ALIASES[key]

    candidate = raw.replace(" ", "_")
    canonical = _LOWER_TO_CANONICAL.get(candidate.lower())
    if canonical is not None:
        return canonical

    # На случай "Europe/Moscow (Москва)" — берём первый токен
    first = candidate.split("(", 1)[0].strip()
    return _LOWER_TO_CANONICAL.get(first.lower())


def zone_button_label(name: str) -> str:
    return f"🌍 {zone_label(name)} ({format_zone_offset(name, None)})"
