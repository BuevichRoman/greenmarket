from sqlalchemy.orm import Session

from app.infrastructure.models import SellerProfileChange


class SellerProfileChangeRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        *,
        seller_id: int,
        field: str,
        old_value: str | None,
        new_value: str | None,
        author_user_id: int,
        author_role: str,
    ) -> SellerProfileChange:
        change = SellerProfileChange(
            seller_id=seller_id,
            field=field,
            old_value=old_value,
            new_value=new_value,
            author_user_id=author_user_id,
            author_role=author_role,
        )
        self.session.add(change)
        return change

    def list_by_seller(self, seller_id: int) -> list[SellerProfileChange]:
        return (
            self.session.query(SellerProfileChange)
            .filter(SellerProfileChange.seller_id == seller_id)
            .order_by(SellerProfileChange.id.desc())
            .all()
        )

    def _feed_query(self, *, after_id: int | None):
        """Общая выборка ленты — чтобы `list_recent` и `count_recent` не могли
        разъехаться в условии: `total`, посчитанный по другому набору, врал бы
        клиенту про то, есть ли ещё записи."""
        query = self.session.query(SellerProfileChange)
        if after_id is None:
            return query
        return query.filter(SellerProfileChange.id > after_id)

    def list_recent(self, *, limit: int, after_id: int | None = None) -> list[SellerProfileChange]:
        """Лента последних изменений для Admin Cabinet.

        Сортировка по `id`, а не по `created_at`: несколько полей, изменённых
        одним PUT, получают одинаковую метку времени с точностью до секунды, и
        порядок внутри такой пачки был бы неопределённым.

        `after_id` — «что нового с прошлого раза»: клиент запоминает
        максимальный `id` прошлой выдачи. По той же причине курсор именно `id`,
        а не время: по секундной метке пачка из одного PUT неразделима.
        """
        return (
            self._feed_query(after_id=after_id)
            .order_by(SellerProfileChange.id.desc())
            .limit(limit)
            .all()
        )

    def count_recent(self, *, after_id: int | None = None) -> int:
        """Сколько записей всего — без него клиент не отличит полную страницу
        от обрезанной."""
        return self._feed_query(after_id=after_id).count()
