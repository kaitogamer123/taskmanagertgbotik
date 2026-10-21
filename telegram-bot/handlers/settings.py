from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.settings_repo import (
    get_settings,
    set_evening_time,
    set_morning_time,
    toggle_evening,
    toggle_morning,
)
from keyboards.inline import settings_keyboard
from states import SettingsStates
from utils.date_utils import parse_time

router = Router(name="settings")


def _settings_text(settings) -> str:
    morning = "включены ✅" if settings.morning_enabled else "выключены 🚫"
    evening = "включены ✅" if settings.evening_enabled else "выключены 🚫"
    return (
        "🔔 Настройка уведомлений\n\n"
        f"🌅 Утренняя сводка (планы на сегодня): {settings.morning_time}, {morning}\n"
        f"🌙 Вечерняя сводка (планы на завтра): {settings.evening_time}, {evening}\n\n"
        "Также я напомню про конкретную задачу за выбранное время до её начала — "
        "это настраивается при добавлении задачи или кнопкой «Изменить время "
        "оповещения» в описании задачи."
    )


@router.message(Command("notify", "Notify", "settings", "Settings"))
async def cmd_notify(message: Message, db: UserDB) -> None:
    settings = get_settings(db)
    await message.answer(_settings_text(settings), reply_markup=settings_keyboard(settings))


@router.callback_query(F.data == "settings_toggle:morning")
async def toggle_morning_cb(callback: CallbackQuery, db: UserDB) -> None:
    settings = get_settings(db)
    toggle_morning(db, not settings.morning_enabled)
    settings = get_settings(db)
    await callback.answer()
    await callback.message.edit_text(_settings_text(settings), reply_markup=settings_keyboard(settings))


@router.callback_query(F.data == "settings_toggle:evening")
async def toggle_evening_cb(callback: CallbackQuery, db: UserDB) -> None:
    settings = get_settings(db)
    toggle_evening(db, not settings.evening_enabled)
    settings = get_settings(db)
    await callback.answer()
    await callback.message.edit_text(_settings_text(settings), reply_markup=settings_keyboard(settings))


@router.callback_query(F.data == "settings_edit:morning")
async def edit_morning_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_morning_time)
    await callback.answer()
    await callback.message.answer(
        "Во сколько присылать утреннюю сводку с планами на сегодня? "
        "Напиши время, например 08:00."
    )


@router.callback_query(F.data == "settings_edit:evening")
async def edit_evening_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_evening_time)
    await callback.answer()
    await callback.message.answer(
        "Во сколько присылать вечернюю сводку с планами на завтра? "
        "Напиши время, например 20:00."
    )


@router.message(StateFilter(SettingsStates.waiting_morning_time))
async def process_morning_time(message: Message, state: FSMContext, db: UserDB) -> None:
    time_value = parse_time(message.text or "")
    if time_value is None:
        await message.answer("Не понял время 🙈 Напиши в формате ЧЧ:ММ, например 08:30.")
        return
    set_morning_time(db, time_value)
    await state.clear()
    settings = get_settings(db)
    await message.answer(
        f"Готово ✅ Утренняя сводка теперь будет приходить в {time_value}.",
    )
    await message.answer(_settings_text(settings), reply_markup=settings_keyboard(settings))


@router.message(StateFilter(SettingsStates.waiting_evening_time))
async def process_evening_time(message: Message, state: FSMContext, db: UserDB) -> None:
    time_value = parse_time(message.text or "")
    if time_value is None:
        await message.answer("Не понял время 🙈 Напиши в формате ЧЧ:ММ, например 20:00.")
        return
    set_evening_time(db, time_value)
    await state.clear()
    settings = get_settings(db)
    await message.answer(
        f"Готово ✅ Вечерняя сводка теперь будет приходить в {time_value}.",
    )
    await message.answer(_settings_text(settings), reply_markup=settings_keyboard(settings))
