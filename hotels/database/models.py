from peewee import (
    Model,
    SqliteDatabase,
    CharField,
    TextField,
    FloatField,
    DateTimeField,
    ForeignKeyField,
)
import datetime

db = SqliteDatabase("bot.db")


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    user_id = CharField(unique=True)
    username = CharField(null=True)


class SearchHistory(BaseModel):
    user = ForeignKeyField(User, backref="searches")
    command = CharField()
    city = CharField()
    dates = CharField()
    price_min = FloatField(null=True)
    price_max = FloatField(null=True)
    hotels_count = CharField()
    timestamp = DateTimeField(default=datetime.datetime.now)
