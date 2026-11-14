"""Заметки: папки, текст, чек-листы и ссылки на файлы в чате."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from database.db_manager import UserDB

_UNSET = object()


@dataclass
class Note:
    id: int
    folder_id: Optional[int]
    title: Optional[str]
    body: str
    note_date: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    items: list[sqlite3.Row] = field(default_factory=list)
    files: list[sqlite3.Row] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        if self.title and self.title.strip():
            return self.title.strip()
        for line in (self.body or "").splitlines():
            if line.strip():
                return line.strip()[:60]
        return "Без названия"


def create_folder(db: UserDB, name: str) -> Optional[int]:
    name = (name or "").strip()[:100]
    if not name:
        return None
    try:
        cur = db.conn.execute(
            "INSERT INTO note_folders (name, created_at) "
            "VALUES (?, datetime('now','localtime'))",
            (name,),
        )
        db.conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        row = db.conn.execute(
            "SELECT id FROM note_folders WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        return int(row["id"]) if row else None


def list_folders(db: UserDB) -> list[sqlite3.Row]:
    return db.conn.execute(
        """
        SELECT f.*, (
            SELECT COUNT(*) FROM notes n WHERE n.folder_id = f.id
        ) AS note_count
        FROM note_folders f
        ORDER BY f.name COLLATE NOCASE
        """
    ).fetchall()


def get_folder(db: UserDB, folder_id: int) -> Optional[sqlite3.Row]:
    return db.conn.execute(
        "SELECT * FROM note_folders WHERE id = ?", (folder_id,)
    ).fetchone()


def delete_folder(db: UserDB, folder_id: int) -> None:
    db.conn.execute("UPDATE notes SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
    db.conn.execute("DELETE FROM note_folders WHERE id = ?", (folder_id,))
    db.conn.commit()


def create_note(
    db: UserDB,
    folder_id: Optional[int],
    title: Optional[str],
    body: str,
    note_date: Optional[str] = None,
) -> int:
    cur = db.conn.execute(
        """
        INSERT INTO notes
            (folder_id, title, body, note_date, created_at, updated_at)
        VALUES (?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))
        """,
        (folder_id or None, (title or None), body or "", note_date),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def get_note(db: UserDB, note_id: int) -> Optional[Note]:
    row = db.conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        return None
    items = db.conn.execute(
        "SELECT * FROM note_items WHERE note_id = ? ORDER BY position, id",
        (note_id,),
    ).fetchall()
    files = db.conn.execute(
        "SELECT * FROM note_files WHERE note_id = ? ORDER BY id", (note_id,)
    ).fetchall()
    return Note(
        id=row["id"],
        folder_id=row["folder_id"],
        title=row["title"],
        body=row["body"] or "",
        note_date=row["note_date"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        items=list(items),
        files=list(files),
    )


def list_notes(
    db: UserDB,
    folder_id: Optional[int] = None,
    query: Optional[str] = None,
) -> list[Note]:
    where: list[str] = []
    params: list[object] = []
    if folder_id is not None:
        if folder_id == 0:
            where.append("folder_id IS NULL")
        else:
            where.append("folder_id = ?")
            params.append(folder_id)
    if query:
        like = f"%{query.strip()}%"
        where.append(
            "("
            "title LIKE ? OR body LIKE ? "
            "OR id IN (SELECT note_id FROM note_items WHERE text LIKE ?) "
            "OR id IN (SELECT note_id FROM note_files "
            "WHERE caption LIKE ? OR file_name LIKE ?)"
            ")"
        )
        params.extend([like, like, like, like, like])

    sql = "SELECT * FROM notes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, id DESC"

    rows = db.conn.execute(sql, params).fetchall()
    return [
        Note(
            id=row["id"],
            folder_id=row["folder_id"],
            title=row["title"],
            body=row["body"] or "",
            note_date=row["note_date"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def update_note(
    db: UserDB,
    note_id: int,
    title: object = _UNSET,
    body: object = _UNSET,
    folder_id: object = _UNSET,
    note_date: object = _UNSET,
) -> None:
    sets: list[str] = []
    params: list[object] = []
    if title is not _UNSET:
        sets.append("title = ?")
        params.append((title or None) if title else None)
    if body is not _UNSET:
        sets.append("body = ?")
        params.append(body or "")
    if folder_id is not _UNSET:
        sets.append("folder_id = ?")
        params.append(folder_id or None)
    if note_date is not _UNSET:
        sets.append("note_date = ?")
        params.append(note_date or None)
    sets.append("updated_at = datetime('now','localtime')")
    params.append(note_id)
    db.conn.execute(f"UPDATE notes SET {', '.join(sets)} WHERE id = ?", params)
    db.conn.commit()


def delete_note(db: UserDB, note_id: int) -> None:
    db.conn.execute("DELETE FROM note_items WHERE note_id = ?", (note_id,))
    db.conn.execute("DELETE FROM note_files WHERE note_id = ?", (note_id,))
    db.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    db.conn.commit()


def add_item(db: UserDB, note_id: int, text: str) -> Optional[int]:
    text = (text or "").strip()[:500]
    if not text:
        return None
    row = db.conn.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 AS pos FROM note_items WHERE note_id = ?",
        (note_id,),
    ).fetchone()
    cur = db.conn.execute(
        "INSERT INTO note_items (note_id, text, done, position) VALUES (?, ?, 0, ?)",
        (note_id, text, row["pos"]),
    )
    db.conn.execute(
        "UPDATE notes SET updated_at = datetime('now','localtime') WHERE id = ?",
        (note_id,),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def toggle_item(db: UserDB, item_id: int, note_id: int) -> Optional[bool]:
    row = db.conn.execute(
        "SELECT done FROM note_items WHERE id = ? AND note_id = ?",
        (item_id, note_id),
    ).fetchone()
    if row is None:
        return None
    new_done = 0 if row["done"] else 1
    db.conn.execute(
        "UPDATE note_items SET done = ? WHERE id = ?", (new_done, item_id)
    )
    db.conn.execute(
        "UPDATE notes SET updated_at = datetime('now','localtime') WHERE id = ?",
        (note_id,),
    )
    db.conn.commit()
    return bool(new_done)


def delete_item(db: UserDB, item_id: int, note_id: int) -> None:
    db.conn.execute(
        "DELETE FROM note_items WHERE id = ? AND note_id = ?", (item_id, note_id)
    )
    db.conn.execute(
        "UPDATE notes SET updated_at = datetime('now','localtime') WHERE id = ?",
        (note_id,),
    )
    db.conn.commit()


def add_file(
    db: UserDB,
    note_id: int,
    file_id: str,
    file_unique_id: Optional[str],
    file_type: str,
    file_name: Optional[str],
    caption: Optional[str],
    message_id: Optional[int],
    chat_id: Optional[int],
) -> int:
    cur = db.conn.execute(
        """
        INSERT INTO note_files
            (note_id, file_id, file_unique_id, file_type, file_name,
             caption, message_id, chat_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        """,
        (
            note_id,
            file_id,
            file_unique_id,
            file_type,
            file_name,
            caption,
            message_id,
            chat_id,
        ),
    )
    db.conn.execute(
        "UPDATE notes SET updated_at = datetime('now','localtime') WHERE id = ?",
        (note_id,),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def search_notes(db: UserDB, query: str) -> list[Note]:
    return list_notes(db, query=query)
