import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.getenv(
    "RAPIDAPI_HOST",
    "apidojo-booking-v1.p.rapidapi.com",
)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "bot.db"))


def validate_settings() -> None:
    """Проверяет обязательные переменные окружения до запуска приложения."""
    missing = [
        name
        for name, value in {
            "BOT_TOKEN": BOT_TOKEN,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Не заданы обязательные переменные окружения: "
            f"{', '.join(missing)}. "
            "Скопируйте .env.example в .env и заполните значения."
        )

    valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if LOG_LEVEL not in valid_log_levels:
        raise RuntimeError(
            "LOG_LEVEL должен быть одним из: DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )


def validate_rapidapi_settings() -> None:
    """Проверяет настройки, обязательные для поиска отелей."""
    if not RAPIDAPI_KEY:
        raise RuntimeError(
            "Не задан RAPIDAPI_KEY. Добавьте ключ в файл .env перед запуском поиска."
        )

    if not RAPIDAPI_HOST:
        raise RuntimeError(
            "Не задан RAPIDAPI_HOST. "
            "Укажите X-RapidAPI-Host из личного кабинета RapidAPI."
        )
