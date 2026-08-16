"""
api/hotels.py — HTTP-клиент для Priceline (RapidAPI).

Модуль инкапсулирует:
- Создание/переиспользование aiohttp.ClientSession.
- Повтор запросов (retry) при временных ошибках (429/5xx/таймауты).
- Поиск locationId по названию города (autocomplete).
- Поиск отелей (low/high by price).
- Получение деталей отеля.
- Утилиты для извлечения цен и deeplink/booking URL.

Внешний код (handlers) должен работать только с функциями:
- search_lowprice / search_highprice
- get_hotel_details
- hotel_rates_info / extract_previous_price_from_search / hotel_booking_url

Конфигурация берётся из config.py:
- RAPIDAPI_HOST, RAPIDAPI_KEY
"""

from __future__ import annotations

import asyncio
import email.utils
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from json import JSONDecodeError
from typing import Any

import aiohttp
from aiohttp import ContentTypeError
from loguru import logger

from config import RAPIDAPI_HOST, RAPIDAPI_KEY

BASE_URL = f"https://{RAPIDAPI_HOST}"

# Заголовки RapidAPI: ключ и хост обязателен для доступа к endpoint.
HEADERS: dict[str, str] = {
    "X-RapidAPI-Key": RAPIDAPI_KEY or "",
    "X-RapidAPI-Host": RAPIDAPI_HOST or "",
}

# Пути (endpoints) для текущего RapidAPI хоста.
AUTOCOMPLETE_PATH = "/hotels/auto-complete"
SEARCH_PATH = "/hotels/search"
DETAILS_PATH = "/hotels/details"

# Ограничиваем параллельные запросы к API, чтобы не упираться в лимиты.
_API_SEMAPHORE = asyncio.Semaphore(2)

# В search limit можно использовать >10 (например, для bestdeal pool).
_MAX_API_LIMIT = 100

# Общая HTTP-сессия (не создаём новую на каждый запрос).
_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()


@dataclass(frozen=True)
class ApiResponse:
    """
    Унифицированный результат HTTP-вызова.

    Attributes:
        status: HTTP статус ответа.
         JSON (dict/list) или text (str), если JSON распарсить не удалось.
        url: финальный URL (с учётом query string), удобен для логирования.
    """

    status: int
    data: Any
    url: str


class HotelsApiError(RuntimeError):
    """Ошибки бизнес-уровня, которые удобно показывать пользователю как 'Ошибка API'."""


async def init_http_session() -> None:
    """
    Явно инициализировать HTTP-сессию.

    Можно не вызывать: сессия создастся лениво при первом запросе.
    """
    await _get_session()


async def close_http_session() -> None:
    """Закрыть общую HTTP-сессию (вызывать при остановке бота)."""
    global _session
    async with _session_lock:
        if _session and not _session.closed:
            await _session.close()
        _session = None


async def _get_session() -> aiohttp.ClientSession:
    """
    Получить общую aiohttp-сессию (создаёт при необходимости).

    Использование общей сессии важно:
    - экономит ресурсы,
    - корректно переиспользует соединения (keep-alive),
    - меньше нагрузка и быстрее ответы.
    """
    global _session
    async with _session_lock:
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession()
        return _session


def _retry_after_seconds(retry_after_value: str | None) -> float | None:
    """
    Преобразовать Retry-After header в секунды.

    Retry-After бывает:
    - числом секунд,
    - HTTP-date (RFC 7231).
    """
    if not retry_after_value:
        return None

    # Вариант 1: число секунд
    try:
        return max(0.0, float(int(retry_after_value)))
    except ValueError:
        pass

    # Вариант 2: HTTP-date
    try:
        dt = email.utils.parsedate_to_datetime(retry_after_value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (dt - now).total_seconds())
    except (TypeError, ValueError):
        return None


async def _get_json(
    path: str,
    params: dict[str, Any],
    timeout_sec: int = 30,
    attempts: int = 4,
) -> ApiResponse:
    """
    Выполнить GET-запрос к RapidAPI и вернуть ApiResponse.

    Retry политика:
    - повторяем при 429 и 5xx, а также при ClientError/TimeoutError,
    - задержка: Retry-After (если есть) или экспоненциальный backoff + jitter.
    """
    url = f"{BASE_URL}{path}"
    last_status: int = 0
    last_data: Any = None
    last_url: str = url

    session = await _get_session()

    for attempt in range(1, attempts + 1):
        try:
            async with (
                _API_SEMAPHORE,
                session.get(
                    url,
                    headers=HEADERS,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout_sec),
                ) as resp,
            ):
                last_status = resp.status
                last_url = str(resp.url)
                retry_after = resp.headers.get("Retry-After")

                try:
                    data = await resp.json()
                except (ContentTypeError, JSONDecodeError):
                    data = await resp.text()

                last_data = data

                if resp.status == 200:
                    return ApiResponse(resp.status, data, last_url)

                if resp.status in (429, 500, 502, 503, 504):
                    wait = _retry_after_seconds(retry_after)
                    if wait is None:
                        wait = min(20.0, 0.8 * (2 ** (attempt - 1)) + random.random())

                    logger.warning(
                        f"HTTP {resp.status} {path}, retry in {wait:.1f}s "
                        f"(attempt {attempt}/{attempts}) url={last_url}"
                    )
                    await asyncio.sleep(wait)
                    continue

                # не retryable
                return ApiResponse(resp.status, data, last_url)

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_data = {"error": str(e), "type": type(e).__name__}
            wait = min(20.0, 0.8 * (2 ** (attempt - 1)) + random.random())
            logger.warning(
                f"HTTP client error {path}: {e}. retry in {wait:.1f}s "
                f"(attempt {attempt}/{attempts})"
            )
            await asyncio.sleep(wait)

    return ApiResponse(last_status, last_data, last_url)


async def find_location_id(city: str) -> str:
    """
    Получить locationId для города (используется в поиске отелей).

    Args:
        city: строка города, например "London".

    Returns:
        locationId как строка.

    Raises:
        ValueError: если city пустой.
        HotelsApiError: если API вернул ошибку/пустой результат.
    """
    city = city.strip()
    if not city:
        raise ValueError("Пустой город")

    resp = await _get_json(AUTOCOMPLETE_PATH, params={"query": city}, timeout_sec=40)
    if resp.status != 200:
        raise HotelsApiError(f"Auto-complete failed: {resp.status} {resp.data}")

    items = (resp.data or {}).get("data", {}).get("searchItems", [])
    if not items or not isinstance(items, list) or not isinstance(items[0], dict):
        raise HotelsApiError("200 OK, но searchItems пустой/не найден")

    loc_id = items[0].get("id") or items[0].get("cityID")
    if not loc_id:
        raise HotelsApiError("200 OK, но в первом searchItems нет id/cityID")

    return str(loc_id)


def _extract_hotels_list(payload: Any) -> list[dict[str, Any]]:
    """
    Достаёт список отелей из разных вариантов структуры ответа API.

    API может возвращать:
    - dict -> data -> hotels/results/result,
    - dict -> hotels/results/result,
    - list напрямую.
    """
    if isinstance(payload, dict):
        for key in ("hotels", "results", "result", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
            if isinstance(value, dict):
                inner = (
                    value.get("hotels") or value.get("results") or value.get("result")
                )
                if isinstance(inner, list):
                    return [x for x in inner if isinstance(x, dict)]

    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    return []


def _to_float(x: Any) -> float | None:
    """Преобразует число/строку с числом в float (или None)."""
    if x is None:
        return None

    try:
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            s = "".join(ch for ch in x if (ch.isdigit() or ch == "."))
            return float(s) if s else None
    except (TypeError, ValueError):
        return None

    return None


def hotel_rates_info(h: dict[str, Any]) -> dict[str, str | float | None]:
    """
    Унифицированная выжимка по ценам (из ratesSummary).

    Returns:
        dict с ключами:
        - currency: код валюты (например "USD")
        - min_price: минимальная цена
        - grand_total: итоговая цена
        - nightly_total: цена за ночь
    """
    rs = h.get("ratesSummary") or {}
    return {
        "currency": (rs.get("minCurrencyCode") or rs.get("currencyCode")),
        "min_price": _to_float(rs.get("minPrice")),
        "grand_total": _to_float(rs.get("grandTotal")),
        "nightly_total": _to_float(rs.get("nightlyRateIncludingTaxesAndFees")),
    }


def _hotel_price_value(h: dict[str, Any]) -> float:
    """
    Числовой ключ сортировки по цене.

    Если извлечь цену не удалось, возвращается очень большое число.
    Такой отель окажется в конце списка.
    """
    rs = h.get("ratesSummary") or {}
    candidates = [
        rs.get("minPrice"),
        rs.get("nightlyRateIncludingTaxesAndFees"),
        rs.get("grandTotal"),
        # fallback-и для разных структур
        h.get("price"),
        h.get("minPrice"),
        h.get("min_total_price"),
        (h.get("rate") or {}).get("total"),
        (h.get("rate") or {}).get("price"),
        (h.get("pricing") or {}).get("total"),
        (h.get("pricing") or {}).get("nightly"),
    ]

    for c in candidates:
        v = _to_float(c)
        if v is not None:
            return v

    return 1e18


def _clamp_api_limit(limit: int) -> int:
    """Ограничить limit диапазоном 1.._MAX_API_LIMIT."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    return max(1, min(_MAX_API_LIMIT, limit))


async def search_lowprice(
    city: str,
    checkin_date: str,
    checkout_date: str,
    limit: int = 5,
    adults: int = 2,
) -> list[dict[str, Any]]:
    """
    Поиск отелей по городу и датам с сортировкой от дешёвых к дорогим.

    Важно:
    - API сортирует по PRICE, но структура может быть разной, поэтому дополнительно
      сортируем локально по извлечённой цене.
    """
    limit = _clamp_api_limit(limit)
    location_id = await find_location_id(city)

    params = {
        "locationId": location_id,
        "checkIn": checkin_date,
        "checkOut": checkout_date,
        "adults": str(adults),
        "rooms": "1",
        "sort": "PRICE",
        "limit": str(limit),
    }

    resp = await _get_json(SEARCH_PATH, params=params, timeout_sec=30)
    if resp.status != 200:
        raise HotelsApiError(f"Search failed: {resp.status} {resp.data}")

    hotels = _extract_hotels_list(resp.data)
    hotels.sort(key=_hotel_price_value)
    return hotels[:limit]


async def search_highprice(
    city: str,
    checkin_date: str,
    checkout_date: str,
    limit: int = 5,
    adults: int = 2,
) -> list[dict[str, Any]]:
    """Поиск отелей с сортировкой от дорогих к дешёвым."""
    limit = _clamp_api_limit(limit)
    location_id = await find_location_id(city)

    params = {
        "locationId": location_id,
        "checkIn": checkin_date,
        "checkOut": checkout_date,
        "adults": str(adults),
        "rooms": "1",
        "sort": "PRICE",
        "limit": str(limit),
    }

    resp = await _get_json(SEARCH_PATH, params=params, timeout_sec=30)
    if resp.status != 200:
        raise HotelsApiError(f"Search failed: {resp.status} {resp.data}")

    hotels = _extract_hotels_list(resp.data)
    hotels.sort(key=_hotel_price_value, reverse=True)
    return hotels[:limit]


def extract_previous_price_from_search(h: dict[str, Any]) -> float | None:
    """
    Попытаться извлечь "предыдущую" цену (strike-through/previous) из результата поиска.

    Иногда API требует previousPrice для эндпоинта details.
    """
    rs = h.get("ratesSummary") or {}
    return (
        _to_float(rs.get("minStrikePrice"))
        or _to_float(rs.get("strikeThroughPrice"))
        or _to_float(rs.get("previousPrice"))
        or _to_float(rs.get("minPrice"))
    )


async def get_hotel_details(
    hotel_id: str,
    checkin: str,
    checkout: str,
    previous_price: float | None = None,
) -> dict[str, Any]:
    """
    Получить детали отеля по hotelId и датам.

    Args:
        hotel_id: идентификатор отеля.
        checkin, checkout: даты в ISO (YYYY-MM-DD).
        previous_price: опционально (если есть).

    Returns:
        dict (JSON) ответа details.

    Raises:
        HotelsApiError: при HTTP != 200 или неожиданных данных.
    """
    hotel_id = str(hotel_id or "").strip()
    if not hotel_id:
        raise ValueError("Пустой hotel_id")

    params: dict[str, Any] = {
        "hotelId": hotel_id,
        "checkIn": checkin,
        "checkOut": checkout,
    }
    if previous_price is not None:
        params["previousPrice"] = str(previous_price)

    resp = await _get_json(DETAILS_PATH, params=params, timeout_sec=40)
    if resp.status != 200:
        raise HotelsApiError(f"Details failed: {resp.status} {resp.data}")

    if isinstance(resp.data, dict):
        return resp.data

    raise HotelsApiError(f"Details: unexpected payload type: {type(resp.data)}")


def hotel_booking_url(
    h: dict[str, Any], details: dict[str, Any] | None = None
) -> str | None:
    """
    Получить URL для перехода к бронированию/странице отеля.

    Логика:
    1) Пытаемся найти "deeplink/url" в details (если переданы).
    2) Fallback: ссылка на Priceline по hotelId.
    """
    if isinstance(details, dict):
        data = details.get("data")
        if isinstance(data, dict):
            for key in (
                "deeplinkUrl",
                "deeplinkURL",
                "bookingUrl",
                "url",
                "webUrl",
                "websiteUrl",
            ):
                v = data.get(key)
                if isinstance(v, str) and v.startswith("http"):
                    return v

            hotel = data.get("hotel")
            if isinstance(hotel, dict):
                for key in ("deeplinkUrl", "bookingUrl", "url", "webUrl", "websiteUrl"):
                    v = hotel.get(key)
                    if isinstance(v, str) and v.startswith("http"):
                        return v

    hid = h.get("hotelId")
    if hid:
        return f"https://www.priceline.com/relax/at/{hid}"

    return None
