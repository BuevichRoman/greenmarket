import pytest
from sqlalchemy import text

from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.mapping.publication_model import PublicationMetadata, PublicationModel, PublicationProduct
from app.platform.seller_gateway import SellerGateway
from app.publication.errors import DuplicatePublicationError, PublicationConflictError
from app.publication.publication_service import PublicationService


def insert_seller(session, *, name: str, publication_key: str | None = None, catalog_hash: str | None = None) -> int:
    user_id = insert_user(session, name=name)
    return session.execute(
        text(
            "INSERT INTO Seller (user_id, current_publication_key, current_catalog_hash) "
            "VALUES (:user_id, :publication_key, :catalog_hash)"
        ),
        {"user_id": user_id, "publication_key": publication_key, "catalog_hash": catalog_hash},
    ).lastrowid


def insert_user(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_product_group(session, *, name: str) -> int:
    return session.execute(text("INSERT INTO ProductGroup (name) VALUES (:name)"), {"name": name}).lastrowid


def insert_product(session, *, product_group_id: int, name: str) -> int:
    return session.execute(
        text("INSERT INTO Product (product_group_id, name) VALUES (:group_id, :name)"),
        {"group_id": product_group_id, "name": name},
    ).lastrowid


def make_service(session) -> PublicationService:
    return PublicationService(
        session=session,
        seller_gateway=SellerGateway(session),
        seller_product_repository=SellerProductRepository(session),
        product_repository=ProductRepository(session),
        product_group_repository=ProductGroupRepository(session),
        catalog_publication_repository=CatalogPublicationRepository(session),
    )


def make_product(*, seller_product_id=None, seller_name="Ферма А", group="Тестовая группа PublicationService", name=None, price=50.0, unit="кг", stock=5.0, description=None, attributes=None) -> PublicationProduct:
    return PublicationProduct(
        seller_product_id=seller_product_id,
        seller_name=seller_name,
        product_group_name=group,
        product_name=name,
        price=price,
        unit=unit,
        stock=stock,
        description=description,
        attributes=attributes,
    )


def make_model(seller_id: int, products: list[PublicationProduct]) -> PublicationModel:
    return PublicationModel(
        products=products,
        metadata=PublicationMetadata(seller_id=seller_id, template_version="1.0", template_id="template-1"),
    )


def test_publishes_new_catalog_creates_seller_products(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма новая")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    model = make_model(
        seller_id,
        [make_product(seller_name="Ферма А", price=50), make_product(seller_name="Ферма Б", price=80)],
    )

    result = service.publish(model, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")

    assert result.success is True
    assert result.publication_id > 0
    assert (result.created_count, result.updated_count, result.deactivated_count) == (2, 0, 0)

    seller_products = SellerProductRepository(committing_session).list_by_seller(seller_id)
    assert len(seller_products) == 2

    gateway = SellerGateway(committing_session)
    assert gateway.get_current_publication_key(seller_id) == "key-1"
    assert gateway.get_current_catalog_hash(seller_id) == "hash-1"
    assert CatalogPublicationRepository(committing_session).latest_version(seller_id) == 1


def test_publishing_again_updates_changed_seller_product(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма обновление")
    user_id = insert_user(committing_session, name="Admin")
    group_id = insert_product_group(committing_session, name="Тестовая группа PublicationService")
    insert_product(committing_session, product_group_id=group_id, name="Тестовый товар")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(price=50, unit="кг")])
    service.publish(first, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")
    seller_product_id = SellerProductRepository(committing_session).list_by_seller(seller_id)[0].id

    second = make_model(
        seller_id,
        [make_product(seller_product_id=seller_product_id, price=99.5, name="Тестовый товар")],
    )
    result = service.publish(second, published_by=user_id, publication_key="key-2", catalog_hash="hash-2")

    assert (result.created_count, result.updated_count, result.deactivated_count) == (0, 1, 0)
    updated = SellerProductRepository(committing_session).find_by_id(seller_product_id)
    assert float(updated.price) == 99.5
    assert updated.product_id is not None


def test_publishing_alongside_new_product_only_counts_new_one(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма плюс товар")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(seller_name="Ферма А", price=50, unit="кг", stock=5)])
    service.publish(first, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")
    existing_id = SellerProductRepository(committing_session).list_by_seller(seller_id)[0].id

    second = make_model(
        seller_id,
        [
            make_product(seller_product_id=existing_id, seller_name="Ферма А", price=50, unit="кг", stock=5),
            make_product(seller_name="Ферма А", price=10, unit="шт", stock=3),
        ],
    )
    result = service.publish(second, published_by=user_id, publication_key="key-2", catalog_hash="hash-2")

    assert (result.created_count, result.updated_count, result.deactivated_count) == (1, 0, 0)
    assert len(SellerProductRepository(committing_session).list_by_seller(seller_id)) == 2


def test_publishing_catalog_missing_previous_product_deactivates_it(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма удаление")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    first = make_model(
        seller_id,
        [make_product(seller_name="Остаётся", price=10), make_product(seller_name="Пропадёт", price=20)],
    )
    service.publish(first, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")
    remaining, disappearing = SellerProductRepository(committing_session).list_by_seller(seller_id)

    second = make_model(
        seller_id,
        [make_product(seller_product_id=remaining.id, seller_name="Остаётся", price=10)],
    )
    result = service.publish(second, published_by=user_id, publication_key="key-2", catalog_hash="hash-2")

    assert result.deactivated_count == 1
    repository = SellerProductRepository(committing_session)
    assert repository.find_by_id(remaining.id).is_published is True
    assert repository.find_by_id(disappearing.id).is_published is False


def test_conflict_error_rolls_back_all_changes(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма конфликт")
    other_seller_id = insert_seller(committing_session, name="Другая ферма")
    user_id = insert_user(committing_session, name="Admin")
    other_seller_product_id = SellerProductRepository(committing_session).create(
        seller_id=other_seller_id, product_id=None, seller_name="Чужой товар", price=1, stock=1, unit="шт", description=None
    ).id
    service = make_service(committing_session)

    model = make_model(
        seller_id,
        [make_product(seller_name="Новый товар", price=5), make_product(seller_product_id=other_seller_product_id, seller_name="Подмена", price=1)],
    )

    with pytest.raises(PublicationConflictError):
        service.publish(model, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")

    assert SellerProductRepository(committing_session).list_by_seller(seller_id) == []
    assert CatalogPublicationRepository(committing_session).latest_version(seller_id) == 0
    assert SellerGateway(committing_session).get_current_publication_key(seller_id) is None


def test_seller_product_belonging_to_another_seller_is_rejected(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма A")
    other_seller_id = insert_seller(committing_session, name="Ферма Б")
    user_id = insert_user(committing_session, name="Admin")
    other_id = SellerProductRepository(committing_session).create(
        seller_id=other_seller_id, product_id=None, seller_name="Товар Б", price=1, stock=1, unit="шт", description=None
    ).id
    service = make_service(committing_session)

    model = make_model(seller_id, [make_product(seller_product_id=other_id, price=1)])

    with pytest.raises(PublicationConflictError):
        service.publish(model, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")


def test_duplicate_publication_key_is_rejected(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма дубликат")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(price=10)])
    service.publish(first, published_by=user_id, publication_key="dup-key", catalog_hash="hash-1")

    second = make_model(seller_id, [make_product(price=20)])
    with pytest.raises(DuplicatePublicationError):
        service.publish(second, published_by=user_id, publication_key="dup-key", catalog_hash="hash-2")

    assert CatalogPublicationRepository(committing_session).latest_version(seller_id) == 1


def test_product_returning_after_deactivation_is_reactivated(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма реактивация")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(seller_name="A", price=10), make_product(seller_name="B", price=20)])
    service.publish(first, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")
    kept, dropped = SellerProductRepository(committing_session).list_by_seller(seller_id)

    second = make_model(seller_id, [make_product(seller_product_id=kept.id, seller_name="A", price=10)])
    service.publish(second, published_by=user_id, publication_key="key-2", catalog_hash="hash-2")
    assert SellerProductRepository(committing_session).find_by_id(dropped.id).is_published is False

    third = make_model(
        seller_id,
        [
            make_product(seller_product_id=kept.id, seller_name="A", price=10),
            make_product(seller_product_id=dropped.id, seller_name="B", price=99),
        ],
    )
    result = service.publish(third, published_by=user_id, publication_key="key-3", catalog_hash="hash-3")

    reactivated = SellerProductRepository(committing_session).find_by_id(dropped.id)
    assert reactivated.is_published is True
    assert float(reactivated.price) == 99
    assert result.deactivated_count == 0


def test_product_returning_with_no_other_field_changes_is_still_reactivated(committing_session):
    # Отдельно от предыдущего теста: тут при возврате товара не меняется НИ
    # одно поле, кроме is_published — _has_changed обязана сработать сама
    # по факту is_published=False, а не только "заодно" с другой правкой.
    seller_id = insert_seller(committing_session, name="Ферма реактивация без правок")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(seller_name="A", price=10), make_product(seller_name="B", price=20)])
    service.publish(first, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")
    kept, dropped = SellerProductRepository(committing_session).list_by_seller(seller_id)

    second = make_model(seller_id, [make_product(seller_product_id=kept.id, seller_name="A", price=10)])
    service.publish(second, published_by=user_id, publication_key="key-2", catalog_hash="hash-2")

    third = make_model(
        seller_id,
        [
            make_product(seller_product_id=kept.id, seller_name="A", price=10),
            make_product(seller_product_id=dropped.id, seller_name="B", price=20),
        ],
    )
    result = service.publish(third, published_by=user_id, publication_key="key-3", catalog_hash="hash-3")

    assert SellerProductRepository(committing_session).find_by_id(dropped.id).is_published is True
    assert result.updated_count == 1


def test_changing_product_position_resets_moderation_status(committing_session):
    seller_id = insert_seller(committing_session, name="Ферма модерация")
    user_id = insert_user(committing_session, name="Admin")
    group_id = insert_product_group(committing_session, name="Тестовая группа модерации")
    insert_product(committing_session, product_group_id=group_id, name="Тестовый товар модерации")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(group="Тестовая группа модерации", price=10)])
    service.publish(first, published_by=user_id, publication_key="key-1", catalog_hash="hash-1")
    seller_product_id = SellerProductRepository(committing_session).list_by_seller(seller_id)[0].id

    committing_session.execute(
        text(
            "UPDATE SellerProduct SET moderation_status = 'RESOLVED', moderator_id = :user_id, "
            "moderated_at = NOW(), moderation_comment = 'ok' WHERE id = :id"
        ),
        {"user_id": user_id, "id": seller_product_id},
    )

    # Изменилась только цена — moderation_status трогать не должны.
    second = make_model(seller_id, [make_product(seller_product_id=seller_product_id, group="Тестовая группа модерации", price=15)])
    service.publish(second, published_by=user_id, publication_key="key-2", catalog_hash="hash-2")
    unchanged = SellerProductRepository(committing_session).find_by_id(seller_product_id)
    assert unchanged.moderation_status == "RESOLVED"

    # Товарная позиция сменилась (None -> реальный Product) — заявка на классификацию новая.
    third = make_model(
        seller_id,
        [make_product(seller_product_id=seller_product_id, group="Тестовая группа модерации", name="Тестовый товар модерации", price=15)],
    )
    service.publish(third, published_by=user_id, publication_key="key-3", catalog_hash="hash-3")
    reclassified = SellerProductRepository(committing_session).find_by_id(seller_product_id)
    assert reclassified.moderation_status == "WAIT_PRODUCT"
    assert reclassified.moderator_id is None
    assert reclassified.moderated_at is None
    assert reclassified.moderation_comment is None


def test_publish_logs_start_and_success(committing_session, caplog):
    import logging

    seller_id = insert_seller(committing_session, name="Ферма логирование")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)
    model = make_model(seller_id, [make_product(price=10)])

    with caplog.at_level(logging.INFO, logger="app.publication.publication_service"):
        service.publish(model, published_by=user_id, publication_key="log-key-1", catalog_hash="log-hash-1")

    messages = " ".join(r.message for r in caplog.records)
    assert str(seller_id) in messages
    assert "log-key-1" in messages
    assert "created" in messages.lower() or "1" in messages


def test_publish_logs_failure_reason_on_error(committing_session, caplog):
    import logging

    seller_id = insert_seller(committing_session, name="Ферма ошибка лог")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)
    model = make_model(seller_id, [make_product(seller_product_id=999_999, price=10)])

    with caplog.at_level(logging.WARNING, logger="app.publication.publication_service"):
        with pytest.raises(PublicationConflictError):
            service.publish(model, published_by=user_id, publication_key="log-key-err", catalog_hash="log-hash-err")

    assert any("PublicationConflictError" in r.message or "999999" in r.message for r in caplog.records)


def test_integrity_error_race_on_publication_key_is_wrapped(committing_session):
    # Симулирует гонку: app-level exists_with_key() не увидел уже
    # существующий ключ (окно между проверкой и вставкой), но реальный
    # UNIQUE INDEX на CatalogPublication.publication_key всё равно есть —
    # PublicationService обязан вернуть свою ошибку, а не сырой IntegrityError.
    seller_id = insert_seller(committing_session, name="Ферма гонка")
    other_seller_id = insert_seller(committing_session, name="Другая ферма гонка")
    user_id = insert_user(committing_session, name="Admin")

    real_repository = CatalogPublicationRepository(committing_session)
    real_repository.create(seller_id=other_seller_id, version=1, publication_key="raced-key", catalog_hash="h", published_by=user_id)

    class BlindToRaceRepository(CatalogPublicationRepository):
        def exists_with_key(self, publication_key: str) -> bool:
            return False

    service = PublicationService(
        session=committing_session,
        seller_gateway=SellerGateway(committing_session),
        seller_product_repository=SellerProductRepository(committing_session),
        product_repository=ProductRepository(committing_session),
        product_group_repository=ProductGroupRepository(committing_session),
        catalog_publication_repository=BlindToRaceRepository(committing_session),
    )
    model = make_model(seller_id, [make_product(price=10)])

    with pytest.raises(DuplicatePublicationError):
        service.publish(model, published_by=user_id, publication_key="raced-key", catalog_hash="hash-race")

    assert SellerProductRepository(committing_session).list_by_seller(seller_id) == []


def test_identical_catalog_hash_with_fresh_key_short_circuits_without_touching_seller_products(committing_session):
    # Не сам файл резубмиттится (ключ новый — это отдельный, легитимный
    # повторный download шаблона), но контент не изменился: SellerProduct не
    # трогается вообще, хотя журнал/текущий ключ продавца всё равно обновляются.
    seller_id = insert_seller(committing_session, name="Ферма без изменений")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    first = make_model(seller_id, [make_product(price=10)])
    service.publish(first, published_by=user_id, publication_key="key-1", catalog_hash="same-hash")
    before = SellerProductRepository(committing_session).list_by_seller(seller_id)

    second = make_model(seller_id, [make_product(price=999)])
    result = service.publish(second, published_by=user_id, publication_key="key-2", catalog_hash="same-hash")

    assert result.success is True
    assert (result.created_count, result.updated_count, result.deactivated_count) == (0, 0, 0)
    after = SellerProductRepository(committing_session).list_by_seller(seller_id)
    assert [float(p.price) for p in after] == [float(p.price) for p in before]
    assert CatalogPublicationRepository(committing_session).latest_version(seller_id) == 2
    assert SellerGateway(committing_session).get_current_publication_key(seller_id) == "key-2"


def test_republishing_the_exact_same_file_is_rejected_as_duplicate(committing_session):
    # "Re-publish the exact same file" из ТЗ ПР-006 — тот же PublicationKey
    # И тот же CatalogHash (не просто новый ключ с неизменным контентом, как
    # в тесте выше). Интерпретация: replay уже обработанного документа,
    # DuplicatePublicationError, а не тихий no-op.
    seller_id = insert_seller(committing_session, name="Ферма повтор файла")
    user_id = insert_user(committing_session, name="Admin")
    service = make_service(committing_session)

    model = make_model(seller_id, [make_product(price=10)])
    service.publish(model, published_by=user_id, publication_key="same-file-key", catalog_hash="same-file-hash")

    resubmitted = make_model(seller_id, [make_product(price=10)])
    with pytest.raises(DuplicatePublicationError):
        service.publish(resubmitted, published_by=user_id, publication_key="same-file-key", catalog_hash="same-file-hash")

    assert CatalogPublicationRepository(committing_session).latest_version(seller_id) == 1
