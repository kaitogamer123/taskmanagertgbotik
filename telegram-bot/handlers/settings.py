from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.settings_repo import (
    get_settings,
    set_evening_time,
    set_morning_time,
    set_quiet_hours,
    set_skip_empty_digest,
    toggle_evening,
    toggle_morning,
)
from keyboards.inline import cancel_inline_keyboard, settings_keyboard
from keyboards.reply import BTN_TIME_SETTINGS, MAIN_MENU_BUTTONS
from states import SettingsStates
from utils.clock import format_utc_offset, now_for_user
from utils.date_utils import parse_time

router = Router(name="settings")


def build_settings_text(db: UserDB) -> str:
    settings = get_settings(db)
    local_str = now_for_user(db).strftime("%H:%M")
    tz_label = format_utc_offset(settings.utc_offset)
    morning = "включены ✅" if settings.morning_enabled else "выключены 🚫"
    evening = "включены ✅" if settings.evening_enabled else "выключены 🚫"
    skip_empty = "не присылать" if settings.skip_empty_digest else "присылать"
    quiet = "включены" if settings.quiet_enabled else "выключены"
    return (
        "⚙️ <b>Настройка времени и уведомлений</b>\n\n"
        f"🌍 <b>Часовой пояс:</b> {tz_label} (сейчас у тебя <b>{local_str}</b>)\n"
        f"🌅 <b>Утренняя сводка</b> (планы на сегодня): {settings.morning_time}, {morning}\n"
        f"🌙 <b>Вечерняя сводка</b> (планы на завтра): {settings.evening_time}, {evening}\n"
        f"🔕 <b>Пустые сводки:</b> {skip_empty}\n"
        f"🌙 <b>Тихие часы:</b> {quiet} ({settings.quiet_start}–{settings.quiet_end}); "
        "напоминания ночью переносятся на утро\n\n"
        "💡 Изменить часовой пояс также всегда можно командой <b>/changeTime</b>.\n"
        "Напоминание за N минут до конкретной задачи настраивается при её создании "
        "или кнопкой «⏰ Изменить время оповещения» внутри задачи."
    )


async def send_time_settings(message: Message, db: UserDB) -> None:
    settings = get_settings(db)
    local_str = now_for_user(db).strftime("%H:%M")
    await message.answer(
        build_settings_text(db),
        reply_markup=settings_keyboard(settings, local_str),
    )


@router.message(Command("notify", "settings", ignore_case=True))
@router.message(F.text == BTN_TIME_SETTINGS)
async def cmd_notify(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    await send_time_settings(message, db)


@router.callback_query(F.data == "time_menu")
async def cb_time_menu(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    await callback.answer()
    settings = get_settings(db)
    local_str = now_for_user(db).strftime("%H:%M")
    if callback.message:
        await callback.message.edit_text(
            build_settings_text(db),
            reply_markup=settings_keyboard(settings, local_str),
        )


@router.callback_query(F.data == "settings_toggle:morning")
async def toggle_morning_cb(callback: CallbackQuery, db: UserDB) -> None:
    settings = get_settings(db)
    toggle_morning(db, not settings.morning_enabled)
    settings = get_settings(db)
    local_str = now_for_user(db).strftime("%H:%M")
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            build_settings_text(db),
            reply_markup=settings_keyboard(settings, local_str),
        )


@router.callback_query(F.data == "settings_toggle:evening")
async def toggle_evening_cb(callback: CallbackQuery, db: UserDB) -> None:
    settings = get_settings(db)
    toggle_evening(db, not settings.evening_enabled)
    settings = get_settings(db)
    local_str = now_for_user(db).strftime("%H:%M")
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            build_settings_text(db),
            reply_markup=settings_keyboard(settings, local_str),
        )


@router.callback_query(F.data == "settings_edit:morning")
async def edit_morning_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_morning_time)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Во сколько присылать утреннюю сводку с планами на сегодня?\n"
            "Напиши время в формате ЧЧ:ММ, например <code>08:00</code>:",
            reply_markup=cancel_inline_keyboard(),
        )


@router.callback_query(F.data == "settings_edit:evening")
async def edit_evening_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_evening_time)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Во сколько присылать вечернюю сводку с планами на завтра?\n"
            "Напиши время в формате ЧЧ:ММ, например <code>20:00</code>:",
            reply_markup=cancel_inline_keyboard(),
        )


@router.message(
    StateFilter(SettingsStates.waiting_morning_time),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_morning_time(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    time_value = parse_time(message.text or "")
    if time_value is None:
        await message.answer(
            "Не понял время 🙈 Напиши в формате ЧЧ:ММ, например <code>08:30</code>."
        )
        return
    set_morning_time(db, time_value)
    await state.clear()
    await message.answer(
        f"Готово ✅ Утренняя сводка теперь будет приходить в <b>{time_value}</b>."
    )
    await send_time_settings(message, db)


@router.message(
    StateFilter(SettingsStates.waiting_evening_time),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_evening_time(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    time_value = parse_time(message.text or "")
    if time_value is None:
        await message.answer(
            "Не понял время 🙈 Напиши в формате ЧЧ:ММ, например <code>20:00</code>."
        )
        return
    set_evening_time(db, time_value)
    await state.clear()
    await message.answer(
        f"Готово ✅ Вечерняя сводка теперь будет приходить в <b>{time_value}</b>."
    )
    await send_time_settings(message, db)


async def _safe_edit_settings(message, db: UserDB) -> None:
    settings = get_settings(db)
    local_str = now_for_user(db).strftime("%H:%M")
    try:
        await message.edit_text(
            build_settings_text(db),
            reply_markup=settings_keyboard(settings, local_str),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


@router.callback_query(F.data == "settings_toggle:skip_empty")
async def toggle_skip_empty_cb(callback: CallbackQuery, db: UserDB) -> None:
    settings = get_settings(db)
    set_skip_empty_digest(db, not settings.skip_empty_digest)
    await callback.answer()
    if callback.message:
        await _safe_edit_settings(callback.message, db)


@router.callback_query(F.data == "settings_toggle:quiet")
async def toggle_quiet_cb(callback: CallbackQuery, db: UserDB) -> None:
    settings = get_settings(db)
    set_quiet_hours(db, enabled=not settings.quiet_enabled)
    await callback.answer()
    if callback.message:
        await _safe_edit_settings(callback.message, db)


@router.callback_query(F.data == "settings_edit:quiet_start")
async def edit_quiet_start_cb(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.set_state(SettingsStates.waiting_quiet_start)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Во сколько начинаются тихие часы? Напиши время в формате ЧЧ:ММ, "
            "например <code>23:00</code>:",
            reply_markup=cancel_inline_keyboard(),
        )


@router.callback_query(F.data == "settings_edit:quiet_end")
async def edit_quiet_end_cb(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.set_state(SettingsStates.waiting_quiet_end)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Во сколько заканчиваются тихие часы? Напиши время в формате ЧЧ:ММ, "
            "например <code>08:00</code>:",
            reply_markup=cancel_inline_keyboard(),
        )


@router.message(
    StateFilter(SettingsStates.waiting_quiet_start),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_quiet_start(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    time_value = parse_time(message.text or "")
    if time_value is None:
        await message.answer(
            "Не понял время 🙈 Напиши в формате ЧЧ:ММ, например <code>23:00</code>."
        )
        return
    set_quiet_hours(db, start=time_value)
    await state.clear()
    await message.answer(f"Готово ✅ Тихие часы начинаются в <b>{time_value}</b>.")
    await send_time_settings(message, db)


@router.message(
    StateFilter(SettingsStates.waiting_quiet_end),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_quiet_end(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    time_value = parse_time(message.text or "")
    if time_value is None:
        await message.answer(
            "Не понял время 🙈 Напиши в формате ЧЧ:ММ, например <code>08:00</code>."
        )
        return
    set_quiet_hours(db, end=time_value)
    await state.clear()
    await message.answer(f"Готово ✅ Тихие часы заканчиваются в <b>{time_value}</b>.")
    await send_time_settings(message, db)
