import sqlite3
from pathlib import Path

from database.models import SearchHistory, User, db


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    query = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return connection.execute(query, (table_name,)).fetchone() is not None


def migrate_history() -> None:
    database_path = Path(db.database)

    if not database_path.exists():
        print("Файл базы данных не найден. Будет создана новая база.")
        db.connect(reuse_if_open=True)
        db.create_tables([User, SearchHistory], safe=True)
        db.close()
        return

    source = sqlite3.connect(database_path)
    source.row_factory = sqlite3.Row

    try:
        if not table_exists(source, "search_history"):
            print("Старая таблица search_history отсутствует.")
            db.connect(reuse_if_open=True)
            db.create_tables([User, SearchHistory], safe=True)
            db.close()
            return

        legacy_rows = source.execute("""
            SELECT
                user_id,
                command,
                city,
                checkin,
                checkout,
                hotels_limit,
                created_at,
                COALESCE(results_json, '[]') AS results_json
            FROM search_history
            ORDER BY id
            """).fetchall()

        db.connect(reuse_if_open=True)
        db.create_tables([User, SearchHistory], safe=True)

        migrated_count = 0

        with db.atomic():
            for row in legacy_rows:
                user, _ = User.get_or_create(
                    telegram_id=str(row["user_id"]),
                    defaults={"username": None},
                )

                already_migrated = (
                    SearchHistory.select()
                    .where(
                        (SearchHistory.user == user)
                        & (SearchHistory.command == row["command"])
                        & (SearchHistory.city == row["city"])
                        & (SearchHistory.checkin == row["checkin"])
                        & (SearchHistory.checkout == row["checkout"])
                        & (SearchHistory.created_at == row["created_at"])
                    )
                    .exists()
                )

                if already_migrated:
                    continue

                SearchHistory.create(
                    user=user,
                    command=row["command"],
                    city=row["city"],
                    checkin=row["checkin"],
                    checkout=row["checkout"],
                    hotels_limit=int(row["hotels_limit"]),
                    results_json=row["results_json"],
                    created_at=row["created_at"],
                )
                migrated_count += 1

        print(f"Перенесено записей: {migrated_count}")

    finally:
        source.close()

        if not db.is_closed():
            db.close()


if __name__ == "__main__":
    migrate_history()
