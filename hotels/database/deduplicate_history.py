from peewee import fn

from database.models import SearchHistory, db


def remove_duplicates() -> int:
    """Оставляет одну запись из группы полностью одинаковых поисков."""
    db.connect(reuse_if_open=True)

    try:
        duplicates = (
            SearchHistory.select(
                SearchHistory.user,
                SearchHistory.command,
                SearchHistory.city,
                SearchHistory.checkin,
                SearchHistory.checkout,
                SearchHistory.hotels_limit,
                SearchHistory.results_json,
                SearchHistory.created_at,
            )
            .group_by(
                SearchHistory.user,
                SearchHistory.command,
                SearchHistory.city,
                SearchHistory.checkin,
                SearchHistory.checkout,
                SearchHistory.hotels_limit,
                SearchHistory.results_json,
                SearchHistory.created_at,
            )
            .having(fn.COUNT(SearchHistory.id) > 1)
        )

        removed_count = 0

        with db.atomic():
            for item in duplicates:
                records = (
                    SearchHistory.select()
                    .where(
                        (SearchHistory.user == item.user)
                        & (SearchHistory.command == item.command)
                        & (SearchHistory.city == item.city)
                        & (SearchHistory.checkin == item.checkin)
                        & (SearchHistory.checkout == item.checkout)
                        & (SearchHistory.hotels_limit == item.hotels_limit)
                        & (SearchHistory.results_json == item.results_json)
                        & (SearchHistory.created_at == item.created_at)
                    )
                    .order_by(SearchHistory.id)
                )

                ids_to_delete = [record.id for record in records][1:]

                if ids_to_delete:
                    removed_count += (
                        SearchHistory.delete()
                        .where(SearchHistory.id.in_(ids_to_delete))
                        .execute()
                    )

        return removed_count

    finally:
        if not db.is_closed():
            db.close()


if __name__ == "__main__":
    deleted = remove_duplicates()
    print(f"Удалено дубликатов: {deleted}")
