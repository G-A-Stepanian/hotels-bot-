from datetime import datetime
from typing import TypeAlias

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger

from repositories.history import HistoryRepository

HistoryDate: TypeAlias = datetime | str

router = Router()

COMMAND_LABELS = {
    "lowprice": "💸 Дешёвые",
    "highprice": "💎 Дорогие",
    "bestdeal": "⚖️ Оптимальные",
}


def format_history_item(
    command: str,
    city: str,
    checkin: str,
    checkout: str,
    hotels_limit: int,
    created_at: HistoryDate,
    results_count: int,
) -> str:
    """Форматирует одну запись истории для Telegram."""
    label = COMMAND_LABELS.get(command, f"/{command}")
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            created = created_at
        else:
            created = created_at.strftime("%d.%m.%Y %H:%M")
    else:
        created = created_at.strftime("%d.%m.%Y %H:%M")

    return (
        f"{label}\n"
        f"🏙 Город: {city}\n"
        f"📅 Даты: {checkin} — {checkout}\n"
        f"🏨 Лимит: {hotels_limit}\n"
        f"📋 Найдено: {results_count}\n"
        f"🕒 Поиск: {created}"
    )


@router.message(Command("history"))
async def history_handler(message: Message) -> None:
    """Показывает последние десять поисков текущего пользователя."""
    if message.from_user is None:
        return

    try:
        searches = HistoryRepository.get_recent_searches(
            telegram_id=message.from_user.id,
            limit=10,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Не удалось получить историю для пользователя {}",
            message.from_user.id,
        )
        await message.answer("Не удалось загрузить историю. Попробуйте ещё раз позже.")
        return

    if not searches:
        await message.answer(
            "История поиска пока пуста.\n"
            "Используйте /lowprice, /highprice или /bestdeal."
        )
        return

    items = [
        format_history_item(
            command=search.command,
            city=search.city,
            checkin=search.checkin,
            checkout=search.checkout,
            hotels_limit=search.hotels_limit,
            created_at=search.created_at,
            results_count=len(search.results),
        )
        for search in searches
    ]

    await message.answer(
        "🗂 <b>Последние 10 поисков</b>\n\n" + "\n\n".join(items),
        parse_mode="HTML",
    )
