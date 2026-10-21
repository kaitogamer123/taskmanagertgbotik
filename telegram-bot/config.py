"""
Конфигурация бота.
Токен читается из переменной окружения BOT_TOKEN (через .env файл).
"""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

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

# Часовой пояс, по которому считаются утренние/вечерние уведомления
# и напоминания "за N минут до задачи". Можно переопределить в .env.
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
try:
    TIMEZONE = ZoneInfo(TIMEZONE_NAME)
except Exception:  # noqa: BLE001 - на случай опечатки в .env
    TIMEZONE = ZoneInfo("UTC")

# Настройки уведомлений по умолчанию (используются для новых пользователей)
DEFAULT_MORNING_TIME = "08:00"
DEFAULT_EVENING_TIME = "20:00"

# Как часто (в секундах) фоновый планировщик проверяет, не пора ли
# отправить ежедневную сводку или напоминание о задаче
NOTIFIER_POLL_INTERVAL = int(os.getenv("NOTIFIER_POLL_INTERVAL", "30"))
