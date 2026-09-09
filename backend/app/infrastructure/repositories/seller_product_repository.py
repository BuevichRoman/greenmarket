from datetime import date, datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.infrastructure.models import Product, ProductGroup, SellerProduct
from app.infrastructure.repositories.name_search import LIKE_ESCAPE, name_search_patterns


def moderation_status_for(product_id: int | None) -> str:
    """Модерация Stage 1 — классификация: очередь модерации состоит из
    предложений без связи с Product (docs/02-domain/Catalog_Model.md,
    docs/05-ui/Admin_MVP.md). Отсюда инвариант: WAIT_PRODUCT ⟺ product_id IS NULL.

    Раньше статус жёстко ставился в WAIT_PRODUCT всем новым строкам, включая те,
    где продавец выбрал позицию из справочника корректно — статус существовал,
    но ничего не значил.
    """
    return "WAIT_PRODUCT" if product_id is None else "RESOLVED"



SELLER_ADMIN_SORT_FIELDS = {
    "id": SellerProduct.id,
    "seller_name": SellerProduct.seller_name,
    "price": SellerProduct.price,
    "stock": SellerProduct.stock,
    "updated_at": SellerProduct.updated_at,
}


class UnknownSortFieldError(ValueError):
    """Клиент попросил сортировку по полю, которого сервер не разрешает."""


def parse_seller_admin_sort(sort: str | None) -> tuple[object, bool]:
    """`sort` → (колонка, по убыванию ли). Ведущий минус означает убывание.

    Список полей закрыт и задан сервером: сортировка по произвольной колонке
    открывала бы наружу и внутренние поля модерации, и порядок, который потом
    нечем поддерживать индексами.

    Без параметра — свежие первыми: продавец возвращается в каталог, чтобы
    посмотреть то, что только что правил.
    """
    if not sort:
        return SellerProduct.updated_at, True
    descending = sort.startswith("-")
    name = sort[1:] if descending else sort
    column = SELLER_ADMIN_SORT_FIELDS.get(name)
    if column is None:
        raise UnknownSortFieldError(
            f"Сортировка по '{name}' не поддерживается: {', '.join(sorted(SELLER_ADMIN_SORT_FIELDS))}"
        )
    return column, descending


def _seller_catalog_order(sort: str, sort_dir: str) -> tuple:
    """Порядок каталога продавца.

    Пустая дата поставки уходит в конец в обе стороны: MySQL сам кладёт NULL в
    начало при ASC, а товар без даты не «самый ранний» — он просто без даты.
    Отсюда отдельный первый ключ `supply_date IS NULL`.

    Идентификатор добавляется вызывающим последним и всегда по возрастанию —
    он различает строки с одинаковым значением и не переворачивается вместе с
    направлением, иначе страницы перестали бы складываться в один порядок.
    """
    descending = sort_dir == "desc"
    if sort == "delivery":
        column = SellerProduct.supply_date
        return (column.is_(None), column.desc() if descending else column.asc())
    column = SellerProduct.price if sort == "price" else SellerProduct.seller_name
    return (column.desc() if descending else column.asc(),)


class SellerProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_id(self, seller_product_id: int) -> SellerProduct | None:
        return self.session.get(SellerProduct, seller_product_id)

    def list_by_seller(self, seller_id: int) -> list[SellerProduct]:
        return (
            self.session.query(SellerProduct)
            .filter(SellerProduct.seller_id == seller_id)
            .all()
        )

    def count_published(self, seller_id: int) -> int:
        return (
            self.session.query(SellerProduct)
            .filter(SellerProduct.seller_id == seller_id, SellerProduct.is_published.is_(True))
            .count()
        )

    def list_awaiting_moderation(self, *, page: int, limit: int) -> tuple[list[SellerProduct], int]:
        """Очередь модерации — предложения без связи с Product (Admin_MVP.md,
        экран 3). Фильтр по product_id, а не по moderation_status: статус
        выводится из связи, а не наоборот (см. moderation_status_for)."""
        query = self.session.query(SellerProduct).filter(SellerProduct.product_id.is_(None))
        total = query.count()
        items = (
            query.order_by(SellerProduct.created_at, SellerProduct.id)
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def find_by_idempotency_key(self, seller_id: int, idempotency_key: str) -> SellerProduct | None:
        """Позиция, созданная предыдущей попыткой с тем же ключом.

        Ключ принадлежит паре (продавец, ключ): его генерирует клиент в своей
        книге, и совпадение ключей у двух разных продавцов — их частное дело.
        """
        return (
            self.session.query(SellerProduct)
            .filter(
                SellerProduct.seller_id == seller_id,
                SellerProduct.idempotency_key == idempotency_key,
            )
            .first()
        )

    def _seller_admin_query(self, seller_id: int):
        """Каталог продавца со справочными данными. Join внешний: у новой
        позиции связи со справочником нет по определению."""
        return (
            self.session.query(SellerProduct, Product, ProductGroup)
            .outerjoin(Product, Product.id == SellerProduct.product_id)
            .outerjoin(ProductGroup, ProductGroup.id == Product.product_group_id)
            .filter(SellerProduct.seller_id == seller_id)
        )

    def find_for_seller_admin(
        self, seller_id: int, seller_product_id: int
    ) -> tuple[SellerProduct, "Product | None", "ProductGroup | None"] | None:
        """Одна позиция каталога продавца — или `None`, если её нет **либо** она
        чужая. Два случая намеренно неразличимы: иначе перебором
        идентификаторов выясняется состав чужого каталога.
        """
        return self._seller_admin_query(seller_id).filter(SellerProduct.id == seller_product_id).first()

    def list_for_seller_admin(
        self,
        seller_id: int,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        group_ids: list[int] | None = None,
        is_published: bool | None = None,
        moderation_status: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[tuple[SellerProduct, "Product | None", "ProductGroup | None"]], int]:
        """Каталог продавца для Seller Admin — сам продавец, а не покупатель.

        Отличий от покупательской выборки два, и оба принципиальные. Во-первых,
        видно всё: непромодерированные позиции и снятые с витрины тоже, иначе
        товар, ожидающий модерации, для продавца просто исчезал бы. Во-вторых,
        связь со справочником необязательна — join внешний, у новой позиции
        `product_id` пуст по определению, и эталонное имя с категорией
        возвращаются как `None`.

        Возвращает строки вместе с их позицией справочника и категорией: имя и
        группа приходят оттуда, отдельным запросом на строку их тянуть незачем.
        """
        query = self._seller_admin_query(seller_id)
        if group_ids is not None:
            query = query.filter(Product.product_group_id.in_(group_ids))
        if is_published is not None:
            query = query.filter(SellerProduct.is_published.is_(is_published))
        if moderation_status is not None:
            query = query.filter(SellerProduct.moderation_status == moderation_status)
        for pattern in name_search_patterns(search):
            # Как в каталоге продавца у покупателя: слово может стоять в любом
            # из двух имён. Строка без справочника при этом не теряется —
            # ilike по NULL просто не совпадает.
            query = query.filter(
                or_(
                    SellerProduct.seller_name.ilike(pattern, escape=LIKE_ESCAPE),
                    Product.name.ilike(pattern, escape=LIKE_ESCAPE),
                )
            )

        total = query.count()
        column, descending = parse_seller_admin_sort(sort)
        ordering = column.desc() if descending else column.asc()
        items = (
            # Вторым ключом всегда id: без него строки с одинаковой ценой или
            # одинаковой меткой времени раскладываются по страницам как попало
            # и могут показаться дважды.
            query.order_by(ordering, SellerProduct.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def list_visible_for_seller(
        self,
        seller_id: int,
        *,
        group_ids: list[int] | None = None,
        search: str | None = None,
        sort: str = "name",
        sort_dir: str = "asc",
    ) -> list[SellerProduct]:
        """Каталог одного продавца для покупателя (REST_API.md,
        `GET /catalog/sellers/{id}/products`).

        Видимость та же, что в общем каталоге: опубликованное предложение
        промодерированной и не снятой из справочника позиции. Поиск, в отличие
        от общего каталога, идёт по обоим именам — внутри каталога продавца
        покупатель ищет то, что видит на экране, включая собственное
        наименование продавца.
        """
        query = (
            self.session.query(SellerProduct)
            .join(Product, Product.id == SellerProduct.product_id)
            .join(ProductGroup, ProductGroup.id == Product.product_group_id)
            .filter(
                SellerProduct.seller_id == seller_id,
                SellerProduct.is_published.is_(True),
                Product.is_active.is_(True),
                # Снятая с работы категория прячет предложение так же, как
                # снятая позиция справочника — то же правило, что в
                # ProductRepository.list_active.
                ProductGroup.is_active.is_(True),
            )
        )
        if group_ids is not None:
            query = query.filter(Product.product_group_id.in_(group_ids))
        for pattern in name_search_patterns(search):
            # Каждое слово ищется в обоих именах сразу: слово из собственного
            # наименования продавца и слово из эталонного вместе тоже должны
            # находить строку — на экране покупатель видит их рядом.
            query = query.filter(
                or_(
                    SellerProduct.seller_name.ilike(pattern, escape=LIKE_ESCAPE),
                    Product.name.ilike(pattern, escape=LIKE_ESCAPE),
                )
            )
        return query.order_by(*_seller_catalog_order(sort, sort_dir), SellerProduct.id).all()

    def list_published_for_products(self, product_ids: list[int]) -> list[SellerProduct]:
        if not product_ids:
            return []
        return (
            self.session.query(SellerProduct)
            .filter(
                SellerProduct.product_id.in_(product_ids),
                SellerProduct.is_published.is_(True),
            )
            .order_by(SellerProduct.price, SellerProduct.id)
            .all()
        )

    def create(
        self,
        *,
        seller_id: int,
        product_id: int | None,
        seller_name: str,
        price: float,
        stock: float,
        unit: str,
        description: str | None,
        is_published: bool,
        origin_country: str | None = None,
        supply_date: date | None = None,
        seller_sku: str | None = None,
        idempotency_key: str | None = None,
    ) -> SellerProduct:
        now = datetime.now(timezone.utc)
        seller_product = SellerProduct(
            seller_id=seller_id,
            product_id=product_id,
            seller_name=seller_name,
            price=price,
            stock=stock,
            unit=unit,
            description=description,
            origin_country=origin_country,
            supply_date=supply_date,
            seller_sku=seller_sku,
            idempotency_key=idempotency_key,
            version=1,
            is_published=is_published,
            moderation_status=moderation_status_for(product_id),
            created_at=now,
            updated_at=now,
        )
        self.session.add(seller_product)
        self.session.flush()
        return seller_product
