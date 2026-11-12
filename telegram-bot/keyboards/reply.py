"""Постоянная нижняя клавиатура главного меню (ReplyKeyboardMarkup)."""
from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

BTN_MY_PLANS = "📅 Мои планы"
BTN_ALL_DAYS = "📋 Дни с задачами"
BTN_NEW_PLAN = "➕ Новая задача"
BTN_EVERY_N = "🔁 Повторяющаяся"
BTN_DELETE_TASK = "🗑 Удалить задачу"
BTN_TIME_SETTINGS = "⚙️ Настройка времени"

MAIN_MENU_BUTTONS = {
    BTN_MY_PLANS,
    BTN_ALL_DAYS,
    BTN_NEW_PLAN,
    BTN_EVERY_N,
    BTN_DELETE_TASK,
    BTN_TIME_SETTINGS,
}


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=BTN_MY_PLANS)
    builder.button(text=BTN_ALL_DAYS)
    builder.button(text=BTN_NEW_PLAN)
    builder.button(text=BTN_EVERY_N)
    builder.button(text=BTN_DELETE_TASK)
    builder.button(text=BTN_TIME_SETTINGS)
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)
