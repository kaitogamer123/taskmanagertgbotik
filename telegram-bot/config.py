"""
Конфигурация бота.
Токен и дополнительные параметры читаются из файла .env рядом с bot.py.
"""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Версия бота (показывается в /status и в логах при старте)
BOT_VERSION = "2026.11.14-p3"

# Подхватываем .env, лежащий рядом с ботом
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Папка, где лежат персональные базы данных пользователей
PLANES_USER_DIR = BASE_DIR / "PlanesUser"
PLANES_USER_DIR.mkdir(parents=True, exist_ok=True)

# Как часто (в секундах) разрешено перепроверять, не поменялся ли
# username пользователя и не нужно ли переименовать его базу данных
USERNAME_RECHECK_INTERVAL = 5 * 60  # 5 минут

# Название недели для кнопок /MyPlans — сколько дней показывать вперёд
WEEK_WINDOW_DAYS = 7

# Резервный часовой пояс (если пользователь ещё не указал свой час)
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
try:
    TIMEZONE = ZoneInfo(TIMEZONE_NAME)
except Exception:  # noqa: BLE001 - на случай опечатки в .env
    TIMEZONE = ZoneInfo("UTC")

# Настройки уведомлений по умолчанию (используются для новых пользователей)
DEFAULT_MORNING_TIME = "08:00"
DEFAULT_EVENING_TIME = "20:00"

# Как часто (в секундах) фоновый планировщик проверяет, не пора ли
# отправить ежедневную сводку или напоминание о задаче.
# 60 секунд достаточно: все проверки идут с запасом GRACE_WINDOW = 15 минут.
NOTIFIER_POLL_INTERVAL = max(10, int(os.getenv("NOTIFIER_POLL_INTERVAL", "60")))

# Настройки фонового автопулла с GitHub (как в VigarikSQD).
# Проверка раз в 15 минут вместо раз в минуту: git fetch больше не создаёт
# постоянные процессы/сетевые запросы на слабом VPS.
AUTO_PULL_ENABLED = os.getenv("AUTO_PULL_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
AUTO_PULL_INTERVAL = max(300, int(os.getenv("AUTO_PULL_INTERVAL", "900")))

# ID владельцев бота для системной команды /update
_raw_owners = os.getenv("OWNER_IDS", "7899153362")
OWNER_IDS: set[int] = {
    int(part.strip())
    for part in _raw_owners.split(",")
    if part.strip().lstrip("-").isdigit()
}
