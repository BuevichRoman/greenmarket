from app.infrastructure.repositories.product_repository import ProductRepository


def test_find_by_id_returns_seeded_product(session):
    """Интеграционный тест на реальной базе — без mock, как в ТЗ PR-002.

    Ищем товар по имени (без захардкоженных id, см. database/seeders/002_products.sql),
    затем проверяем find_by_id() тем же id.
    """
    repo = ProductRepository(session)

    orange = repo.find_by_name("Апельсин")
    assert orange is not None

    found = repo.find_by_id(orange.id)
    assert found is not None
    assert found.id == orange.id
    assert found.name == "Апельсин"


def test_find_by_id_returns_none_for_missing_product(session):
    repo = ProductRepository(session)
    assert repo.find_by_id(999_999) is None
