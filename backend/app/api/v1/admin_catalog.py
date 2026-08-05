"""Admin API справочника: ProductGroup и Product (Admin_MVP.md, экраны 1 и 2).

Отдельный роутер от app/api/v1/admin.py: там аутентификация администратора и
продавцы, здесь — единый каталог платформы. Аутентификация общая.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.admin.admin_access import AdminAccess
from app.api.v1.admin import admin_access_denied, get_admin_access
from app.api.v1.admin_schemas import (
    ProductCreateRequest,
    ProductGroupCreateRequest,
    ProductGroupListResponse,
    ProductGroupSummary,
    ProductGroupUpdateRequest,
    ProductListResponse,
    ProductSummary,
    ProductUpdateRequest,
)
from app.api.v1.schemas import error_response
from app.infrastructure.database import get_session
from app.infrastructure.models import Product, ProductGroup
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def group_not_found(group_id: int) -> JSONResponse:
    return error_response(404, "PRODUCT_GROUP_NOT_FOUND", f"Товарная группа {group_id} не найдена")


def _group_summary(group: ProductGroup, product_count: int) -> ProductGroupSummary:
    return ProductGroupSummary(
        id=group.id,
        parent_id=group.parent_id,
        name=group.name,
        sort_order=group.sort_order,
        is_active=group.is_active,
        product_count=product_count,
    )


def _product_summary(product: Product, group_name: str, offer_count: int) -> ProductSummary:
    return ProductSummary(
        id=product.id,
        product_group_id=product.product_group_id,
        group_name=group_name,
        name=product.name,
        description=product.description,
        is_active=product.is_active,
        offer_count=offer_count,
    )


@router.get("/product-groups", response_model=ProductGroupListResponse)
def list_product_groups(
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> ProductGroupListResponse | JSONResponse:
    """Плоский список групп с parent_id — дерево собирает интерфейс. Включая
    деактивированные: скрытую группу иначе нечем вернуть в работу."""
    if access is None:
        return admin_access_denied()

    rows = ProductGroupRepository(session).list_all_with_product_count()
    return ProductGroupListResponse(groups=[_group_summary(group, count) for group, count in rows])


@router.post("/product-groups", response_model=ProductGroupSummary, status_code=201)
def create_product_group(
    request: ProductGroupCreateRequest,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> ProductGroupSummary | JSONResponse:
    if access is None:
        return admin_access_denied()

    repository = ProductGroupRepository(session)
    if request.parent_id is not None and repository.find_by_id(request.parent_id) is None:
        return group_not_found(request.parent_id)

    group = repository.create(name=request.name, parent_id=request.parent_id, sort_order=request.sort_order)
    session.commit()
    return _group_summary(group, 0)


@router.put("/product-groups/{group_id}", response_model=ProductGroupSummary)
def update_product_group(
    group_id: int,
    request: ProductGroupUpdateRequest,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> ProductGroupSummary | JSONResponse:
    if access is None:
        return admin_access_denied()

    repository = ProductGroupRepository(session)
    group = repository.find_by_id(group_id)
    if group is None:
        return group_not_found(group_id)

    fields = request.model_fields_set
    if "parent_id" in fields and request.parent_id is not None:
        if request.parent_id == group_id or repository.is_descendant(group_id, request.parent_id):
            return error_response(
                400,
                "INVALID_PARENT_GROUP",
                "Группу нельзя перенести под саму себя или собственного потомка",
            )
        if repository.find_by_id(request.parent_id) is None:
            return group_not_found(request.parent_id)

    if "parent_id" in fields:
        group.parent_id = request.parent_id
    if request.name is not None:
        group.name = request.name
    if request.sort_order is not None:
        group.sort_order = request.sort_order
    if request.is_active is not None:
        group.is_active = request.is_active

    session.commit()
    return _group_summary(group, repository.count_products(group_id))


@router.get("/products", response_model=ProductListResponse)
def list_products(
    group_id: int | None = None,
    query: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> ProductListResponse | JSONResponse:
    """Справочник для админа: с деактивированными позициями и поиском по имени —
    модератор ищет здесь, к чему привязать позицию продавца."""
    if access is None:
        return admin_access_denied()

    rows, total = ProductRepository(session).list_for_admin(
        group_id=group_id, query=query, page=page, limit=limit
    )
    return ProductListResponse(
        products=[_product_summary(product, group_name, count) for product, group_name, count in rows],
        page=page,
        limit=limit,
        total=total,
    )


@router.post("/products", response_model=ProductSummary, status_code=201)
def create_product(
    request: ProductCreateRequest,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> ProductSummary | JSONResponse:
    if access is None:
        return admin_access_denied()

    group = ProductGroupRepository(session).find_by_id(request.product_group_id)
    if group is None:
        return group_not_found(request.product_group_id)

    product = ProductRepository(session).create(
        product_group_id=request.product_group_id, name=request.name, description=request.description
    )
    session.commit()
    return _product_summary(product, group.name, 0)


@router.put("/products/{product_id}", response_model=ProductSummary)
def update_product(
    product_id: int,
    request: ProductUpdateRequest,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> ProductSummary | JSONResponse:
    """Правка позиции справочника. Удаления нет: Admin_MVP.md не допускает
    удаление Product при связанных SellerProduct — вместо него is_active."""
    if access is None:
        return admin_access_denied()

    repository = ProductRepository(session)
    product = repository.find_by_id(product_id)
    if product is None:
        return error_response(404, "PRODUCT_NOT_FOUND", f"Товарная позиция {product_id} не найдена")

    group_repository = ProductGroupRepository(session)
    if request.product_group_id is not None:
        if group_repository.find_by_id(request.product_group_id) is None:
            return group_not_found(request.product_group_id)
        product.product_group_id = request.product_group_id

    if request.name is not None:
        product.name = request.name
    if "description" in request.model_fields_set:
        product.description = request.description
    if request.is_active is not None:
        product.is_active = request.is_active

    session.commit()
    group = group_repository.find_by_id(product.product_group_id)
    return _product_summary(product, group.name, repository.count_offers(product_id))
