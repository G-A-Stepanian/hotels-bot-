from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback, get_user_locale
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
    viewing = State()


MONTENEGRO_TZ = ZoneInfo("Europe/Podgorica")

COMMAND_TITLES = {
    "lowprice": "💸 Самые дешёвые отели",
    "highprice": "💎 Самые дорогие отели",
    "bestdeal": "⚖️ Отели в диапазоне цены",
}

CALENDAR_MAX_DATE = datetime(2027, 12, 31)


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _to_dt(d: date | datetime) -> datetime:
    """Конвертирует date → datetime(00:00:00). datetime оставляет как есть."""
    if isinstance(d, datetime):
        return d
    return datetime(d.year, d.month, d.day)


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def extract_hotel_name(hotel: dict[str, Any]) -> str:
    return str(
        hotel.get("name")
        or hotel.get("hotelName")
        or hotel.get("title")
        or "Без названия"
    )


def extract_address(hotel: dict[str, Any]) -> str:
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


def format_hotel(index: int, hotel: dict[str, Any]) -> str:
    name = extract_hotel_name(hotel)
    rates = hotel_rates_info(hotel)

    price = rates.get("min_price")
    currency = rates.get("currency") or ""
    price_text = f"{price} {currency}".strip() if price is not None else "не указана"

    address = extract_address(hotel)
    booking_url = hotel_booking_url(hotel) or "ссылка недоступна"

    return (
        f"<b>{index}. {escape(name)}</b>\n"
        f"💰 Цена: {escape(price_text)}\n"
        f"📍 Адрес: {escape(address)}\n"
        f"🔗 {escape(booking_url)}"
    )


def pagination_keyboard(page: int, total: int) -> InlineKeyboardMarkup:
    nav_buttons: list[InlineKeyboardButton] = []

    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"page:{page - 1}")
        )
    if page < total - 1:
        nav_buttons.append(
            InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"page:{page + 1}")
        )

    action_buttons = [
        InlineKeyboardButton(text="🔁 Новый поиск", callback_data="new_search")
    ]

    return InlineKeyboardMarkup(inline_keyboard=[nav_buttons, action_buttons])


async def send_hotel_page(
    message: Message,
    state: FSMContext,
    page: int,
) -> None:
    data = await state.get_data()
    hotels: list[dict[str, Any]] = data["hotels"]
    total = len(hotels)

    text = format_hotel(page + 1, hotels[page])
    text += f"\n\n<i>Отель {page + 1} из {total}</i>"

    await message.answer(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=pagination_keyboard(page, total),
    )
    await state.update_data(current_page=page)
    await state.set_state(SearchStates.viewing)


# ---------------------------------------------------------------------------
# Запуск сценария
# ---------------------------------------------------------------------------


async def start_search(message: Message, state: FSMContext, command: str) -> None:
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
    await start_search(message, state, "lowprice")


@router.message(Command("highprice"))
async def highprice_command(message: Message, state: FSMContext) -> None:
    await start_search(message, state, "highprice")


@router.message(Command("bestdeal"))
async def bestdeal_command(message: Message, state: FSMContext) -> None:
    await start_search(message, state, "bestdeal")


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    await state.clear()

    if current_state is None:
        await message.answer("Нет активного поиска.")
        return

    await message.answer("Поиск отменён.")


# ---------------------------------------------------------------------------
# Шаг 1 — город
# ---------------------------------------------------------------------------


@router.message(SearchStates.city, F.text)
async def city_step(message: Message, state: FSMContext) -> None:
    city = (message.text or "").strip()

    if len(city) < 2:
        await message.answer("Название города слишком короткое. Введите ещё раз:")
        return

    await state.update_data(city=city)
    await state.set_state(SearchStates.checkin)

    now_dt = _to_dt(datetime.now(MONTENEGRO_TZ).replace(tzinfo=None))

    calendar = SimpleCalendar(
        locale=await get_user_locale(message.from_user), show_alerts=True
    )
    calendar.set_dates_range(now_dt, CALENDAR_MAX_DATE)
    await message.answer(
        "📅 Выберите дату заезда:",
        reply_markup=await calendar.start_calendar(),
    )


# ---------------------------------------------------------------------------
# Шаг 2 — дата заезда (календарь)
# ---------------------------------------------------------------------------


@router.callback_query(SearchStates.checkin, SimpleCalendarCallback.filter())
async def checkin_calendar_callback(
    callback: CallbackQuery,
    callback_data: SimpleCalendarCallback,
    state: FSMContext,
) -> None:
    now_dt = _to_dt(datetime.now(MONTENEGRO_TZ).replace(tzinfo=None))

    calendar = SimpleCalendar(
        locale=await get_user_locale(callback.from_user), show_alerts=True
    )
    calendar.set_dates_range(now_dt, CALENDAR_MAX_DATE)
    selected, selected_date = await calendar.process_selection(callback, callback_data)

    if not selected:
        return

    selected_dt = _to_dt(selected_date)
    checkin_str = selected_dt.strftime("%Y-%m-%d")
    await state.update_data(checkin=checkin_str)
    await state.set_state(SearchStates.checkout)

    checkout_calendar = SimpleCalendar(
        locale=await get_user_locale(callback.from_user), show_alerts=True
    )
    checkout_min = datetime(selected_dt.year, selected_dt.month, selected_dt.day + 1)
    checkout_calendar.set_dates_range(checkout_min, CALENDAR_MAX_DATE)

    # ИСПРАВЛЕНИЕ :284 — InaccessibleMessage не имеет .answer()
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    await callback.message.answer(f"✅ Заезд: <b>{checkin_str}</b>", parse_mode="HTML")
    await callback.answer()
    await callback.message.answer(
        "📅 Выберите дату выезда:",
        reply_markup=await checkout_calendar.start_calendar(),
    )


# ---------------------------------------------------------------------------
# Шаг 3 — дата выезда (календарь)
# ---------------------------------------------------------------------------


@router.callback_query(SearchStates.checkout, SimpleCalendarCallback.filter())
async def checkout_calendar_callback(
    callback: CallbackQuery,
    callback_data: SimpleCalendarCallback,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    # ИСПРАВЛЕНИЕ :307 — parse_date может вернуть None, явный fallback
    parsed = parse_date(str(data["checkin"]))
    checkin_dt = _to_dt(parsed if parsed is not None else date.today())

    calendar = SimpleCalendar(
        locale=await get_user_locale(callback.from_user), show_alerts=True
    )
    checkout_min = datetime(checkin_dt.year, checkin_dt.month, checkin_dt.day + 1)
    calendar.set_dates_range(checkout_min, CALENDAR_MAX_DATE)

    selected, selected_date = await calendar.process_selection(callback, callback_data)

    if not selected:
        return

    selected_dt = _to_dt(selected_date)

    if selected_dt <= checkin_dt:
        await callback.answer(
            "⚠️ Дата выезда должна быть позже даты заезда!", show_alert=True
        )
        return

    checkout_str = selected_dt.strftime("%Y-%m-%d")
    await state.update_data(checkout=checkout_str)

    # ИСПРАВЛЕНИЕ :333/:338/:344 — проверяем тип перед .answer()
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    await callback.message.answer(f"✅ Выезд: <b>{checkout_str}</b>", parse_mode="HTML")
    await callback.answer()

    if data["command"] == "bestdeal":
        await state.set_state(SearchStates.price_min)
        await callback.message.answer(
            "Введите минимальную цену за ночь в USD, например: <code>50</code>.",
            parse_mode="HTML",
        )
    else:
        await state.set_state(SearchStates.limit)
        await callback.message.answer(
            "Сколько отелей показать? Введите число от 1 до 10:"
        )


# ---------------------------------------------------------------------------
# Шаг 4 — цены (только для bestdeal)
# ---------------------------------------------------------------------------


@router.message(SearchStates.price_min, F.text)
async def price_min_step(message: Message, state: FSMContext) -> None:
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


# ---------------------------------------------------------------------------
# Шаг 5 — лимит и API-запрос
# ---------------------------------------------------------------------------


@router.message(SearchStates.limit, F.text)
async def limit_step(message: Message, state: FSMContext) -> None:
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
    price_min: float | None = float(data["price_min"]) if "price_min" in data else None
    price_max: float | None = (
        float(data["price_max"]) if data.get("price_max") is not None else None
    )

    await message.answer("🔎 Ищу отели, это может занять несколько секунд…")

    hotels: list[dict[str, Any]] = []

    try:
        if command == "lowprice":
            hotels = await search_lowprice(city, checkin, checkout, limit=limit)

        elif command == "highprice":
            hotels = await search_highprice(city, checkin, checkout, limit=limit)

        else:  # bestdeal
            pool_size = 100 if price_max is not None else 50
            hotels = await search_lowprice(city, checkin, checkout, limit=pool_size)
            # ИСПРАВЛЕНИЕ :454/:457 — min_price может быть None, фильтруем безопасно
            filtered: list[dict[str, Any]] = []
            for h in hotels:
                raw_price = hotel_rates_info(h).get("min_price")
                if raw_price is None:
                    continue
                h_price = float(raw_price)
                if price_min is not None and h_price < price_min:
                    continue
                if price_max is not None and h_price > price_max:
                    continue
                filtered.append(h)
            hotels = filtered[:limit]

    except (HotelsApiError, ValueError) as error:
        logger.warning("Ошибка поиска: {}", error)
        await state.clear()
        await message.answer(
            "Не удалось получить результаты. Проверьте город, даты и настройки API."
        )
        return

    except Exception:  # noqa: BLE001
        logger.exception("Непредвиденная ошибка поиска")
        await state.clear()
        await message.answer(
            "Во время поиска произошла ошибка. Повторите попытку позже."
        )
        return

    if not hotels:
        await state.clear()
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

    await state.update_data(hotels=hotels)
    await message.answer(f"✅ Найдено отелей: {len(hotels)}")
    await send_hotel_page(message, state, page=0)


# ---------------------------------------------------------------------------
# Пагинация результатов
# ---------------------------------------------------------------------------


@router.callback_query(SearchStates.viewing, F.data.startswith("page:"))
async def paginate_callback(callback: CallbackQuery, state: FSMContext) -> None:
    # ИСПРАВЛЕНИЕ :509/:512/:513 — проверяем что message именно Message
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    page = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await callback.message.delete()
    await send_hotel_page(callback.message, state, page)
    await callback.answer()


@router.callback_query(SearchStates.viewing, F.data == "new_search")
async def new_search_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()

    # ИСПРАВЛЕНИЕ :523 — проверяем тип перед .delete()
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    await callback.message.delete()
    await callback.message.answer(
        "Выберите команду для нового поиска:\n"
        "/lowprice — дешёвые отели\n"
        "/highprice — дорогие отели\n"
        "/bestdeal — в диапазоне цены"
    )
    await callback.answer()
