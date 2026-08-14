"""
/help — справка по доступным командам.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name=__name__)

HELP_TEXT = (
    "Доступные команды:\n"
    "/start — старт\n"
    "/help — помощь\n"
    "/lowprice — дешёвые отели\n"
    "/highprice — дорогие отели\n"
    "/bestdeal — подбор по цене\n"
    "/history — история запросов\n"
    "/cancel — прерывание текущего сценария"
)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    """Показать текст помощи."""
    await message.answer(HELP_TEXT)
