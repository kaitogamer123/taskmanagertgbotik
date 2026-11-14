"""Ограничения длины и безопасная обрезка текста для Telegram.

Telegram не принимает сообщения длиннее 4096 символов, а очень длинные
подписи кнопок некрасиво обрезаются клиентом. Кроме того, если обрезать
уже собранный HTML, можно разрезать тег или HTML-сущность — сообщение
не отправится с ошибкой "can't parse entities".

Поэтому:
  * clip() режет СЫРОЙ текст до html.escape();
  * esc() сначала режет, потом экранирует;
  * paginate_lines() разбивает длинный список на несколько сообщений
    по границам строк (каждая строка — самостоятельный HTML-фрагмент).
"""
from __future__ import annotations

import html

MAX_TITLE = 100
MAX_DESCRIPTION = 1500
MAX_BUTTON = 60
MAX_MESSAGE = 4000


def clip(text: str | None, limit: int) -> str:
    """Обрезает строку до limit символов, добавляя многоточие."""
    value = (text or "").strip()
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


def esc(text: str | None, limit: int | None = None) -> str:
    """Экранирует HTML, при необходимости предварительно обрезая текст."""
    value = text or ""
    if limit is not None:
        value = clip(value, limit)
    return html.escape(value)


def clip_button(text: str, limit: int = MAX_BUTTON) -> str:
    """Безопасная подпись inline-кнопки."""
    return clip(text, limit)


def unquote(text: str) -> str | None:
    """Если текст целиком в кавычках — возвращает содержимое без кавычек."""
    value = (text or "").strip()
    pairs = (("«", "»"), ("“", "”"), ('"', '"'), ("'", "'"))
    for left, right in pairs:
        if len(value) >= 2 and value.startswith(left) and value.endswith(right):
            return value[1:-1].strip()
    return None


def unquote_menu_literal(text: str, menu_buttons: set[str]) -> str:
    """
    Позволяет ввести название/описание, совпадающее с кнопкой меню:
    пользователь присылает его в кавычках, а бот убирает кавычки.
    """
    value = (text or "").strip()
    inner = unquote(value)
    if inner is not None and inner in menu_buttons:
        return inner
    return value


def paginate_lines(lines: list[str], limit: int = MAX_MESSAGE) -> list[str]:
    """Собирает строки в сообщения, не превышающие limit символов."""
    chunks: list[str] = []
    current = ""
    for line in lines:
        if current and len(current) + 1 + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current or not chunks:
        chunks.append(current)
    return chunks
