from __future__ import annotations

from handlers.guide import (
    GUIDE_BY_KEY,
    GUIDE_SECTIONS,
    guide_menu_keyboard,
    guide_section_keyboard,
)
from utils.text import MAX_MESSAGE


def test_guide_sections_fit_telegram() -> None:
    assert GUIDE_SECTIONS
    for key, title, text in GUIDE_SECTIONS:
        assert key in GUIDE_BY_KEY
        assert title
        assert len(text) <= MAX_MESSAGE, (key, len(text))
        for row in guide_section_keyboard(key).inline_keyboard:
            for button in row:
                assert len((button.callback_data or "").encode()) <= 64


def test_guide_menu_keyboard() -> None:
    keyboard = guide_menu_keyboard()
    assert keyboard.inline_keyboard
    for row in keyboard.inline_keyboard:
        for button in row:
            assert len((button.callback_data or "").encode()) <= 64
