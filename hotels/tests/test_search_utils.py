from handlers.search import extract_hotel_name, extract_address, _to_dt
from datetime import date, datetime


def test_extract_hotel_name_from_name():
    assert extract_hotel_name({"name": "Grand Hotel"}) == "Grand Hotel"


def test_extract_hotel_name_fallback():
    assert extract_hotel_name({}) == "Без названия"


def test_extract_address_string():
    assert extract_address({"address": "Baker St 221B"}) == "Baker St 221B"


def test_extract_address_dict():
    hotel = {"address": {"addressLine1": "Main St", "city": "London"}}
    assert "Main St" in extract_address(hotel)
    assert "London" in extract_address(hotel)


def test_to_dt_from_date():
    d = date(2026, 9, 1)
    result = _to_dt(d)
    assert isinstance(result, datetime)
    assert result == datetime(2026, 9, 1, 0, 0, 0)


def test_to_dt_from_datetime():
    dt = datetime(2026, 9, 1, 12, 30)
    assert _to_dt(dt) is dt  # тот же объект, без копирования
