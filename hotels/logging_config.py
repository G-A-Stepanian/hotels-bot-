"""
Loguru конфиг: console + JSON (без импортов stdlib logging на топ-уровне).
"""

import sys

from loguru import logger

from config import BASE_DIR, LOG_LEVEL

logger.remove()


# Console (цветной)
logger.add(
    sys.stdout,
    format=(
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
        "{name}:{function}:{line} | {message}"
    ),
    level=LOG_LEVEL,
    colorize=True,
)

# JSON ротация
log_dir = BASE_DIR / "logs"
log_dir.mkdir(exist_ok=True)
logger.add(
    log_dir / "hotels-bot-{time:YYYY-MM-DD}.json",
    format="{time} | {level} | {message}",
    level="INFO",
    rotation="10 MB",
    retention="30 days",
    serialize=True,
    enqueue=True,
)

# Peewee логи (инициализируется позже в main.py)
