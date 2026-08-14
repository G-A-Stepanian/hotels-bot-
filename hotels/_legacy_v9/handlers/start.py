"""
/start — приветственное сообщение.

Держим это отдельным файлом, чтобы не раздувать search-сценарий.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name=__name__)

START_TEXT = (
    "Привет! Я бот поиска отелей.\n"
    "Команды:\n"
    "/help\n"
    "/lowprice\n"
    "/highprice\n"
    "/bestdeal\n"
    "/history\n"
    "/cancel"
)


@router.message(Command("start"))
async def start_cmd(message: Message) -> None:
    """Отправить пользователю стартовую подсказку по командам."""
    await message.answer(START_TEXT)
