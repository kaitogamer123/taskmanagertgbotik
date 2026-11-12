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
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BotCommand

from config import BOT_TOKEN
from handlers import (
    database_cmd,
    everyn,
    myplans,
    newplan,
    settings,
    start,
    system_cmd,
    timezone_cmd,
)
from middlewares.db_middleware import UserDBMiddleware
from middlewares.timezone_middleware import TimezoneGateMiddleware
from services.auto_pull import run_auto_pull
from services.notifier import run_notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
# По каждому апдейту aiogram пишет DEBUG-строки — на сервере это лишний объём лога.
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def set_bot_commands(bot: Bot) -> None:
    # В setMyCommands Telegram разрешает только строчные латинские буквы, цифры и "_".
    # В самих хендлерах команды работают без учёта регистра (/changeTime, /MyPlans, /everyN и т.д.).
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Начало работы с ботом"),
                BotCommand(command="myplans", description="Планы на ближайшую неделю"),
                BotCommand(command="alldays", description="В какие дни есть задачи"),
                BotCommand(command="newplan", description="Добавить новую задачу"),
                BotCommand(command="everyn", description="Добавить повторяющуюся задачу"),
                BotCommand(command="changetime", description="Изменить свой часовой пояс"),
                BotCommand(command="notify", description="Настройка времени и уведомлений"),
                BotCommand(command="database", description="Получить файл базы данных"),
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

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # 1. Открываем персональную SQLite БД пользователя
    db_middleware = UserDBMiddleware()
    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)

    # 2. В самом начале работы узнаём текущий час пользователя для расчёта часового пояса
    tz_middleware = TimezoneGateMiddleware()
    dp.message.middleware(tz_middleware)
    dp.callback_query.middleware(tz_middleware)

    # 3. Регистрация роутеров (универсальный разбор дат в myplans идёт последним)
    dp.include_router(system_cmd.router)
    dp.include_router(timezone_cmd.router)
    dp.include_router(start.router)
    dp.include_router(database_cmd.router)
    dp.include_router(settings.router)
    dp.include_router(newplan.router)
    dp.include_router(everyn.router)
    dp.include_router(myplans.router)

    await set_bot_commands(bot)

    notifier_task = asyncio.create_task(run_notifier(bot))
    auto_pull_task = asyncio.create_task(run_auto_pull(bot))

    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        notifier_task.cancel()
        auto_pull_task.cancel()
        # Дожидаемся отмены фоновых задач, чтобы не оставлять «висящие» корутины
        await asyncio.gather(notifier_task, auto_pull_task, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
