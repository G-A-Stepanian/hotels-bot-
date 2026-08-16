from datetime import date, datetime

from handlers.search import extract_address, extract_hotel_name, parse_date, _to_dt


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


from handlers.search import format_hotel, pagination_keyboard

# --- format_hotel ---


def test_format_hotel_contains_name() -> None:
    hotel = {"name": "Grand Hotel", "address": "Main St"}
    result = format_hotel(1, hotel)
    assert "Grand Hotel" in result


def test_format_hotel_escapes_html() -> None:
    hotel = {"name": "<script>alert(1)</script>"}
    result = format_hotel(1, hotel)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_format_hotel_shows_index() -> None:
    hotel = {"name": "Test"}
    assert "3." in format_hotel(3, hotel)


# --- pagination_keyboard ---


def test_pagination_keyboard_first_page_no_back_button() -> None:
    kb = pagination_keyboard(page=0, total=5)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "◀️ Назад" not in all_texts
    assert "Вперёд ▶️" in all_texts


def test_pagination_keyboard_last_page_no_forward_button() -> None:
    kb = pagination_keyboard(page=4, total=5)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Вперёд ▶️" not in all_texts
    assert "◀️ Назад" in all_texts


def test_pagination_keyboard_middle_page_has_both_buttons() -> None:
    kb = pagination_keyboard(page=2, total=5)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "◀️ Назад" in all_texts
    assert "Вперёд ▶️" in all_texts


def test_pagination_keyboard_single_result_no_nav() -> None:
    kb = pagination_keyboard(page=0, total=1)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "◀️ Назад" not in all_texts
    assert "Вперёд ▶️" not in all_texts


def test_pagination_keyboard_callback_data_correct() -> None:
    kb = pagination_keyboard(page=2, total=5)
    flat = [btn for row in kb.inline_keyboard for btn in row]
    back = next(b for b in flat if b.text == "◀️ Назад")
    fwd = next(b for b in flat if b.text == "Вперёд ▶️")
    assert back.callback_data == "page:1"
    assert fwd.callback_data == "page:3"


def test_pagination_keyboard_always_has_new_search() -> None:
    kb = pagination_keyboard(page=0, total=1)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "🔁 Новый поиск" in all_texts


def test_to_dt_converts_date_to_datetime() -> None:
    d = date(2026, 9, 1)
    result = _to_dt(d)
    assert isinstance(result, datetime)
    assert result == datetime(2026, 9, 1, 0, 0, 0)


def test_to_dt_leaves_datetime_unchanged() -> None:
    dt = datetime(2026, 9, 1, 12, 30)
    assert _to_dt(dt) is dt
