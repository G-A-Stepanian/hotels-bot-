from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from loguru import logger

from api.hotels import (
    HotelsApiError,
    hotel_booking_url,
    hotel_rates_info,
    search_highprice,
    search_lowprice,
)
from config import validate_rapidapi_settings
from repositories.history import HistoryRepository

router = Router()


class SearchStates(StatesGroup):
    city = State()
    checkin = State()
    checkout = State()
    price_min = State()
    price_max = State()
    limit = State()


MONTENEGRO_TZ = ZoneInfo("Europe/Podgorica")

COMMAND_TITLES = {
    "lowprice": "💸 Самые дешёвые отели",
    "highprice": "💎 Самые дорогие отели",
    "bestdeal": "⚖️ Отели в диапазоне цены",
}


def parse_date(value: str) -> date | None:
    """Разбирает дату формата YYYY-MM-DD."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def extract_hotel_name(hotel: dict[str, Any]) -> str:
    """Извлекает название из нескольких вариантов API-ответа."""
    return str(
        hotel.get("name")
        or hotel.get("hotelName")
        or hotel.get("title")
        or "Без названия"
    )


def extract_address(hotel: dict[str, Any]) -> str:
    """Извлекает адрес из распространённых вариантов ответа API."""
    address = hotel.get("address") or hotel.get("addressLine")

    if isinstance(address, str) and address.strip():
        return address.strip()

    if isinstance(address, dict):
        parts = [
            address.get("addressLine1"),
            address.get("addressLine2"),
            address.get("city"),
            address.get("province"),
            address.get("country"),
        ]
        return ", ".join(str(item) for item in parts if item) or "не указан"

    location = hotel.get("location")
    if isinstance(location, dict):
        parts = [
            location.get("address"),
            location.get("addressLine1"),
            location.get("city"),
            location.get("country"),
        ]
        return ", ".join(str(item) for item in parts if item) or "не указан"

    return "не указан"


def format_hotel(
    index: int,
    hotel: dict[str, Any],
) -> str:
    """Формирует компактную карточку отеля."""
    name = extract_hotel_name(hotel)
    rates = hotel_rates_info(hotel)

    price = rates.get("min_price")
    currency = rates.get("currency") or ""
    price_text = f"{price} {currency}".strip() if price is not None else "не указана"

    address = extract_address(hotel)
    booking_url = hotel_booking_url(hotel) or "ссылка недоступна"

    safe_name = escape(name)
    safe_price = escape(price_text)
    safe_address = escape(address)
    safe_url = escape(booking_url)

    return (
        f"<b>{index}. {safe_name}</b>\n"
        f"💰 Цена: {safe_price}\n"
        f"📍 Адрес: {safe_address}\n"
        f"🔗 {safe_url}"
    )


async def start_search(
    message: Message,
    state: FSMContext,
    command: str,
) -> None:
    """Запускает последовательный сценарий поиска."""
    try:
        validate_rapidapi_settings()
    except RuntimeError as error:
        await message.answer(f"⚠️ Поиск пока недоступен: {error}")
        return

    await state.clear()
    await state.update_data(command=command)
    await state.set_state(SearchStates.city)

    await message.answer(
        f"{COMMAND_TITLES[command]}\n\nВведите город, например: <code>London</code>.",
        parse_mode="HTML",
    )


@router.message(Command("lowprice"))
async def lowprice_command(message: Message, state: FSMContext) -> None:
    """Запускает поиск дешёвых отелей."""
    await start_search(message, state, "lowprice")


@router.message(Command("highprice"))
async def highprice_command(message: Message, state: FSMContext) -> None:
    """Запускает поиск дорогих отелей."""
    await start_search(message, state, "highprice")


@router.message(Command("bestdeal"))
async def bestdeal_command(message: Message, state: FSMContext) -> None:
    """Запускает поиск отелей в диапазоне цены."""
    await start_search(message, state, "bestdeal")


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    """Отменяет незавершённый поиск."""
    current_state = await state.get_state()
    await state.clear()

    if current_state is None:
        await message.answer("Нет активного поиска.")
        return

    await message.answer("Поиск отменён.")


@router.message(SearchStates.city, F.text)
async def city_step(message: Message, state: FSMContext) -> None:
    """Принимает город."""
    city = (message.text or "").strip()

    if len(city) < 2:
        await message.answer("Название города слишком короткое. Введите ещё раз:")
        return

    await state.update_data(city=city)
    await state.set_state(SearchStates.checkin)
    await message.answer(
        "Введите дату заезда в формате <code>YYYY-MM-DD</code>, например "
        "<code>2026-09-10</code>.",
        parse_mode="HTML",
    )


@router.message(SearchStates.checkin, F.text)
async def checkin_step(message: Message, state: FSMContext) -> None:
    """Принимает и проверяет дату заезда."""
    checkin = (message.text or "").strip()
    checkin_date = parse_date(checkin)

    if checkin_date is None:
        await message.answer("Неверный формат. Введите дату как YYYY-MM-DD:")
        return

    if checkin_date < datetime.now(MONTENEGRO_TZ).date():
        await message.answer("Дата заезда не может быть в прошлом. Введите другую:")
        return

    await state.update_data(checkin=checkin)
    await state.set_state(SearchStates.checkout)
    await message.answer(
        "Введите дату выезда в формате <code>YYYY-MM-DD</code>.",
        parse_mode="HTML",
    )


@router.message(SearchStates.checkout, F.text)
async def checkout_step(message: Message, state: FSMContext) -> None:
    """Принимает и проверяет дату выезда."""
    checkout = (message.text or "").strip()
    checkout_date = parse_date(checkout)

    if checkout_date is None:
        await message.answer("Неверный формат. Введите дату как YYYY-MM-DD:")
        return

    data = await state.get_data()
    checkin_date = parse_date(str(data["checkin"]))

    if checkin_date is None:
        await state.clear()
        await message.answer("Не удалось прочитать дату заезда. Начните поиск заново.")
        return

    if checkout_date <= checkin_date:
        await message.answer(
            "Дата выезда должна быть позже даты заезда. Введите другую:"
        )
        return

    await state.update_data(checkout=checkout)

    if data["command"] == "bestdeal":
        await state.set_state(SearchStates.price_min)
        await message.answer(
            "Введите минимальную цену за ночь в USD, например: <code>50</code>.",
            parse_mode="HTML",
        )
        return

    await state.set_state(SearchStates.limit)
    await message.answer("Сколько отелей показать? Введите число от 1 до 10:")


@router.message(SearchStates.price_min, F.text)
async def price_min_step(message: Message, state: FSMContext) -> None:
    """Принимает нижнюю границу цены."""
    raw_price = (message.text or "").strip().replace(",", ".")

    try:
        price_min = float(raw_price)
    except ValueError:
        await message.answer("Введите положительное число, например: 50")
        return

    if price_min < 0:
        await message.answer("Минимальная цена не может быть отрицательной:")
        return

    await state.update_data(price_min=price_min)
    await state.set_state(SearchStates.price_max)
    await message.answer(
        "Введите максимальную цену за ночь в USD или <code>-</code> без ограничения.",
        parse_mode="HTML",
    )


@router.message(SearchStates.price_max, F.text)
async def price_max_step(message: Message, state: FSMContext) -> None:
    """Принимает верхнюю границу цены."""
    raw_price = (message.text or "").strip().replace(",", ".")

    if raw_price in {"-", "—", ""}:
        price_max = None
    else:
        try:
            price_max = float(raw_price)
        except ValueError:
            await message.answer(
                "Введите число, например: 150, или <code>-</code>.",
                parse_mode="HTML",
            )
            return

        data = await state.get_data()
        if price_max < float(data["price_min"]):
            await message.answer(
                "Максимальная цена не может быть меньше минимальной. Введите снова:"
            )
            return

    await state.update_data(price_max=price_max)
    await state.set_state(SearchStates.limit)
    await message.answer("Сколько отелей показать? Введите число от 1 до 10:")


@router.message(SearchStates.limit, F.text)
async def limit_step(message: Message, state: FSMContext) -> None:
    """Выполняет API-запрос, выводит и сохраняет результаты."""
    raw_limit = (message.text or "").strip()

    try:
        limit = int(raw_limit)
    except ValueError:
        await message.answer("Введите целое число от 1 до 10:")
        return

    if not 1 <= limit <= 10:
        await message.answer("Количество должно быть от 1 до 10:")
        return

    if message.from_user is None:
        await state.clear()
        return

    data = await state.get_data()
    command = str(data["command"])
    city = str(data["city"])
    checkin = str(data["checkin"])
    checkout = str(data["checkout"])

    price_min = float(data["price_min"]) if "price_min" in data else None
    price_max = float(data["price_max"]) if data.get("price_max") is not None else None

    await message.answer("🔎 Ищу отели, это может занять несколько секунд…")

    try:
        if command == "lowprice":
            hotels = await search_lowprice(city, checkin, checkout, limit=limit)

        elif command == "highprice":
            hotels = await search_highprice(city, checkin, checkout, limit=limit)

        else:
            pool_size = 100 if price_max is not None else 50

            hotels = await search_lowprice(
                city,
                checkin,
                checkout,
                limit=pool_size,
            )

            hotels = [
                hotel
                for hotel in hotels
                if (
                    hotel_rates_info(hotel).get("min_price") is not None
                    and float(hotel_rates_info(hotel)["min_price"]) >= price_min
                    and (
                        price_max is None
                        or float(hotel_rates_info(hotel)["min_price"]) <= price_max
                    )
                )
            ][:limit]
    except (HotelsApiError, ValueError) as error:
        logger.warning("Ошибка поиска: {}", error)
        await message.answer(
            "Не удалось получить результаты. Проверьте город, даты и настройки API."
        )
        return
    except Exception:  # noqa: BLE001
        logger.exception("Непредвиденная ошибка поиска")
        await message.answer(
            "Во время поиска произошла ошибка. Повторите попытку позже."
        )
        return
    finally:
        await state.clear()

    if not hotels:
        await message.answer("По этим параметрам отели не найдены.")
        return

    try:
        HistoryRepository.save_search(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            command=command,
            city=city,
            checkin=checkin,
            checkout=checkout,
            hotels_limit=limit,
            results=hotels,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось сохранить историю поиска")

    await message.answer(
        f"✅ Найдено отелей: {len(hotels)}\n\n"
        + "\n\n".join(
            format_hotel(index, hotel) for index, hotel in enumerate(hotels, start=1)
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
