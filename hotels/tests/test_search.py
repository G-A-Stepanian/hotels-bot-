from datetime import date

from handlers.search import extract_address, extract_hotel_name, parse_date


def test_parse_date_accepts_iso_format() -> None:
    assert parse_date("2026-09-10") == date(2026, 9, 10)


def test_parse_date_rejects_invalid_value() -> None:
    assert parse_date("10.09.2026") is None
    assert parse_date("not-a-date") is None


def test_extract_hotel_name_uses_name() -> None:
    hotel = {"name": "Woodlands Lodge Ilford"}

    assert extract_hotel_name(hotel) == "Woodlands Lodge Ilford"


def test_extract_hotel_name_has_fallback() -> None:
    assert extract_hotel_name({}) == "Без названия"


def test_extract_address_from_string() -> None:
    hotel = {"address": "123 Main Street, London"}

    assert extract_address(hotel) == "123 Main Street, London"


def test_extract_address_from_nested_object() -> None:
    hotel = {
        "address": {
            "addressLine1": "123 Main Street",
            "city": "London",
            "country": "GB",
        }
    }

    assert extract_address(hotel) == "123 Main Street, London, GB"


def test_extract_address_fallback() -> None:
    assert extract_address({}) == "не указан"
