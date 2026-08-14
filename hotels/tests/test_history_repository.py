import json

from database.models import SearchHistory


def test_results_property_deserializes_json() -> None:
    history = SearchHistory(
        results_json=json.dumps(
            [{"name": "Test Hotel", "price": 100}],
            ensure_ascii=False,
        )
    )

    assert history.results == [{"name": "Test Hotel", "price": 100}]


def test_set_results_serializes_json() -> None:
    history = SearchHistory()
    hotels = [{"name": "Отель", "price": 100}]

    history.set_results(hotels)

    assert json.loads(history.results_json) == hotels
