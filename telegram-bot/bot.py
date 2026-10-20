"""
Точка входа Telegram-бота на aiogram 3.

Запуск:
    python bot.py

Перед запуском убедись, что:
  1) создан файл .env (скопируй .env.example) с переменной BOT_TOKEN;
  2) установлены зависимости из requirements.txt (см. README.md / setup.sh).
"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from config import BOT_TOKEN
from handlers import database_cmd, everyn, myplans, newplan, start
from middlewares.db_middleware import UserDBMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начало работы с ботом"),
            BotCommand(command="MyPlans", description="Посмотреть свои планы"),
            BotCommand(command="NewPlan", description="Добавить новую задачу"),
            BotCommand(command="everyN", description="Добавить повторяющуюся задачу"),
            BotCommand(command="database", description="Получить файл базы данных"),
        ]
    )


async def main() -> None:
    if not BOT_TOKEN:
        logger.error(
            "Не задан BOT_TOKEN. Создай файл .env рядом с bot.py "
            "(см. .env.example) и укажи токен, полученный у @BotFather."
        )
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    db_middleware = UserDBMiddleware()
    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)

    # Порядок важен: команды и FSM-сценарии регистрируются раньше,
    # универсальный обработчик текста (дат) — в самом конце, внутри myplans.
    dp.include_router(start.router)
    dp.include_router(database_cmd.router)
    dp.include_router(newplan.router)
    dp.include_router(everyn.router)
    dp.include_router(myplans.router)

    await set_bot_commands(bot)

    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
