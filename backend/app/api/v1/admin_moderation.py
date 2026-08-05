"""Admin API очереди модерации (Admin_MVP.md, экран 3).

Модерация Stage 1 — классификация, а не допуск: очередь состоит из предложений
продавцов без связи с Product, и работа модератора в том, чтобы эту связь
проставить. Статуса «отклонено» нет, статус выводится из самой связи
(см. moderation_status_for, миграция 014).
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin.admin_access import AdminAccess
from app.api.v1.admin import admin_access_denied, get_admin_access
from app.api.v1.admin_schemas import (
    ModerationQueueItem,
    ModerationQueueResponse,
    ModerationResolveRequest,
    ModerationResolveResponse,
)
from app.api.v1.schemas import error_response
from app.core.config import settings
from app.infrastructure.database import get_session
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import (
    SellerProductRepository,
    moderation_status_for,
)
from app.platform.photo_gateway import PhotoGateway
from app.platform.photo_storage import build_photo_url
from app.platform.seller_gateway import SellerGateway

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _photo_urls(s3_keys: list[str]) -> list[str]:
    return [
        build_photo_url(
            key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            public_base_url=settings.s3_public_base_url,
        )
        for key in s3_keys
    ]


@router.get("/moderation", response_model=ModerationQueueResponse)
def list_moderation_queue(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> ModerationQueueResponse | JSONResponse:
    if access is None:
        return admin_access_denied()

    offers, total = SellerProductRepository(session).list_awaiting_moderation(page=page, limit=limit)
    seller_names = SellerGateway(session).list_seller_names([offer.seller_id for offer in offers])
    photos = PhotoGateway(session).list_by_seller_products([offer.id for offer in offers])

    return ModerationQueueResponse(
        items=[
            ModerationQueueItem(
                seller_product_id=offer.id,
                seller_id=offer.seller_id,
                seller_name=seller_names.get(offer.seller_id, ""),
                name=offer.seller_name,
                description=offer.description,
                price=offer.price,
                unit=offer.unit,
                is_published=offer.is_published,
                moderation_status=offer.moderation_status,
                created_at=offer.created_at,
                # Фото — то, по чему модератор понимает, что за товар ему
                # принесли: наименование продавца бывает нечитаемым.
                photos=_photo_urls(photos.get(offer.id, [])),
            )
            for offer in offers
        ],
        page=page,
        limit=limit,
        total=total,
    )


@router.put("/moderation/{seller_product_id}", response_model=ModerationResolveResponse)
def resolve_moderation_item(
    seller_product_id: int,
    request: ModerationResolveRequest,
    access: AdminAccess | None = Depends(get_admin_access),
    session: Session = Depends(get_session),
) -> ModerationResolveResponse | JSONResponse:
    """Привязать предложение продавца к позиции справочника. После привязки
    товар становится частью единого каталога и виден покупателю."""
    if access is None:
        return admin_access_denied()

    repository = SellerProductRepository(session)
    offer = repository.find_by_id(seller_product_id)
    if offer is None:
        return error_response(
            404, "SELLER_PRODUCT_NOT_FOUND", f"Предложение {seller_product_id} не найдено"
        )

    product = ProductRepository(session).find_by_id(request.product_id)
    if product is None:
        return error_response(404, "PRODUCT_NOT_FOUND", f"Товарная позиция {request.product_id} не найдена")
    if not product.is_active:
        # Модерация выглядела бы завершённой, а покупателю товар всё равно не
        # показывался бы: каталог отдаёт только активные позиции.
        return error_response(
            400, "INACTIVE_PRODUCT", f"Товарная позиция {request.product_id} деактивирована"
        )

    offer.product_id = product.id
    offer.moderation_status = moderation_status_for(product.id)
    # moderator_id ссылается на пользователя платформы (users.id_user), а не на
    # Administrator.id — см. fk_SellerProduct_moderator в миграции 005.
    offer.moderator_id = access.user_id
    offer.moderated_at = func.now()
    if request.comment is not None:
        offer.moderation_comment = request.comment

    session.commit()
    session.refresh(offer)
    return ModerationResolveResponse(
        seller_product_id=offer.id,
        product_id=offer.product_id,
        moderation_status=offer.moderation_status,
        moderator_id=offer.moderator_id,
        moderated_at=offer.moderated_at,
        moderation_comment=offer.moderation_comment,
    )
