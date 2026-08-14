from typing import Any

from database.models import SearchHistory, User


class HistoryRepository:
    """Слой доступа к истории поисков пользователя."""

    @staticmethod
    def get_or_create_user(
        telegram_id: int,
        username: str | None,
    ) -> User:
        """Возвращает пользователя и обновляет его username при изменении."""
        user, created = User.get_or_create(
            telegram_id=str(telegram_id),
            defaults={"username": username},
        )

        if not created and username != user.username:
            user.username = username
            user.save()

        return user

    @staticmethod
    def save_search(
        telegram_id: int,
        username: str | None,
        command: str,
        city: str,
        checkin: str,
        checkout: str,
        hotels_limit: int,
        results: list[dict[str, Any]],
    ) -> SearchHistory:
        """Сохраняет успешно завершённый поиск."""
        user = HistoryRepository.get_or_create_user(telegram_id, username)

        history = SearchHistory(
            user=user,
            command=command,
            city=city,
            checkin=checkin,
            checkout=checkout,
            hotels_limit=hotels_limit,
        )
        history.set_results(results)
        history.save()

        return history

    @staticmethod
    def get_recent_searches(
        telegram_id: int,
        limit: int = 10,
    ) -> list[SearchHistory]:
        """Возвращает последние поиски пользователя."""
        return list(
            SearchHistory.select()
            .join(User)
            .where(User.telegram_id == str(telegram_id))
            .order_by(SearchHistory.created_at.desc(), SearchHistory.id.desc())
            .limit(limit)
        )
