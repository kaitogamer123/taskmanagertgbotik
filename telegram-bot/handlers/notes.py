"""Заметки: папки, текст, интерактивный чек-лист, файлы через file_id, поиск."""
from __future__ import annotations

from datetime import date as date_cls

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db_manager import UserDB
from database.notes_repo import (
    Note,
    add_file,
    add_item,
    create_folder,
    create_note,
    delete_note,
    get_folder,
    get_note,
    list_folders,
    list_notes,
    search_notes,
    toggle_item,
    update_note,
)
from database.plans_repo import search_plans, search_rules
from keyboards.inline import (
    note_card_keyboard,
    note_date_keyboard,
    note_delete_confirm_keyboard,
    note_move_keyboard,
    notes_folders_keyboard,
    notes_list_keyboard,
)
from keyboards.reply import BTN_NOTES, MAIN_MENU_BUTTONS
from states import NotesStates
from utils.date_utils import format_date_full_ru, parse_natural_date
from utils.text import MAX_TITLE, clip, esc

router = Router(name="notes")

PAGE_SIZE = 5
MAX_NOTE_BODY = 4000
NOTES_INTRO = (
    "📝 <b>Заметки</b>\n\n"
    "Выбери папку или создай новую заметку.\n"
    "Заметки хранятся отдельно от планов и не попадают в сводки."
)


async def _safe_edit(message: Message | None, text: str, reply_markup=None) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            await message.answer(text, reply_markup=reply_markup)


def _folder_label(db: UserDB, folder_id: int) -> str:
    if folder_id == -1:
        return "Все заметки"
    if folder_id == 0:
        return "Без папки"
    folder = get_folder(db, folder_id)
    return folder["name"] if folder is not None else "Папка"


def _note_folder_id(note: Note) -> int:
    return note.folder_id if note.folder_id is not None else 0


def _note_date_label(note: Note) -> str:
    if not note.note_date:
        return ""
    try:
        d = date_cls.fromisoformat(note.note_date)
        return format_date_full_ru(d)
    except ValueError:
        return note.note_date


def _note_text(db: UserDB, note: Note) -> str:
    folder = _folder_label(db, _note_folder_id(note))
    lines = [
        f"📝 <b>{esc(note.display_title, MAX_TITLE)}</b>",
        f"📁 {esc(folder)}",
        f"🕓 Создано: {esc(note.created_at or '—')}",
        f"✏️ Изменено: {esc(note.updated_at or '—')}",
    ]
    if note.note_date:
        lines.append(f"📅 Дата заметки: {esc(_note_date_label(note))}")

    lines.append("")
    lines.append(esc(note.body, 1000) if note.body else "<i>Текст пуст</i>")

    if note.items:
        lines.append("")
        lines.append("☑️ <b>Чек-лист:</b>")
        for item in note.items[:10]:
            mark = "✅" if item["done"] else "⬜"
            lines.append(f"{mark} {esc(item['text'], 80)}")
        if len(note.items) > 10:
            lines.append(f"… ещё {len(note.items) - 10}")

    if note.files:
        lines.append("")
        lines.append("📎 <b>Файлы:</b>")
        for file_row in note.files[:8]:
            name = file_row["file_name"] or file_row["file_type"]
            lines.append(f"• {esc(name, 60)}")
        if len(note.files) > 8:
            lines.append(f"… ещё {len(note.files) - 8}")

    return "\n".join(lines)


def _notes_list_view(
    db: UserDB, folder_id: int, page: int
) -> tuple[str, object]:
    notes = list_notes(db, None if folder_id == -1 else folder_id)
    max_pages = max(1, (len(notes) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, max_pages - 1))
    label = _folder_label(db, folder_id)
    if not notes:
        text = (
            f"📝 <b>{esc(label)}</b>\n\n"
            "Пока нет заметок. Создай первую кнопкой ниже."
        )
    else:
        text = (
            f"📝 <b>{esc(label)}</b>\n"
            f"Всего заметок: {len(notes)}\n\n"
            "Нажми на заметку ниже, чтобы открыть её."
        )
    return text, notes_list_keyboard(notes, folder_id, page, PAGE_SIZE)


def _extract_file(message: Message) -> tuple[str, str, str | None, str | None, str | None] | None:
    caption = message.caption
    if message.photo:
        f = message.photo[-1]
        return "photo", f.file_id, f.file_unique_id, None, caption
    if message.document:
        f = message.document
        return "document", f.file_id, f.file_unique_id, f.file_name, caption
    if message.video:
        f = message.video
        return "video", f.file_id, f.file_unique_id, f.file_name, caption
    if message.audio:
        f = message.audio
        return "audio", f.file_id, f.file_unique_id, f.file_name or f.title, caption
    if message.voice:
        f = message.voice
        return "voice", f.file_id, f.file_unique_id, None, caption
    if message.animation:
        f = message.animation
        return "animation", f.file_id, f.file_unique_id, f.file_name, caption
    if message.video_note:
        f = message.video_note
        return "video_note", f.file_id, f.file_unique_id, None, caption
    return None


async def _send_note_file(message: Message | None, file_row) -> None:
    if message is None:
        return
    file_type = file_row["file_type"]
    file_id = file_row["file_id"]
    caption = esc(file_row["caption"], 200) if file_row["caption"] else None
    name = file_row["file_name"] or file_type
    try:
        if file_type == "photo":
            await message.answer_photo(file_id, caption=caption)
        elif file_type == "document":
            await message.answer_document(file_id, caption=caption)
        elif file_type == "video":
            await message.answer_video(file_id, caption=caption)
        elif file_type == "audio":
            await message.answer_audio(file_id, caption=caption)
        elif file_type == "voice":
            await message.answer_voice(file_id, caption=caption)
        elif file_type == "animation":
            await message.answer_animation(file_id, caption=caption)
        elif file_type == "video_note":
            await message.answer_video_note(file_id)
        else:
            await message.answer_document(file_id, caption=caption)
    except Exception:  # noqa: BLE001 - файл могли удалить
        await message.answer(
            f"⚠️ Файл «{esc(name, 60)}» недоступен: возможно, сообщение удалено."
        )


def _note_markdown(db: UserDB, note: Note) -> str:
    lines = [
        f"# {note.display_title}",
        "",
        f"Папка: {_folder_label(db, _note_folder_id(note))}",
        f"Создано: {note.created_at or '—'}",
        f"Изменено: {note.updated_at or '—'}",
    ]
    if note.note_date:
        lines.append(f"Дата заметки: {_note_date_label(note)}")
    if note.body:
        lines += ["", "## Текст", "", note.body]
    if note.items:
        lines += ["", "## Чек-лист", ""]
        for item in note.items:
            mark = "x" if item["done"] else " "
            lines.append(f"- [{mark}] {item['text']}")
    if note.files:
        lines += ["", "## Файлы", ""]
        for file_row in note.files:
            lines.append(
                f"- {file_row['file_name'] or file_row['file_type']} "
                f"({file_row['file_type']}, file_id сохранён в чате)"
            )
    return "\n".join(lines)


def _search_view(db: UserDB, query: str, scope: str) -> tuple[str, object]:
    notes = search_notes(db, query)[:8]
    plans = search_plans(db, query, 8) if scope == "all" else []
    rules = search_rules(db, query, 8) if scope == "all" else []

    lines = [f"🔎 <b>Поиск:</b> {esc(query, 80)}"]
    if notes:
        lines += ["", "📝 <b>Заметки:</b>"]
        for note in notes:
            lines.append(
                f"• {esc(note.display_title, 60)} — "
                f"{esc(_folder_label(db, _note_folder_id(note)), 30)}"
            )
    if plans:
        lines += ["", "📅 <b>Задачи:</b>"]
        for plan in plans:
            time_part = f" {plan['time_start']}" if plan["time_start"] else ""
            lines.append(
                f"• {plan['plan_date']}{time_part} — {esc(plan['title'], 60)}"
            )
    if rules:
        lines += ["", "🔁 <b>Повторяющиеся:</b>"]
        for rule in rules:
            from utils.repeat_parser import describe_rule

            lines.append(
                f"• {esc(rule['title'], 60)} — "
                f"{esc(describe_rule(rule['rule_type'], rule['rule_value']), 50)}"
            )

    if len(lines) == 1:
        lines.append("\nНичего не найдено.")

    builder = InlineKeyboardBuilder()
    for note in notes:
        builder.row(
            InlineKeyboardButton(
                text=clip(f"📝 {note.display_title}", 60),
                callback_data=f"note:{note.id}",
            )
        )
    for plan in plans:
        builder.row(
            InlineKeyboardButton(
                text=clip(f"📅 {plan['plan_date']} {plan['title']}", 60),
                callback_data=f"day:{plan['plan_date']}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ В заметки" if scope == "notes" else "⬅️ В меню",
            callback_data="notes_menu" if scope == "notes" else "week_menu",
        )
    )
    return "\n".join(lines), builder.as_markup()


# ─── Меню заметок ────────────────────────────────────────────────────────────


@router.message(Command("notes", ignore_case=True))
@router.message(F.text == BTN_NOTES)
async def cmd_notes(message: Message, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    await message.answer(
        NOTES_INTRO, reply_markup=notes_folders_keyboard(list_folders(db))
    )


@router.callback_query(F.data == "notes_menu")
async def cb_notes_menu(callback: CallbackQuery, state: FSMContext, db: UserDB) -> None:
    await state.clear()
    await callback.answer()
    await _safe_edit(
        callback.message,
        NOTES_INTRO,
        notes_folders_keyboard(list_folders(db)),
    )


@router.callback_query(F.data.startswith("notes_page:"))
async def cb_notes_page(callback: CallbackQuery, db: UserDB) -> None:
    _, folder_str, page_str = (callback.data or "").split(":", 2)
    folder_id = int(folder_str) if folder_str.lstrip("-").isdigit() else -1
    page = int(page_str) if page_str.isdigit() else 0
    text, kb = _notes_list_view(db, folder_id, page)
    await callback.answer()
    await _safe_edit(callback.message, text, kb)


@router.callback_query(F.data == "note_folder_new")
async def cb_note_folder_new(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(NotesStates.waiting_folder_name)
    if callback.message:
        await callback.message.answer("📁 Название новой папки?")


@router.message(
    StateFilter(NotesStates.waiting_folder_name),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_folder_name(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название папки не может быть пустым.")
        return
    create_folder(db, name)
    await state.clear()
    await message.answer(
        f"✅ Папка <b>{esc(name, 100)}</b> готова.",
        reply_markup=notes_folders_keyboard(list_folders(db)),
    )


@router.callback_query(F.data.startswith("note_new"))
async def cb_note_new(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    folder_id = -1
    if len(parts) > 1 and parts[1].lstrip("-").isdigit():
        folder_id = int(parts[1])
    await callback.answer()
    await state.set_state(NotesStates.waiting_new_text)
    await state.update_data(folder_id=folder_id)
    if callback.message:
        await callback.message.answer(
            "📝 Отправь текст заметки. Можно фото или файл с подписью.\n"
            "Потом добавим чек-лист и папку. /cancel — отмена."
        )


@router.message(
    StateFilter(NotesStates.waiting_new_text),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_new_note(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    data = await state.get_data()
    folder_id = int(data.get("folder_id", -1))
    body = (message.text or message.caption or "").strip()
    extracted = _extract_file(message)
    if not body and extracted is None:
        await message.answer("Отправь текст, фото или файл (или /cancel).")
        return

    note_id = create_note(
        db,
        None if folder_id <= 0 else folder_id,
        None,
        body,
    )
    if extracted is not None:
        file_type, file_id, unique_id, file_name, caption = extracted
        add_file(
            db,
            note_id,
            file_id,
            unique_id,
            file_type,
            file_name,
            caption,
            message.message_id,
            message.chat.id,
        )
    await state.clear()
    note = get_note(db, note_id)
    if note is None:
        await message.answer("Не удалось создать заметку.")
        return
    await message.answer(
        _note_text(db, note), reply_markup=note_card_keyboard(note, _note_folder_id(note))
    )


@router.callback_query(F.data.startswith("note:"))
async def cb_note(callback: CallbackQuery, db: UserDB) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    note = get_note(db, note_id)
    if note is None:
        await callback.answer("Заметка уже удалена", show_alert=True)
        return
    await callback.answer()
    await _safe_edit(
        callback.message,
        _note_text(db, note),
        note_card_keyboard(note, _note_folder_id(note)),
    )


# ─── Чек-лист ────────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("note_item:"))
async def cb_note_item(callback: CallbackQuery, db: UserDB) -> None:
    _, item_str, note_str = (callback.data or "").split(":", 2)
    item_id = int(item_str)
    note_id = int(note_str)
    done = toggle_item(db, item_id, note_id)
    if done is None:
        await callback.answer("Пункт уже удалён", show_alert=True)
        return
    await callback.answer("Готово ✅" if done else "Снято ⬜")
    note = get_note(db, note_id)
    if note is not None:
        await _safe_edit(
            callback.message,
            _note_text(db, note),
            note_card_keyboard(note, _note_folder_id(note)),
        )


@router.callback_query(F.data.startswith("note_item_add:"))
async def cb_note_item_add(
    callback: CallbackQuery, state: FSMContext
) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    await callback.answer()
    await state.set_state(NotesStates.waiting_note_item)
    await state.update_data(note_id=note_id)
    if callback.message:
        await callback.message.answer("☑️ Текст пункта чек-листа?")


@router.message(
    StateFilter(NotesStates.waiting_note_item),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_note_item(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пункт не может быть пустым.")
        return
    data = await state.get_data()
    note_id = int(data["note_id"])
    add_item(db, note_id, text)
    await state.clear()
    note = get_note(db, note_id)
    if note is None:
        await message.answer("Заметка уже удалена.")
        return
    await message.answer(
        _note_text(db, note), reply_markup=note_card_keyboard(note, _note_folder_id(note))
    )


# ─── Файлы ───────────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("note_file_add:"))
async def cb_note_file_add(
    callback: CallbackQuery, state: FSMContext
) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    await callback.answer()
    await state.set_state(NotesStates.waiting_note_file)
    await state.update_data(note_id=note_id)
    if callback.message:
        await callback.message.answer(
            "📎 Отправь фото или файл. Он останется в чате, бот сохранит ссылку."
        )


@router.message(
    StateFilter(NotesStates.waiting_note_file),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_note_file(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    extracted = _extract_file(message)
    if extracted is None:
        await message.answer("Нужно фото или файл (или /cancel).")
        return
    data = await state.get_data()
    note_id = int(data["note_id"])
    file_type, file_id, unique_id, file_name, caption = extracted
    add_file(
        db,
        note_id,
        file_id,
        unique_id,
        file_type,
        file_name,
        caption,
        message.message_id,
        message.chat.id,
    )
    await state.clear()
    note = get_note(db, note_id)
    if note is None:
        await message.answer("Заметка уже удалена.")
        return
    await message.answer(
        _note_text(db, note), reply_markup=note_card_keyboard(note, _note_folder_id(note))
    )


@router.callback_query(F.data.startswith("note_files:"))
async def cb_note_files(callback: CallbackQuery, db: UserDB) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    note = get_note(db, note_id)
    if note is None:
        await callback.answer("Заметка уже удалена", show_alert=True)
        return
    await callback.answer()
    if not note.files:
        if callback.message:
            await callback.message.answer("📎 В заметке нет файлов.")
        return
    for file_row in note.files:
        await _send_note_file(callback.message, file_row)


# ─── Редактирование заметки ──────────────────────────────────────────────────


@router.callback_query(F.data.startswith("note_text:"))
async def cb_note_text(callback: CallbackQuery, state: FSMContext) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    await callback.answer()
    await state.set_state(NotesStates.waiting_note_text)
    await state.update_data(note_id=note_id)
    if callback.message:
        await callback.message.answer("✏️ Пришли новый текст заметки.")


@router.message(
    StateFilter(NotesStates.waiting_note_text),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_note_text(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    text = (message.text or "").strip()
    if len(text) > MAX_NOTE_BODY:
        await message.answer(f"Слишком длинный текст, максимум {MAX_NOTE_BODY} символов.")
        return
    data = await state.get_data()
    note_id = int(data["note_id"])
    update_note(db, note_id, body=text)
    await state.clear()
    note = get_note(db, note_id)
    if note is None:
        await message.answer("Заметка уже удалена.")
        return
    await message.answer(
        _note_text(db, note), reply_markup=note_card_keyboard(note, _note_folder_id(note))
    )


@router.callback_query(F.data.startswith("note_title:"))
async def cb_note_title(callback: CallbackQuery, state: FSMContext) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    await callback.answer()
    await state.set_state(NotesStates.waiting_note_title)
    await state.update_data(note_id=note_id)
    if callback.message:
        await callback.message.answer("📝 Пришли новый заголовок (или «-», чтобы убрать).")


@router.message(
    StateFilter(NotesStates.waiting_note_title),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_note_title(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    title = (message.text or "").strip()
    if title in {"-", "нет", "без заголовка"}:
        title = ""
    if len(title) > MAX_TITLE:
        await message.answer(f"Слишком длинный заголовок, максимум {MAX_TITLE} символов.")
        return
    data = await state.get_data()
    note_id = int(data["note_id"])
    update_note(db, note_id, title=title or None)
    await state.clear()
    note = get_note(db, note_id)
    if note is None:
        await message.answer("Заметка уже удалена.")
        return
    await message.answer(
        _note_text(db, note), reply_markup=note_card_keyboard(note, _note_folder_id(note))
    )


@router.callback_query(F.data.startswith("note_move:"))
async def cb_note_move(callback: CallbackQuery, db: UserDB) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    note = get_note(db, note_id)
    if note is None:
        await callback.answer("Заметка уже удалена", show_alert=True)
        return
    await callback.answer()
    await _safe_edit(
        callback.message,
        "📁 В какую папку переместить заметку?",
        note_move_keyboard(note_id, list_folders(db)),
    )


@router.callback_query(F.data.startswith("note_move_to:"))
async def cb_note_move_to(callback: CallbackQuery, db: UserDB) -> None:
    _, note_str, folder_str = (callback.data or "").split(":", 2)
    note_id = int(note_str)
    folder_id = int(folder_str) if folder_str.lstrip("-").isdigit() else 0
    update_note(db, note_id, folder_id=None if folder_id <= 0 else folder_id)
    await callback.answer("📁 Перемещено")
    note = get_note(db, note_id)
    if note is not None:
        await _safe_edit(
            callback.message,
            _note_text(db, note),
            note_card_keyboard(note, _note_folder_id(note)),
        )


@router.callback_query(F.data.startswith("note_date:"))
async def cb_note_date(callback: CallbackQuery, state: FSMContext) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    await callback.answer()
    await state.set_state(NotesStates.waiting_note_date)
    await state.update_data(note_id=note_id)
    if callback.message:
        await callback.message.answer(
            "📅 Напиши дату заметки (например <code>19.10</code> или «завтра»).",
            reply_markup=note_date_keyboard(note_id),
        )


@router.callback_query(F.data.startswith("note_date_clear:"))
async def cb_note_date_clear(callback: CallbackQuery, db: UserDB) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    update_note(db, note_id, note_date=None)
    await callback.answer("Дата убрана")
    note = get_note(db, note_id)
    if note is not None:
        await _safe_edit(
            callback.message,
            _note_text(db, note),
            note_card_keyboard(note, _note_folder_id(note)),
        )


@router.message(
    StateFilter(NotesStates.waiting_note_date),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_note_date(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    parsed = parse_natural_date((message.text or "").strip())
    if parsed is None:
        await message.answer("Не понял дату. Напиши, например, <code>19.10</code>.")
        return
    data = await state.get_data()
    note_id = int(data["note_id"])
    update_note(db, note_id, note_date=parsed.isoformat())
    await state.clear()
    note = get_note(db, note_id)
    if note is None:
        await message.answer("Заметка уже удалена.")
        return
    await message.answer(
        _note_text(db, note), reply_markup=note_card_keyboard(note, _note_folder_id(note))
    )


@router.callback_query(F.data.startswith("note_delete:"))
async def cb_note_delete(callback: CallbackQuery, db: UserDB) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    note = get_note(db, note_id)
    if note is None:
        await callback.answer("Заметка уже удалена", show_alert=True)
        return
    await callback.answer()
    await _safe_edit(
        callback.message,
        f"🗑 Удалить заметку «<b>{esc(note.display_title, MAX_TITLE)}</b>»?",
        note_delete_confirm_keyboard(note_id),
    )


@router.callback_query(F.data.startswith("note_delete_yes:"))
async def cb_note_delete_yes(callback: CallbackQuery, db: UserDB) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    note = get_note(db, note_id)
    folder_id = _note_folder_id(note) if note is not None else 0
    delete_note(db, note_id)
    await callback.answer("🗑 Заметка удалена")
    text, kb = _notes_list_view(db, folder_id, 0)
    await _safe_edit(callback.message, f"✅ Заметка удалена.\n\n{text}", kb)


@router.callback_query(F.data.startswith("note_export:"))
async def cb_note_export(callback: CallbackQuery, db: UserDB) -> None:
    note_id = int((callback.data or "").split(":", 1)[1])
    note = get_note(db, note_id)
    if note is None:
        await callback.answer("Заметка уже удалена", show_alert=True)
        return
    content = _note_markdown(db, note)
    await callback.answer("📤 Готово")
    if callback.message is None:
        return
    await callback.message.answer_document(
        BufferedInputFile(
            content.encode("utf-8"), filename=f"note_{note.id}.md"
        ),
        caption=f"📤 Заметка «{esc(note.display_title, 60)}»",
    )


# ─── Поиск ───────────────────────────────────────────────────────────────────


@router.message(Command("find", ignore_case=True))
async def cmd_find(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if not query:
        await state.set_state(NotesStates.waiting_search)
        await state.update_data(scope="all")
        await message.answer("🔎 Что искать? Напиши текст.")
        return
    await state.clear()
    text, kb = _search_view(db, query, "all")
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "note_search")
async def cb_note_search(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(NotesStates.waiting_search)
    await state.update_data(scope="notes")
    if callback.message:
        await callback.message.answer("🔎 Что искать в заметках?")


@router.message(
    StateFilter(NotesStates.waiting_search),
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
)
async def process_search(
    message: Message, state: FSMContext, db: UserDB
) -> None:
    query = (message.text or "").strip()
    if not query:
        await message.answer("Напиши, что искать.")
        return
    data = await state.get_data()
    scope = data.get("scope", "all")
    await state.clear()
    text, kb = _search_view(db, query, scope)
    await message.answer(text, reply_markup=kb)
