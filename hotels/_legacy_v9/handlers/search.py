"""
handlers/search.py — основной сценарий поиска отелей.

Команды:
- /lowprice  — найти самые дешёвые отели
- /highprice — найти самые дорогие отели
- /bestdeal  — отфильтровать по диапазону цен (min..max)

Поток (FSM):
1) city -> (выбор checkin) -> (выбор checkout) -> (опц. цены для bestdeal) -> limit
2) выполняем API запрос(ы), нормализуем результаты в список pages
3) сохраняем запрос + pages в SQLite
4) переходим в состояние browse и показываем результаты постранично (inline pagination)

Календарь:
- inline calendar через aiogram_calendar
- ограничения: не раньше сегодня; выезд минимум +1 день; горизонт выбора MAX_DAYS_AHEAD

Пагинация:
- 1 отель = 1 страница
- кнопки: ⬅️ ➡️, 📸 Фото, 🗺 На карте, ✖️ Закрыть
- фото/карта отправляются отдельными сообщениями, карточка редактируется через edit_text
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram_calendar import (
    SimpleCalendar,
    SimpleCalendarCallback,
)  # pip install aiogram_calendar
from database.history import add_history
from loguru import logger
from utils.hotel_utils import (
    HotelRender,
    coords_str,
    details_desc_and_photos,
    fallback_photos_from_search,
    hotel_name,
    hotel_price_line,
    parse_date_yyyy_mm_dd,
    parse_float,
    parse_int,
    send_photos,
    to_history_dict,
)

from api.hotels import (
    HotelsApiError,
    extract_previous_price_from_search,
    get_hotel_details,
    hotel_booking_url,
    hotel_rates_info,
    search_highprice,
    search_lowprice,
)
from config import DB_PATH

router = Router(name=__name__)

FETCH_POOL = 80

CAL_LOCALE = "ru_RU"
MAX_DAYS_AHEAD = 365
MIN_STAY_NIGHTS = 1


class SearchState(StatesGroup):
    """FSM состояния сценария поиска."""

    city = State()
    checkin = State()
    checkout = State()
    price_min = State()
    price_max = State()
    limit = State()
    browse = State()  # режим пагинации


class BrowseCb(CallbackData, prefix="br"):
    """CallbackData для постраничного просмотра результата."""

    action: str  # prev/next/noop/photos/map/close
    idx: int


def _is_no_upper_bound(s: str) -> bool:
    """Проверка 'нет верхнего предела' для bestdeal max price."""
    s = (s or "").strip().lower()
    return s in {"-", "—", "нет", "no", "none", "null", "inf", "infinity", "∞", ""}


def _min_price(h: dict[str, Any]) -> float | None:
    """Извлечь минимальную цену из hotel_rates_info для фильтрации bestdeal."""
    rates = hotel_rates_info(h)
    v = rates.get("min_price")
    return float(v) if isinstance(v, (int, float)) else None


def _today() -> date:
    """Текущая локальная дата (для ограничения календаря)."""
    return datetime.now().date()


def _to_dt(d: date) -> datetime:
    """date -> datetime (00:00) для календаря."""
    return datetime.combine(d, time.min)


def _global_range() -> tuple[date, date]:
    """Глобальный диапазон выбора дат: [today .. today+MAX_DAYS_AHEAD]."""
    d0 = _today()
    d1 = d0 + timedelta(days=MAX_DAYS_AHEAD)
    return d0, d1


def _calendar(min_d: date, max_d: date) -> SimpleCalendar:
    """
    Создать календарь с ограничением диапазона дат.

    show_alerts=True — чтобы календарь мог показывать предупреждения пользователю.
    """
    cal = SimpleCalendar(locale=CAL_LOCALE, show_alerts=True)
    cal.set_dates_range(_to_dt(min_d), _to_dt(max_d))
    return cal


async def _send_calendar(
    message: Message, title: str, min_d: date, max_d: date
) -> None:
    """Отправить inline-календарь в чат."""
    await message.answer(
        title, reply_markup=await _calendar(min_d, max_d).start_calendar()
    )


def _parse_coords(coords: str) -> tuple[float, float] | None:
    """
    Парсить координаты из строки 'lat, lon'.

    В проекте coords сохраняются как строка (см. utils.coords_str).
    """
    s = (coords or "").strip()
    if not s or s.lower() == "неизвестны":
        return None
    try:
        a, b = [x.strip() for x in s.split(",", 1)]
        return float(a), float(b)
    except Exception:
        return None


def _pager_kb(idx: int, total: int) -> InlineKeyboardMarkup:
    """
    Inline-клавиатура постраничного просмотра.
    """
    prev_idx = max(0, idx - 1)
    next_idx = min(total - 1, idx + 1)

    row1 = [
        InlineKeyboardButton(
            text="⬅️", callback_data=BrowseCb(action="prev", idx=prev_idx).pack()
        ),
        InlineKeyboardButton(
            text=f"{idx + 1}/{total}",
            callback_data=BrowseCb(action="noop", idx=idx).pack(),
        ),
        InlineKeyboardButton(
            text="➡️", callback_data=BrowseCb(action="next", idx=next_idx).pack()
        ),
    ]
    row2 = [
        InlineKeyboardButton(
            text="📸 Фото", callback_data=BrowseCb(action="photos", idx=idx).pack()
        ),
        InlineKeyboardButton(
            text="🗺 На карте", callback_data=BrowseCb(action="map", idx=idx).pack()
        ),
        InlineKeyboardButton(
            text="✖️ Закрыть", callback_data=BrowseCb(action="close", idx=idx).pack()
        ),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def _page_text(
    idx: int, total: int, checkin: str, checkout: str, item: dict[str, Any]
) -> str:
    """
    Текст одной страницы (1 отель).

    item — словарь, который вернул to_history_dict(HotelRender).
    """
    name = item.get("name") or "Без названия"
    price = item.get("price") or "неизвестна"
    coords = item.get("coords") or "неизвестны"
    desc = item.get("desc") or "нет"
    booking_url = item.get("booking_url") or "нет"

    return (
        f"Отель {idx + 1}/{total}\n"
        f"{name}\n"
        f"Даты: {checkin} — {checkout}\n"
        f"Цена: {price}\n"
        f"Бронирование: {booking_url}\n"
        f"Координаты: {coords}\n"
        f"Описание: {desc}"
    )


async def _start(message: Message, state: FSMContext, command: str) -> None:
    """Общий старт сценария для /lowprice /highprice /bestdeal."""
    user_id = message.from_user.id if message.from_user else None
    logger.info(f"Search started: cmd={command} user={user_id}")

    await state.clear()
    await state.update_data(command=command)
    await state.set_state(SearchState.city)
    await message.answer("Введите город (например: London):")


@router.message(Command("lowprice"))
async def lowprice_cmd(message: Message, state: FSMContext) -> None:
    """Запуск сценария дешёвых отелей."""
    await _start(message, state, "lowprice")


@router.message(Command("highprice"))
async def highprice_cmd(message: Message, state: FSMContext) -> None:
    """Запуск сценария дорогих отелей."""
    await _start(message, state, "highprice")


@router.message(Command("bestdeal"))
async def bestdeal_cmd(message: Message, state: FSMContext) -> None:
    """Запуск сценария bestdeal (фильтрация по цене)."""
    await _start(message, state, "bestdeal")


@router.message(SearchState.city, F.text)
async def city_step(message: Message, state: FSMContext) -> None:
    """Шаг ввода города."""
    city = (message.text or "").strip()
    if len(city) < 2:
        await message.answer("Город слишком короткий. Введите ещё раз:")
        return

    await state.update_data(city=city)
    await state.set_state(SearchState.checkin)

    d0, d1 = _global_range()
    await _send_calendar(
        message, "Выберите дату заезда (или введи YYYY-MM-DD):", min_d=d0, max_d=d1
    )


# -------- Текстовый ввод дат (fallback) --------


@router.message(SearchState.checkin, F.text)
async def checkin_text_step(message: Message, state: FSMContext) -> None:
    """Fallback: ввод даты заезда текстом YYYY-MM-DD."""
    checkin_s = (message.text or "").strip()
    d_in = parse_date_yyyy_mm_dd(checkin_s)
    if d_in is None:
        await message.answer("Неверная дата. Выбери в календаре или введи YYYY-MM-DD:")
        return

    d0, d1 = _global_range()
    if d_in < d0 or d_in > d1:
        await message.answer(
            f"Дата заезда должна быть в диапазоне {d0.isoformat()} … {d1.isoformat()}."
        )
        return

    await state.update_data(checkin=checkin_s)
    await state.set_state(SearchState.checkout)

    min_out = d_in + timedelta(days=MIN_STAY_NIGHTS)
    await _send_calendar(
        message, "Выберите дату выезда (или введи YYYY-MM-DD):", min_d=min_out, max_d=d1
    )


@router.message(SearchState.checkout, F.text)
async def checkout_text_step(message: Message, state: FSMContext) -> None:
    """Fallback: ввод даты выезда текстом YYYY-MM-DD."""
    checkout_s = (message.text or "").strip()
    d_out = parse_date_yyyy_mm_dd(checkout_s)
    if d_out is None:
        await message.answer("Неверная дата. Выбери в календаре или введи YYYY-MM-DD:")
        return

    data = await state.get_data()
    d_in = parse_date_yyyy_mm_dd(str(data.get("checkin") or ""))
    if d_in is None:
        await message.answer(
            "Не вижу дату заезда. Начни заново: /lowprice или /highprice или /bestdeal"
        )
        await state.clear()
        return

    d0, d1 = _global_range()
    min_out = d_in + timedelta(days=MIN_STAY_NIGHTS)

    if d_out < min_out:
        await message.answer(
            "Дата выезда должна быть позже даты заезда. Выбери другую дату:"
        )
        return
    if d_out < d0 or d_out > d1:
        await message.answer(
            f"Дата выезда должна быть в диапазоне {d0.isoformat()} … {d1.isoformat()}."
        )
        return

    await state.update_data(checkout=checkout_s)

    cmd = data.get("command")
    if cmd == "bestdeal":
        await state.set_state(SearchState.price_min)
        await message.answer("Введите минимальную цену (например: 50):")
    else:
        await state.set_state(SearchState.limit)
        await message.answer("Сколько отелей показать? (1–10):")


# -------- Календарь (callback) --------


@router.callback_query(SimpleCalendarCallback.filter())
async def calendar_callback(
    call: CallbackQuery, callback_data: SimpleCalendarCallback, state: FSMContext
) -> None:
    """
    Обработчик inline-календаря.

    В зависимости от FSM-состояния выбираем дату checkin или checkout.
    """
    current = await state.get_state()
    if current not in (SearchState.checkin.state, SearchState.checkout.state):
        await call.answer()
        return

    data = await state.get_data()
    d0, d1 = _global_range()

    if current == SearchState.checkin.state:
        cal = _calendar(d0, d1)
        selected, dt = await cal.process_selection(call, callback_data)
        if not selected:
            return

        picked_d = dt.date()
        await state.update_data(checkin=picked_d.isoformat())
        await state.set_state(SearchState.checkout)

        min_out = picked_d + timedelta(days=MIN_STAY_NIGHTS)
        if call.message:
            await _send_calendar(
                call.message,
                "Выберите дату выезда (или введи YYYY-MM-DD):",
                min_d=min_out,
                max_d=d1,
            )
        return

    # checkout
    checkin_s = str(data.get("checkin") or "")
    d_in = parse_date_yyyy_mm_dd(checkin_s)
    if d_in is None:
        await call.answer("Не вижу дату заезда. Начни заново.", show_alert=True)
        await state.clear()
        return

    min_out = d_in + timedelta(days=MIN_STAY_NIGHTS)
    cal = _calendar(min_out, d1)
    selected, dt = await cal.process_selection(call, callback_data)
    if not selected:
        return

    picked_d = dt.date()
    await state.update_data(checkout=picked_d.isoformat())

    cmd = data.get("command")
    if call.message:
        if cmd == "bestdeal":
            await state.set_state(SearchState.price_min)
            await call.message.answer("Введите минимальную цену (например: 50):")
        else:
            await state.set_state(SearchState.limit)
            await call.message.answer("Сколько отелей показать? (1–10):")


# -------- Bestdeal: цены --------


@router.message(SearchState.price_min, F.text)
async def price_min_step(message: Message, state: FSMContext) -> None:
    """Ввод минимальной цены для bestdeal."""
    v = parse_float(message.text or "")
    if v is None or v < 0:
        await message.answer("Введите число (минимальная цена), например 50:")
        return

    await state.update_data(price_min=float(v))
    await state.set_state(SearchState.price_max)
    await message.answer(
        "Введите максимальную цену (например: 200). Если верхнего предела нет — отправьте '-'."
    )


@router.message(SearchState.price_max, F.text)
async def price_max_step(message: Message, state: FSMContext) -> None:
    """Ввод максимальной цены (или '-') для bestdeal."""
    raw = message.text or ""
    if _is_no_upper_bound(raw):
        await state.update_data(price_max=None)
        await state.set_state(SearchState.limit)
        await message.answer("Сколько отелей показать? (1–10):")
        return

    v = parse_float(raw)
    if v is None or v < 0:
        await message.answer(
            "Введите число (макс. цена), например 200, или '-' если без верхнего предела:"
        )
        return

    data = await state.get_data()
    price_min = float(data["price_min"])
    if float(v) < price_min:
        await message.answer(
            "Максимальная цена должна быть >= минимальной. Введите ещё раз:"
        )
        return

    await state.update_data(price_max=float(v))
    await state.set_state(SearchState.limit)
    await message.answer("Сколько отелей показать? (1–10):")


# -------- Поиск + подготовка страниц --------


@router.message(SearchState.limit, F.text)
async def limit_step(message: Message, state: FSMContext) -> None:
    """Ввод limit, затем выполнение поиска и старт пагинации."""
    limit = parse_int(message.text or "")
    if limit is None or not (1 <= limit <= 10):
        await message.answer("Введите число от 1 до 10:")
        return

    data = await state.get_data()
    cmd = data["command"]
    city = data["city"]
    checkin = data["checkin"]
    checkout = data["checkout"]

    await message.answer("Ищу отели...")

    try:
        if cmd == "lowprice":
            hotels = await search_lowprice(city, checkin, checkout, limit=limit)
        elif cmd == "highprice":
            hotels = await search_highprice(city, checkin, checkout, limit=limit)
        elif cmd == "bestdeal":
            price_min = float(data["price_min"])
            price_max = data.get("price_max")  # float | None

            pool = await search_lowprice(city, checkin, checkout, limit=FETCH_POOL)

            filtered: list[dict[str, Any]] = []
            for h in pool:
                p = _min_price(h)
                if p is None:
                    continue
                if p < price_min:
                    continue
                if price_max is not None and p > float(price_max):
                    continue
                filtered.append(h)

            filtered.sort(key=lambda x: _min_price(x) or 1e18)
            hotels = filtered[:limit]
        else:
            await message.answer(
                "Неизвестная команда. Начни заново: /lowprice, /highprice, /bestdeal"
            )
            await state.clear()
            return

    except HotelsApiError as e:
        logger.exception("Search API error")
        await message.answer(f"Ошибка API: {e}")
        await state.clear()
        return
    except Exception as e:
        logger.exception("Search unexpected error")
        await message.answer(f"Неожиданная ошибка: {e}")
        await state.clear()
        return

    if not hotels:
        await message.answer("Ничего не найдено.")
        await state.clear()
        return

    # Собираем результаты в "страницы" (dict), пригодные для истории и пагинации.
    pages: list[dict[str, Any]] = []

    for h in hotels:
        hid = h.get("hotelId")

        desc_text = "нет"
        photos: list[str] = []
        details: dict[str, Any] | None = None

        prev = None
        if hid is not None:
            try:
                prev = extract_previous_price_from_search(h)
            except Exception:
                prev = None

            try:
                details = await get_hotel_details(
                    str(hid), checkin, checkout, previous_price=prev
                )
                desc_text, photos = details_desc_and_photos(details)
            except Exception:
                desc_text, photos, details = "нет", [], None

        if not photos:
            photos = fallback_photos_from_search(h, limit=3)

        try:
            book_url = hotel_booking_url(h, details)
        except Exception:
            book_url = None

        r = HotelRender(
            name=hotel_name(h),
            price=hotel_price_line(h, hotel_rates_info),
            coords=coords_str(h),
            desc=desc_text,
            booking_url=book_url,
            photos=photos,
        )
        pages.append(to_history_dict(r))

    # Сохраняем в историю (одним INSERT).
    user_id = message.from_user.id if message.from_user else 0
    add_history(
        str(DB_PATH),
        user_id,
        command=cmd,
        city=city,
        checkin=checkin,
        checkout=checkout,
        hotels_limit=limit,
        results=pages,
    )

    # Старт пагинации.
    await state.update_data(
        browse_pages=pages,
        browse_idx=0,
        browse_checkin=checkin,
        browse_checkout=checkout,
    )
    await state.set_state(SearchState.browse)

    text = _page_text(0, len(pages), checkin, checkout, pages[0])
    await message.answer(
        text, reply_markup=_pager_kb(0, len(pages)), disable_web_page_preview=True
    )


# -------- Пагинация (callback) --------


@router.callback_query(BrowseCb.filter())
async def browse_callback(
    call: CallbackQuery, callback_data: BrowseCb, state: FSMContext
) -> None:
    """
    Управление просмотром результатов:
    - prev/next: редактируем карточку (edit_text)
    - photos/map: отправляем отдельные сообщения
    - close: закрываем просмотр (очищаем state)
    """
    await call.answer()

    if callback_data.action == "noop":
        return

    data = await state.get_data()
    pages = data.get("browse_pages")

    if not isinstance(pages, list) or not pages:
        if call.message:
            await call.message.answer(
                "Сессия просмотра устарела. Запусти поиск заново: /lowprice /highprice /bestdeal"
            )
        await state.clear()
        return

    total = len(pages)
    idx = max(0, min(total - 1, int(callback_data.idx)))

    checkin = str(data.get("browse_checkin") or "")
    checkout = str(data.get("browse_checkout") or "")

    if callback_data.action in ("prev", "next"):
        await state.update_data(browse_idx=idx)
        if call.message:
            await call.message.edit_text(
                _page_text(idx, total, checkin, checkout, pages[idx]),
                reply_markup=_pager_kb(idx, total),
                disable_web_page_preview=True,
            )
        return

    if callback_data.action == "photos":
        item = pages[idx]
        photos = item.get("photos") or []
        if call.message:
            if isinstance(photos, list) and photos:
                await send_photos(call.message, [str(x) for x in photos], limit=3)
            else:
                await call.message.answer("Фото не найдено для этого отеля.")
        return

    if callback_data.action == "map":
        item = pages[idx]
        coords = str(item.get("coords") or "")
        parsed = _parse_coords(coords)
        if not parsed:
            if call.message:
                await call.message.answer("Координаты недоступны для этого отеля.")
            return
        lat, lon = parsed
        if call.message:
            await call.message.answer_location(latitude=lat, longitude=lon)
        return

    if callback_data.action == "close":
        if call.message:
            await call.message.edit_text(
                "Просмотр закрыт. Можешь запустить новый поиск: /lowprice /highprice /bestdeal"
            )
        await state.clear()
        return
