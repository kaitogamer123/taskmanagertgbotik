"""
Точка входа Telegram-бота на aiogram 3.

Запуск:
    python bot.py

Перед запуском убедись, что:
  1) создан файл .env (скопируй .env.example) с переменной BOT_TOKEN;
  2) установлены зависимости из requirements.txt (см. README.md / setup.sh / update.sh).
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BotCommand, ErrorEvent

from config import BASE_DIR, BOT_TOKEN, BOT_VERSION, OWNER_IDS
from database.db_manager import ensure_index
from handlers import (
    broadcast,
    database_cmd,
    everyn,
    feedback,
    myplans,
    newplan,
    notes,
    settings,
    snooze,
    start,
    system_cmd,
    timezone_cmd,
)
from middlewares.antispam import AntispamMiddleware
from middlewares.db_middleware import UserDBMiddleware
from middlewares.timezone_middleware import TimezoneGateMiddleware
from services.auto_pull import run_auto_pull
from services.notifier import run_notifier

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"

_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(), _file_handler],
)
# По каждому апдейту aiogram пишет DEBUG-строки — на сервере это лишний объём лога.
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

LOCK_FILE = BASE_DIR / "bot.pid"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:  # noqa: BLE001 - на Windows поведение отличается
        return False
    return True


def ensure_single_instance() -> None:
    """Не даём запустить второй экземпляр бота (иначе TelegramConflictError)."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pid = 0
        if pid and pid != os.getpid() and _pid_alive(pid):
            logger.error(
                "Уже запущен другой экземпляр бота (PID %s). Выхожу, "
                "чтобы не было конфликта polling.",
                pid,
            )
            sys.exit(1)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")


def release_lock() -> None:
    try:
        if (
            LOCK_FILE.exists()
            and LOCK_FILE.read_text(encoding="utf-8").strip() == str(os.getpid())
        ):
            LOCK_FILE.unlink()
    except OSError:
        pass


atexit.register(release_lock)


async def set_bot_commands(bot: Bot) -> None:
    # В setMyCommands Telegram разрешает только строчные латинские буквы, цифры и "_".
    # В самих хендлерах команды работают без учёта регистра (/changeTime, /MyPlans, /everyN и т.д.).
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Начало работы с ботом"),
                BotCommand(command="help", description="Справка и примеры"),
                BotCommand(command="myplans", description="Планы на ближайшую неделю"),
                BotCommand(command="alldays", description="В какие дни есть задачи"),
                BotCommand(command="newplan", description="Добавить новую задачу"),
                BotCommand(command="everyn", description="Добавить повторяющуюся задачу"),
                BotCommand(command="notes", description="Заметки и папки"),
                BotCommand(command="find", description="Поиск по задачам и заметкам"),
                BotCommand(command="stats", description="Статистика выполнения"),
                BotCommand(command="feedback", description="Написать владельцу бота"),
                BotCommand(command="delete", description="Удалить задачу"),
                BotCommand(command="changetime", description="Изменить свой часовой пояс"),
                BotCommand(command="notify", description="Настройка времени и уведомлений"),
                BotCommand(command="database", description="Получить файл базы данных"),
                BotCommand(command="cancel", description="Отменить текущее действие"),
            ]
        )
    except TelegramBadRequest:
        logger.exception("Не удалось обновить список команд бота")


async def main() -> None:
    if not BOT_TOKEN:
        logger.error(
            "Не задан BOT_TOKEN. Создай файл .env рядом с bot.py "
            "(см. .env.example) и укажи токен, полученный у @BotFather."
        )
        sys.exit(1)

    ensure_single_instance()
    index = ensure_index()
    logger.info("Версия %s, пользователей в индексе: %s", BOT_VERSION, len(index))

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.error("Необработанная ошибка", exc_info=event.exception)
        error_text = f"{type(event.exception).__name__}: {event.exception}"[:300]
        for owner in OWNER_IDS:
            try:
                await bot.send_message(
                    owner, f"⚠️ Ошибка в боте:\n<code>{error_text}</code>"
                )
            except Exception:  # noqa: BLE001 - не должны падать в обработчике ошибок
                pass
        try:
            if event.update.message:
                await event.update.message.answer(
                    "Что-то пошло не так 🙈 Я уже записал ошибку."
                )
            elif event.update.callback_query:
                await event.update.callback_query.answer(
                    "Ошибка, попробуй ещё раз", show_alert=True
                )
        except Exception:  # noqa: BLE001
            pass
        return True

    # 1. Открываем персональную SQLite БД пользователя
    antispam = AntispamMiddleware()
    dp.message.middleware(antispam)
    dp.callback_query.middleware(antispam)

    db_middleware = UserDBMiddleware()
    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)

    # 2. В самом начале работы узнаём текущий час пользователя для расчёта часового пояса
    tz_middleware = TimezoneGateMiddleware()
    dp.message.middleware(tz_middleware)
    dp.callback_query.middleware(tz_middleware)

    # 3. Регистрация роутеров (универсальный разбор дат в myplans идёт последним)
    dp.include_router(system_cmd.router)
    dp.include_router(broadcast.router)
    dp.include_router(feedback.router)
    dp.include_router(timezone_cmd.router)
    dp.include_router(start.router)
    dp.include_router(database_cmd.router)
    dp.include_router(settings.router)
    dp.include_router(newplan.router)
    dp.include_router(everyn.router)
    dp.include_router(notes.router)
    dp.include_router(snooze.router)
    dp.include_router(myplans.router)

    await set_bot_commands(bot)

    notifier_task = asyncio.create_task(run_notifier(bot))
    auto_pull_task = asyncio.create_task(run_auto_pull(bot))

    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=False)
    try:
        await dp.start_polling(bot)
    finally:
        notifier_task.cancel()
        auto_pull_task.cancel()
        # Дожидаемся отмены фоновых задач, чтобы не оставлять «висящие» корутины
        await asyncio.gather(notifier_task, auto_pull_task, return_exceptions=True)
        await bot.session.close()
        release_lock()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
