"""
Настройка часового пояса пользователя:
  - при самом первом запуске (через TimezoneGateMiddleware -> TimezoneStates.waiting_hour);
  - по команде /changeTime (в любом регистре) или кнопке в меню «⚙️ Настройка времени».
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
    set_user_timezone_offset,
)
from handlers.start import WELCOME_TEXT
from keyboards.inline import hour_picker_keyboard
from keyboards.reply import MAIN_MENU_BUTTONS, main_reply_keyboard
from states import TimezoneStates
from utils.clock import (
    calc_utc_offset_hours,
    format_utc_offset,
    now_for_offset,
    now_for_user,
    parse_user_hour,
)

router = Router(name="timezone_cmd")


def _ask_change_time_text(db: UserDB) -> str:
    settings = get_settings(db)
    current_tz = format_utc_offset(settings.utc_offset)
    current_local = now_for_user(db).strftime("%H:%M")
    return (
        f"🌍 <b>Настройка часового пояса</b>\n"
        f"Сейчас установлен: <b>{current_tz}</b> (у тебя по нему <b>{current_local}</b>).\n\n"
        "🕐 <b>Сколько у тебя сейчас времени?</b>\n"
        "Достаточно написать или выбрать кнопкой ниже, <b>какой у тебя сейчас час</b> "
        "(от <code>0</code> до <code>23</code>, например <code>16</code> или <code>16:20</code>):"
    )


@router.message(Command("changeTime", "changetime", ignore_case=True))
async def cmd_change_time(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    await state.set_state(TimezoneStates.waiting_hour)
    await state.update_data(first_setup=False)
    await message.answer(
        _ask_change_time_text(db),
        reply_markup=hour_picker_keyboard(allow_cancel=True),
    )


@router.callback_query(F.data == "tz_change")
async def cb_change_time(
    callback: CallbackQuery, state: FSMContext, db: UserDB
) -> None:
    await state.clear()
    await state.set_state(TimezoneStates.waiting_hour)
    await state.update_data(first_setup=False)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            _ask_change_time_text(db),
            reply_markup=hour_picker_keyboard(allow_cancel=True),
        )


@router.callback_query(F.data == "tz_cancel")
async def cb_cancel_tz(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Изменение часового пояса отменено")
    if callback.message:
        await callback.message.edit_text("Изменение часового пояса отменено 👌")


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
    local_now = now_for_offset(offset)

    # Если это совершенно новый пользователь — заполняем стартовые демо-планы
    # строго по ЕГО реальной локальной дате! При смене пояса демо не подсыпаем.
    if first_setup and not settings.demo_seeded:
        seed_demo_data(db.conn, today=local_now.date())
        mark_demo_seeded(db)

    await state.clear()

    tz_label = format_utc_offset(offset)
    info_text = (
        f"✅ Готово! Определил твой часовой пояс: <b>{tz_label}</b> "
        f"(сейчас у тебя <b>{local_now.strftime('%H:%M')}</b>).\n\n"
        "💡 <b>На будущее:</b> если вдруг переедешь куда-то в другой часовой пояс "
        "или случайно опечатался сейчас — ты всегда можешь изменить свой часовой пояс "
        "командой <b>/changeTime</b> (или через кнопку <b>«⚙️ Настройка времени»</b>)."
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
        "Сначала давай узнаем твой часовой пояс 🕐\n"
        "Напиши, какой у тебя сейчас час (число от <code>0</code> до <code>23</code>), "
        "или выбери кнопку выше 👆"
    )
