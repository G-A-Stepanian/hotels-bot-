from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("hello-world"))
@router.message(F.text == "Привет")
async def hello_handler(msg: Message):
    await msg.answer("Hello World! Бот готов к этапу 1.")
