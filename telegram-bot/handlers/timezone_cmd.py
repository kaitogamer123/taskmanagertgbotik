"""
Настройка часового пояса пользователя:
  - при первом запуске — выбор города/IANA-зоны;
  - по команде /changeTime или кнопке «⚙️ Настройка времени»;
  - резервный режим «по текущему часу» для старых клиентов.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.db_manager import UserDB
from database.seed import seed_demo_data
from database.settings_repo import (
    get_settings,
    mark_demo_seeded,
    set_user_timezone_name,
    set_user_timezone_offset,
)
from handlers.start import WELCOME_TEXT
from keyboards.inline import hour_picker_keyboard, timezone_picker_keyboard
from keyboards.reply import MAIN_MENU_BUTTONS, main_reply_keyboard
from states import TimezoneStates
from utils.clock import (
    calc_utc_offset_hours,
    format_zone_offset,
    get_zone,
    now_in_zone,
    now_for_user,
    parse_user_hour,
    zone_utc_offset_hours,
)
from utils.timezones import normalize_zone_input, zone_label

router = Router(name="timezone_cmd")


def _current_zone_text(db: UserDB) -> str:
    settings = get_settings(db)
    current = format_zone_offset(settings.timezone_name, settings.utc_offset)
    zone_note = f" · {settings.timezone_name}" if settings.timezone_name else ""
    current_local = now_for_user(db).strftime("%H:%M")
    return (
        f"Сейчас установлен: <b>{current}</b>{zone_note} "
        f"(у тебя по нему <b>{current_local}</b>)."
    )


def _ask_timezone_text(db: UserDB) -> str:
    return (
        "🌍 <b>Настройка часового пояса</b>\n"
        f"{_current_zone_text(db)}\n\n"
        "Выбери свой город/зону кнопкой ниже. Если города нет — "
        "«⌨️ Другой город» или «🕐 По текущему времени».\n\n"
        "<i>Часовой пояс нужен для «сегодня/завтра», напоминаний и перехода "
        "на летнее/зимнее время.</i>"
    )


def _first_setup_prompt() -> str:
    return (
        "👋 Привет! Я бот-органайзер для твоих планов 🗓\n\n"
        "Перед началом работы выбери свой <b>город или часовой пояс</b>, "
        "чтобы «сегодня/завтра» и напоминания работали точно по твоему времени.\n\n"
        "Если нужного города нет — нажми «⌨️ Другой город» и напиши "
        "название (например, <code>Москва</code> или <code>Europe/Moscow</code>)."
    )


@router.message(Command("changeTime", "changetime", ignore_case=True))
async def cmd_change_time(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    await state.set_state(TimezoneStates.waiting_zone)
    await state.update_data(first_setup=False)
    await message.answer(
        _ask_timezone_text(db),
        reply_markup=timezone_picker_keyboard(allow_cancel=True),
    )


@router.callback_query(F.data == "tz_change")
async def cb_change_time(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    await state.set_state(TimezoneStates.waiting_zone)
    await state.update_data(first_setup=False)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            _ask_timezone_text(db),
            reply_markup=timezone_picker_keyboard(allow_cancel=True),
        )


@router.callback_query(F.data == "tz_cancel")
async def cb_cancel_tz(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Изменение часового пояса отменено")
    if callback.message:
        await callback.message.edit_text("Изменение часового пояса отменено 👌")


async def _apply_timezone(
    target_message: Message,
    state: FSMContext,
    db: UserDB,
    zone_name: str,
    first_setup: bool,
) -> None:
    offset = zone_utc_offset_hours(zone_name) or 0
    set_user_timezone_name(db, zone_name, offset)

    settings = get_settings(db)
    local_now = now_in_zone(zone_name, offset)

    if first_setup and not settings.demo_seeded:
        seed_demo_data(db.conn, today=local_now.date())
        mark_demo_seeded(db)

    await state.clear()

    tz_label = format_zone_offset(zone_name, offset)
    info_text = (
        f"✅ Готово! Часовой пояс: <b>{zone_label(zone_name)}</b> "
        f"({tz_label}).\n"
        f"Сейчас у тебя <b>{local_now.strftime('%H:%M')}</b>.\n\n"
        "💡 Если переедешь или ошибёшься — измени пояс командой "
        "<b>/changeTime</b> или кнопкой <b>«⚙️ Настройка времени»</b>."
    )
    await target_message.answer(info_text)
    if first_setup:
        await target_message.answer(WELCOME_TEXT, reply_markup=main_reply_keyboard())
    else:
        await target_message.answer(
            "Меню всегда снизу 👇", reply_markup=main_reply_keyboard()
        )


@router.callback_query(F.data.startswith("tz_set:"))
async def cb_set_zone(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    zone_name = (callback.data or "").split(":", 1)[1]
    if get_zone(zone_name) is None:
        await callback.answer("Неизвестная зона", show_alert=True)
        return
    data = await state.get_data()
    first_setup = bool(data.get("first_setup", False))
    await callback.answer()
    if callback.message:
        await _apply_timezone(callback.message, state, db, zone_name, first_setup)


@router.callback_query(F.data == "tz_other")
async def cb_other_zone(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.set_state(TimezoneStates.waiting_zone_name)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "⌨️ Напиши город или IANA-зону, например:\n"
            "<code>Москва</code>, <code>Алматы</code>, <code>Europe/Moscow</code>, "
            "<code>Asia/Almaty</code>."
        )


@router.callback_query(F.data == "tz_hour_mode")
async def cb_hour_mode(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.set_state(TimezoneStates.waiting_hour)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "🕐 Напиши, какой у тебя сейчас час (0–23), например <code>14</code> "
            "или <code>14:30</code>. Можно выбрать кнопкой:",
            reply_markup=hour_picker_keyboard(allow_cancel=True),
        )


async def _apply_user_hour(
    target_message: Message,
    state: FSMContext,
    db: UserDB,
    hour: int,
) -> None:
    data = await state.get_data()
    first_setup = bool(data.get("first_setup", False))

    offset = calc_utc_offset_hours(hour)
    set_user_timezone_offset(db, offset)

    settings = get_settings(db)
    local_now = now_in_zone(None, offset)

    if first_setup and not settings.demo_seeded:
        seed_demo_data(db.conn, today=local_now.date())
        mark_demo_seeded(db)

    await state.clear()

    tz_label = format_zone_offset(None, offset)
    info_text = (
        f"✅ Готово! Определил твой часовой пояс: <b>{tz_label}</b> "
        f"(сейчас у тебя <b>{local_now.strftime('%H:%M')}</b>).\n\n"
        "💡 Если переедешь или ошибёшься — измени пояс командой "
        "<b>/changeTime</b> или кнопкой <b>«⚙️ Настройка времени»</b>."
    )

    if first_setup:
        await target_message.answer(info_text)
        await target_message.answer(WELCOME_TEXT, reply_markup=main_reply_keyboard())
    else:
        await target_message.answer(info_text, reply_markup=main_reply_keyboard())


@router.callback_query(
    StateFilter(TimezoneStates.waiting_hour), F.data.startswith("tz_hour:")
)
async def cb_pick_hour(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    _, hour_str = (callback.data or "").split(":", 1)
    hour = int(hour_str)
    await callback.answer()
    if callback.message:
        await _apply_user_hour(callback.message, state, db, hour)


@router.message(
    StateFilter(TimezoneStates.waiting_zone, TimezoneStates.waiting_zone_name),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_zone_text(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    raw = (message.text or "").strip()
    zone_name = normalize_zone_input(raw)
    if zone_name is not None:
        data = await state.get_data()
        await _apply_timezone(
            message, state, db, zone_name, bool(data.get("first_setup", False))
        )
        return

    hour = parse_user_hour(raw)
    if hour is not None:
        await _apply_user_hour(message, state, db, hour)
        return

    await message.answer(
        "Не понял 🙈 Напиши город (например, <code>Москва</code>, "
        "<code>Алматы</code>) или зону (<code>Europe/Moscow</code>), "
        "либо нажми «🕐 По текущему времени»."
    )


@router.message(
    StateFilter(TimezoneStates.waiting_hour),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_hour_text(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    hour = parse_user_hour(message.text or "")
    if hour is None:
        await message.answer(
            "Не смог понять час 🙈\n"
            "Напиши, пожалуйста, просто число от <code>0</code> до <code>23</code> — "
            "какой у тебя сейчас час (например <code>14</code> или <code>14:30</code>), "
            "либо нажми кнопку выше 👆"
        )
        return
    await _apply_user_hour(message, state, db, hour)


@router.message(StateFilter(TimezoneStates.waiting_hour))
async def fallback_first_setup_hour(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    """Если часовой пояс ещё не задан, но пользователь нажал текстовую кнопку меню."""
    data = await state.get_data()
    if not data.get("first_setup"):
        return
    await message.answer(
        "Сначала давай настроим часовой пояс 🕐\n"
        "Выбери город кнопкой или напиши его текстом, либо нажми "
        "«🕐 По текущему времени»."
    )
