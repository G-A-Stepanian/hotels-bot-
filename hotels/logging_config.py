"""
Loguru конфиг: console + JSON (без импортов stdlib logging на топ-уровне).
"""

from loguru import logger
import sys
from pathlib import Path
from config import LOG_LEVEL

# Console (цветной)
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    level=LOG_LEVEL,
    colorize=True,
)

# JSON ротация
log_dir = Path("logs")
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
