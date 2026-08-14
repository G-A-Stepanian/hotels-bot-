"""
database/history.py — слой доступа к SQLite базе (история запросов).

Схема:
Таблица `search_history` хранит:
- user_id: Telegram user id
- command: какая команда запущена (lowprice/highprice/bestdeal)
- city, checkin, checkout, hotels_limit: параметры запроса
- created_at: ISO-строка UTC времени
- results_json: JSON строка со списком результатов (которые показывали пользователю)

Особенности:
- `init_history()` создаёт таблицу при первом запуске.
- Есть "миграция": добавляем колонку results_json через ALTER TABLE,
  если база была создана старой версией (где колонки ещё не было).
- Методы возвращают типизированные HistoryRow.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class HistoryRow:
    """
    Запись истории запросов.

    Поля соответствуют колонкам таблицы `search_history`.
    """

    id: int
    user_id: int
    command: str
    city: str
    checkin: str
    checkout: str
    hotels_limit: int
    created_at: str
    results_json: str | None = None


def init_history(db_path: str) -> None:
    """
    Инициализировать БД истории.

    Делает:
    - создаёт таблицу `search_history`, если её нет;
    - пытается добавить колонку `results_json` (для старой БД);
    - создаёт индексы по user_id и (user_id, id).

    Args:
        db_path: путь к SQLite файлу.
    """
    with sqlite3.connect(db_path) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                command TEXT NOT NULL,
                city TEXT NOT NULL,
                checkin TEXT NOT NULL,
                checkout TEXT NOT NULL,
                hotels_limit INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """)

        # Миграция для старой БД: добавим колонку results_json, если её не было.
        try:
            con.execute("ALTER TABLE search_history ADD COLUMN results_json TEXT")
        except sqlite3.OperationalError:
            # Колонка уже существует — это ожидаемо.
            pass

        # Индексы — ускоряют /history и выбор записи по id.
        con.execute("CREATE INDEX IF NOT EXISTS idx_sh_user ON search_history(user_id)")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_sh_user_id ON search_history(user_id, id)"
        )


def add_history(
    db_path: str,
    user_id: int,
    command: str,
    city: str,
    checkin: str,
    checkout: str,
    hotels_limit: int,
    results: list[dict[str, Any]] | None = None,
) -> None:
    """
    Добавить запись истории.

    Args:
        db_path: путь к SQLite файлу.
        user_id: Telegram user id.
        command: 'lowprice' / 'highprice' / 'bestdeal'.
        city: город.
        checkin: дата заезда (YYYY-MM-DD).
        checkout: дата выезда (YYYY-MM-DD).
        hotels_limit: лимит результатов, который запросил пользователь.
        results: список словарей с результатами (в нашем проекте — то, что отдаёт to_history_dict()).

    Notes:
        results сериализуются в results_json как UTF-8 JSON (ensure_ascii=False).
    """
    results_json = json.dumps(results or [], ensure_ascii=False)

    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO search_history(
                user_id, command, city, checkin, checkout, hotels_limit, created_at, results_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                str(command),
                str(city),
                str(checkin),
                str(checkout),
                int(hotels_limit),
                datetime.utcnow().isoformat(timespec="seconds"),
                results_json,
            ),
        )


def get_history(db_path: str, user_id: int, limit: int = 10) -> list[HistoryRow]:
    """
    Получить последние записи истории пользователя.

    Args:
        db_path: путь к SQLite файлу.
        user_id: Telegram user id.
        limit: сколько записей вернуть (по умолчанию 10).

    Returns:
        Список HistoryRow, отсортированный от новых к старым.
    """
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute(
            """
            SELECT id, user_id, command, city, checkin, checkout, hotels_limit, created_at, results_json
            FROM search_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(user_id), int(limit)),
        )
        rows = cur.fetchall()
        return [HistoryRow(**dict(r)) for r in rows]


def get_history_by_id(db_path: str, user_id: int, history_id: int) -> HistoryRow | None:
    """
    Получить одну запись истории по её id, но только если она принадлежит user_id.

    Args:
        db_path: путь к SQLite файлу.
        user_id: Telegram user id.
        history_id: id записи.

    Returns:
        HistoryRow или None (если записи нет или она принадлежит другому пользователю).
    """
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute(
            """
            SELECT id, user_id, command, city, checkin, checkout, hotels_limit, created_at, results_json
            FROM search_history
            WHERE user_id = ? AND id = ?
            LIMIT 1
            """,
            (int(user_id), int(history_id)),
        )
        row = cur.fetchone()
        return HistoryRow(**dict(row)) if row else None
