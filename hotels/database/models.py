import json
from datetime import UTC, datetime
from typing import Any

from peewee import (
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

from config import DATABASE_PATH

db = SqliteDatabase(
    DATABASE_PATH,
    pragmas={
        "foreign_keys": 1,
        "journal_mode": "wal",
    },
)


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    telegram_id = CharField(unique=True, index=True)
    username = CharField(null=True)

    class Meta:
        table_name = "users"


class SearchHistory(BaseModel):
    user = ForeignKeyField(User, backref="searches", on_delete="CASCADE")
    command = CharField()
    city = CharField()
    checkin = CharField()
    checkout = CharField()
    hotels_limit = IntegerField()
    results_json = TextField(default="[]")
    created_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "search_history"
        indexes = ((("user", "id"), False),)

    @property
    def results(self) -> list[dict[str, Any]]:
        """Возвращает сохранённые результаты поиска как список словарей."""
        return json.loads(self.results_json)

    def set_results(self, results: list[dict[str, Any]]) -> None:
        """Сериализует результаты API для сохранения в SQLite."""
        self.results_json = json.dumps(results, ensure_ascii=False)
