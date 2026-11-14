from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class TimezoneStates(StatesGroup):
    waiting_zone = State()
    waiting_zone_name = State()
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


class PlanEditStates(StatesGroup):
    waiting_value = State()


class SettingsStates(StatesGroup):
    waiting_morning_time = State()
    waiting_evening_time = State()
    waiting_quiet_start = State()
    waiting_quiet_end = State()


class NotesStates(StatesGroup):
    waiting_new_text = State()
    waiting_folder_name = State()
    waiting_note_text = State()
    waiting_note_title = State()
    waiting_note_item = State()
    waiting_note_file = State()
    waiting_note_date = State()
    waiting_search = State()


class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_confirm = State()


class FeedbackStates(StatesGroup):
    waiting_text = State()
