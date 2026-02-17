#!/usr/bin/env python3
"""
main.py - Telegram бот поиска отелей (этап 1).
Запуск: python main.py
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database.models import db, User, SearchHistory  # ← Импорт моделей!
from handlers.start import router as start_router  # ← handlers/start.py


async def main():
    logging.basicConfig(level=logging.INFO)

    db.connect()
    db.create_tables([User, SearchHistory], safe=True)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(start_router)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        db.close()
        print("👋 Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
