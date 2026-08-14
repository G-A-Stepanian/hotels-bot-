"""Точка входа Telegram-бота поиска отелей."""

import asyncio

from aiogram import Bot, Dispatcher
from loguru import logger

import logging_config  # noqa: F401
from api.hotels import close_http_session
from config import BOT_TOKEN, validate_settings
from database.models import SearchHistory, User, db
from handlers.history import router as history_router
from handlers.search import router as search_router
from handlers.start import router as start_router


async def main() -> None:
    """Инициализирует зависимости и запускает long polling."""
    validate_settings()

    bot: Bot | None = None
    database_connected = False

    try:
        logger.info("Запуск HotelSearchBot")

        db.connect(reuse_if_open=True)
        database_connected = True
        db.create_tables([User, SearchHistory], safe=True)
        logger.info("База данных инициализирована")

        bot = Bot(token=BOT_TOKEN)
        dispatcher = Dispatcher()
        dispatcher.include_router(start_router)
        dispatcher.include_router(history_router)
        dispatcher.include_router(search_router)

        logger.info("Запуск polling")
        await dispatcher.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception:
        logger.exception("Критическая ошибка приложения")
        raise
    finally:
        await close_http_session()

        if bot is not None:
            await bot.session.close()

        if database_connected and not db.is_closed():
            db.close()

        logger.info("HotelSearchBot остановлен")


if __name__ == "__main__":
    asyncio.run(main())
