#!/usr/bin/env python3
"""
main.py - HotelSearchBot с Loguru (этап 1, Python 3.13/macOS).
"""

import asyncio  # ← ПЕРВЫЙ импорт!
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database.models import db, User, SearchHistory
from handlers.start import router as start_router
import logging_config  # ← Loguru config (безопасно после asyncio)


async def main():
    from loguru import logger  # ← Loguru ВНУТРИ async main()!

    logger.info("🚀 Запуск HotelSearchBot")

    db.connect()
    db.create_tables([User, SearchHistory], safe=True)
    logger.info("✅ База данных: bot.db")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(start_router)

    try:
        logger.info("📡 Polling...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception("💥 Критическая ошибка!")  # С стек-трейсом
    finally:
        await bot.session.close()
        db.close()
        logger.info("👋 Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
