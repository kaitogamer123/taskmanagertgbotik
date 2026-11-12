from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TimezoneStates(StatesGroup):
    waiting_hour = State()


class NewPlanStates(StatesGroup):
    waiting_date = State()
    waiting_time_start = State()
    waiting_time_end = State()
    waiting_title = State()
    waiting_description = State()
    waiting_reminder = State()


class EveryNStates(StatesGroup):
    waiting_title = State()
    waiting_time_start = State()
    waiting_time_end = State()
    waiting_repeat_type = State()
    waiting_interval_value = State()
    waiting_weekday_select = State()
    waiting_monthly_value = State()
    waiting_yearly_value = State()
    waiting_start_date = State()
    waiting_reminder = State()


class ReminderEditStates(StatesGroup):
    waiting_value = State()


class SettingsStates(StatesGroup):
    waiting_morning_time = State()
    waiting_evening_time = State()
