"""Постоянная нижняя клавиатура главного меню (ReplyKeyboardMarkup)."""
from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

BTN_ACTIVE_PLANS = "📅 Активные планы"
BTN_MY_PLANS = BTN_ACTIVE_PLANS  # обратная совместимость
BTN_OLD_PLANS = "📅 Мои планы"
BTN_HISTORY = "🕓 История планов"
BTN_ALL_DAYS = "📋 Дни с задачами"
BTN_NEW_PLAN = "➕ Новая задача"
BTN_EVERY_N = "🔁 Повторяющаяся"
BTN_DELETE_TASK = "🗑 Удалить задачу"
BTN_TIME_SETTINGS = "⚙️ Настройка времени"
BTN_NOTES = "📝 Заметки"
BTN_FEEDBACK = "💬 Обратная связь"
BTN_HELP = "📖 Помощь"

MAIN_MENU_BUTTONS = {
    BTN_ACTIVE_PLANS,
    BTN_OLD_PLANS,
    BTN_HISTORY,
    BTN_ALL_DAYS,
    BTN_NEW_PLAN,
    BTN_EVERY_N,
    BTN_DELETE_TASK,
    BTN_TIME_SETTINGS,
    BTN_NOTES,
    BTN_FEEDBACK,
    BTN_HELP,
}


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=BTN_ACTIVE_PLANS)
    builder.button(text=BTN_HISTORY)
    builder.button(text=BTN_ALL_DAYS)
    builder.button(text=BTN_NEW_PLAN)
    builder.button(text=BTN_EVERY_N)
    builder.button(text=BTN_DELETE_TASK)
    builder.button(text=BTN_NOTES)
    builder.button(text=BTN_TIME_SETTINGS)
    builder.button(text=BTN_FEEDBACK)
    builder.button(text=BTN_HELP)
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)
