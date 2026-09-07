from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.publications import get_seller_access_resolver
from app.api.v1.schemas import PublicationResponse, error_response
from app.api.v1.seller_catalog_schemas import (
    ProductSuggestion,
    ProductSuggestListResponse,
    SellerCatalogDetail,
    SellerCatalogItem,
    SellerCatalogListResponse,
    SellerProductGroupListResponse,
    SellerProductGroupOption,
    SellerProductCreateRequest,
    SellerProductPhotoResponse,
    SellerProductUpdateRequest,
)
from app.api.v1.seller_schemas import (
    MarketListResponse,
    MarketOption,
    SellerActivationRequest,
    SellerActivationResponse,
    SellerProfileResponse,
    SellerProfileUpdateRequest,
    SellerProfileUpdateResponse,
    SellerStatusResponse,
)
from app.application.seller_catalog_use_case import (
    DuplicateSellerSkuError,
    ProductNotSelectableError,
    SellerCatalogUseCase,
    SellerProductNotFoundError,
)
from app.infrastructure.database import get_session
from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.core.config import settings
from app.infrastructure.repositories.market_repository import MarketRepository
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import (
    SellerProductRepository,
    UnknownSortFieldError,
)
from app.api.v1.photos import get_photo_storage
from app.platform.photo_gateway import PhotoGateway
from app.platform.photo_storage import PhotoStorage, build_photo_url
from app.platform.photo_upload import PhotoUploadError, read_validated_photo
from app.platform.seller_gateway import SellerGateway
from app.profile.errors import ProfileValidationError, SellerNotFoundError
from app.profile.seller_profile_service import SellerProfileService
from app.infrastructure.repositories.seller_product_photo_repository import SellerProductPhotoRepository
from app.publication.seller_access import SellerAccess, resolve_seller_access
from app.publication.seller_activation import activate_seller
from app.publication.seller_catalog_publisher import SellerCatalogPublisher

router = APIRouter(prefix="/api/v1/seller", tags=["seller"])

_BEARER_PREFIX = "bearer "


def get_seller_bearer_access(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> SellerAccess | None:
    """Продавец из заголовка `Authorization: Bearer <token>`.

    Новый контур Seller Catalog API токен в query-строке не принимает: она
    целиком попадает в access.log nginx. Прежние эндпоинты раздела оставлены
    как есть — их клиенты (Apps Script, Seller Cabinet) переводятся на
    заголовок отдельной задачей.
    """
    if authorization is None or not authorization.lower().startswith(_BEARER_PREFIX):
        return None
    return resolve_seller_access(authorization[len(_BEARER_PREFIX):].strip(), session)


def seller_access_denied() -> JSONResponse:
    # 401, а не 403 как в прежних эндпоинтах раздела: с Bearer запрос без
    # действительного заголовка не аутентифицирован, а не «аутентифицирован, но
    # не имеет прав» (ТЗ Seller Catalog API, раздел 10).
    return error_response(401, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")


@router.get("/catalog", response_model=SellerStatusResponse)
def get_seller_catalog(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerStatusResponse | JSONResponse:
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    status = SellerGateway(session).get_status(access.seller_id)
    if status is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {access.seller_id} не найден")

    publications = CatalogPublicationRepository(session).list_by_seller(access.seller_id)
    last_published_at = publications[0].published_at if publications else None

    return SellerStatusResponse(
        seller_id=access.seller_id,
        is_active=status.is_active,
        current_catalog_version=status.current_catalog_version,
        published_product_count=SellerProductRepository(session).count_published(access.seller_id),
        last_published_at=last_published_at,
    )


@router.post("/activate", response_model=SellerActivationResponse)
def activate(
    request: SellerActivationRequest,
    session: Session = Depends(get_session),
) -> SellerActivationResponse | JSONResponse:
    access_token = activate_seller(request.activation_code, spreadsheet_id=request.spreadsheet_id, session=session)
    if access_token is None:
        return error_response(400, "INVALID_ACTIVATION_CODE", "Код активации недействителен.")

    session.commit()
    return SellerActivationResponse(access_token=access_token)


def _profile_response(seller_id: int, *, session: Session) -> SellerProfileResponse | JSONResponse:
    # find_list_row, а не get_status: имя и is_active приезжают одной строкой,
    # а имя из токена брать нельзя — оно есть только у этого вызывающего.
    seller = SellerGateway(session).find_list_row(seller_id)
    if seller is None:
        return error_response(404, "SELLER_NOT_FOUND", f"Продавец {seller_id} не найден")

    service = SellerProfileService(session)
    profile = service.read(seller_id)
    return SellerProfileResponse(
        seller_id=seller_id,
        name=seller.name,
        status="ACTIVE" if seller.is_active else "INACTIVE",
        suggested_phone=service.suggested_phone(seller_id),
        **profile,
    )


@router.get("/markets", response_model=MarketListResponse)
def list_markets(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> MarketListResponse | JSONResponse:
    """Справочник мест торговли для выпадающего списка в форме профиля —
    и рынки, и отдельно стоящие лавки.

    Только открытые точки: закрытую выбрать нельзя, её и не предлагаем.
    Токен требуется, как и у остального Seller API, — справочник живёт в
    кабинете продавца, а не в публичном каталоге.
    """
    if resolve_access(access_token) is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    markets = MarketRepository(session).list_active()
    return MarketListResponse(
        markets=[MarketOption(id=m.id, name=m.name, type=m.type, address=m.address) for m in markets]
    )


@router.get("/profile", response_model=SellerProfileResponse)
def get_seller_profile(
    access_token: str,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerProfileResponse | JSONResponse:
    access = resolve_access(access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")
    return _profile_response(access.seller_id, session=session)


@router.put("/profile", response_model=SellerProfileUpdateResponse)
def update_seller_profile(
    request: SellerProfileUpdateRequest,
    session: Session = Depends(get_session),
    resolve_access=Depends(get_seller_access_resolver),
) -> SellerProfileUpdateResponse | JSONResponse:
    access = resolve_access(request.access_token)
    if access is None:
        return error_response(403, "SELLER_ACCESS_DENIED", "Токен доступа продавца недействителен")

    try:
        changed = SellerProfileService(session).apply(
            access.seller_id,
            request.changed_values(),
            # published_by — платформенный users.id_user продавца: поле названо
            # по первому потребителю, публикациям, но хранит именно id пользователя.
            author_user_id=access.published_by,
            author_role="SELLER",
        )
    except SellerNotFoundError as exc:
        return error_response(404, "SELLER_NOT_FOUND", str(exc))
    except ProfileValidationError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    session.commit()
    return SellerProfileUpdateResponse(changed=changed)


@router.post("/catalog/publish", response_model=PublicationResponse)
def publish_catalog(
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
) -> PublicationResponse | JSONResponse:
    """Публикация текущего состояния каталога продавца.

    Тела у запроса нет: публикуется то, что уже лежит в каталоге, а правки
    приходят раньше — отдельными запросами. Отсутствие товара в запросе не
    означает и не может означать снятие с витрины (ТЗ, раздел 8).
    """
    if access is None:
        return seller_access_denied()

    publisher = SellerCatalogPublisher(
        session=session,
        seller_gateway=SellerGateway(session),
        seller_product_repository=SellerProductRepository(session),
        seller_product_photo_repository=SellerProductPhotoRepository(session),
        catalog_publication_repository=CatalogPublicationRepository(session),
    )
    result = publisher.publish(access.seller_id, published_by=access.published_by)

    return PublicationResponse(
        success=True,
        publication_id=result.publication_id,
        created=result.created_count,
        updated=result.updated_count,
        deactivated=result.deactivated_count,
        message="Каталог опубликован",
        mode=result.mode,
        hidden_no_photo=result.hidden_no_photo,
    )


_MAX_PAGE_SIZE = 100
_MAX_SUGGEST_LIMIT = 50


def _catalog_item_fields(row, product, group) -> dict:
    return {
        "id": row.id,
        "product_id": row.product_id,
        # Эталонного имени и категории у несопоставленной позиции не
        # существует — отдаём пусто, а не выдуманную заглушку.
        "product_name": product.name if product is not None else None,
        "product_group_id": group.id if group is not None else None,
        "product_group_name": group.name if group is not None else None,
        "seller_name": row.seller_name,
        "price": row.price,
        "stock": row.stock,
        "unit": row.unit,
        "description": row.description,
        "origin_country": row.origin_country,
        "supply_date": row.supply_date,
        "seller_sku": row.seller_sku,
        "is_published": bool(row.is_published),
        "moderation_status": row.moderation_status,
        "updated_at": row.updated_at,
    }


def _resolve_group_ids(product_group_id: int | None, session: Session) -> list[int] | None:
    """Категория означает ветку целиком — то же правило, что в каталоге
    покупателя: товары висят и на листьях, и на корнях."""
    if product_group_id is None:
        return None
    subtrees = ProductGroupRepository(session).subtree_ids_by_group([product_group_id])
    return subtrees.get(product_group_id, [product_group_id])


@router.get("/products", response_model=SellerCatalogListResponse)
def list_seller_products(
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=_MAX_PAGE_SIZE),
    search: str | None = None,
    product_group_id: int | None = None,
    is_published: bool | None = None,
    moderation_status: str | None = None,
    sort: str | None = None,
) -> SellerCatalogListResponse | JSONResponse:
    """Каталог продавца целиком — включая непромодерированное и снятое с витрины.

    Это не покупательская выборка: продавцу нужно видеть и то, чего покупатель
    не видит, иначе позиция, ожидающая модерации, для него просто исчезает.
    """
    if access is None:
        return seller_access_denied()

    try:
        rows, total = SellerProductRepository(session).list_for_seller_admin(
            access.seller_id,
            page=page,
            page_size=page_size,
            search=search,
            group_ids=_resolve_group_ids(product_group_id, session),
            is_published=is_published,
            moderation_status=moderation_status,
            sort=sort,
        )
    except UnknownSortFieldError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    return SellerCatalogListResponse(
        items=[SellerCatalogItem(**_catalog_item_fields(row, product, group)) for row, product, group in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/products/suggest", response_model=ProductSuggestListResponse)
def suggest_products(
    q: str,
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
    product_group_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=_MAX_SUGGEST_LIMIT),
) -> ProductSuggestListResponse | JSONResponse:
    """Позиции справочника для выбора товарной позиции.

    Объявлен раньше `/products/{seller_product_id}`: иначе «suggest» уехало бы
    в путь как идентификатор и вернуло бы 422 вместо подсказок.
    """
    if access is None:
        return seller_access_denied()
    if not q.strip():
        return error_response(422, "VALIDATION_ERROR", "Параметр 'q' не может быть пустым")

    found = ProductRepository(session).suggest_for_seller(
        search=q, group_ids=_resolve_group_ids(product_group_id, session), limit=limit
    )
    return ProductSuggestListResponse(
        items=[
            ProductSuggestion(
                id=product.id, name=product.name, product_group_id=group.id, product_group_name=group.name
            )
            for product, group in found
        ]
    )


@router.get("/products/{seller_product_id}", response_model=SellerCatalogDetail)
def get_seller_product(
    seller_product_id: int,
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
) -> SellerCatalogDetail | JSONResponse:
    """Одна позиция каталога вместе с фотографиями — состав формы редактирования.

    Чужая позиция неотличима от несуществующей: иначе перебором идентификаторов
    выясняется состав чужого каталога.
    """
    if access is None:
        return seller_access_denied()

    detail = _detail_or_none(session, access.seller_id, seller_product_id)
    if detail is None:
        return error_response(404, "SELLER_PRODUCT_NOT_FOUND", "Позиция каталога не найдена")
    return detail


@router.get("/product-groups", response_model=SellerProductGroupListResponse)
def list_seller_product_groups(
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
) -> SellerProductGroupListResponse | JSONResponse:
    """Только активные категории: снятую продавцу предлагать незачем, товар в
    ней всё равно не станет видимым."""
    if access is None:
        return seller_access_denied()

    return SellerProductGroupListResponse(
        items=[
            SellerProductGroupOption(
                id=group.id, parent_id=group.parent_id, name=group.name, sort_order=group.sort_order
            )
            for group in ProductGroupRepository(session).list_active()
        ]
    )


def _detail_or_none(session: Session, seller_id: int, seller_product_id: int) -> SellerCatalogDetail | None:
    """Карточка перечитывается из базы, а не собирается из тела запроса: так
    ответ на создание и на правку описывает действительное состояние строки,
    включая выведенный статус модерации."""
    found = SellerProductRepository(session).find_for_seller_admin(seller_id, seller_product_id)
    if found is None:
        return None
    row, product, group = found
    keys = PhotoGateway(session).list_by_seller_products([row.id]).get(row.id, [])
    photos = [
        build_photo_url(
            key, bucket=settings.s3_bucket, region=settings.s3_region, public_base_url=settings.s3_public_base_url
        )
        for key in keys
    ]
    return SellerCatalogDetail(**_catalog_item_fields(row, product, group), photos=photos)


@router.post("/products", response_model=SellerCatalogDetail, status_code=201)
def create_seller_product(
    request: SellerProductCreateRequest,
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
) -> SellerCatalogDetail | JSONResponse:
    """Завести позицию в каталоге продавца.

    Статус модерации не принимается и не выбирается — он выводится из товарной
    позиции: выбрана существующая активная позиция значит RESOLVED, не выбрана
    — WAIT_PRODUCT. На витрину новая позиция сама не выходит.
    """
    if access is None:
        return seller_access_denied()

    try:
        created = SellerCatalogUseCase(session).create(access.seller_id, request.model_dump())
    except ProductNotSelectableError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))
    except DuplicateSellerSkuError as exc:
        return error_response(409, "SELLER_SKU_ALREADY_EXISTS", str(exc))

    session.commit()
    return _detail_or_none(session, access.seller_id, created.id)


@router.patch("/products/{seller_product_id}", response_model=SellerCatalogDetail)
def update_seller_product(
    seller_product_id: int,
    request: SellerProductUpdateRequest,
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
) -> SellerCatalogDetail | JSONResponse:
    """Частичное изменение позиции: правятся только присланные ключи.

    Видимость этим запросом не меняется — товар выходит на витрину публикацией,
    а не сохранением карточки.
    """
    if access is None:
        return seller_access_denied()

    nulled = request.nulled_non_nullable()
    if nulled:
        return error_response(422, "VALIDATION_ERROR", f"Поля нельзя очистить: {', '.join(nulled)}")

    try:
        updated = SellerCatalogUseCase(session).update(access.seller_id, seller_product_id, request.changes())
    except SellerProductNotFoundError:
        return error_response(404, "SELLER_PRODUCT_NOT_FOUND", "Позиция каталога не найдена")
    except ProductNotSelectableError as exc:
        return error_response(422, "VALIDATION_ERROR", str(exc))
    except DuplicateSellerSkuError as exc:
        return error_response(409, "SELLER_SKU_ALREADY_EXISTS", str(exc))

    session.commit()
    return _detail_or_none(session, access.seller_id, updated.id)


@router.post("/products/{seller_product_id}/photos", response_model=SellerProductPhotoResponse, status_code=201)
def upload_seller_product_photo(
    seller_product_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    access: SellerAccess | None = Depends(get_seller_bearer_access),
    storage=Depends(get_photo_storage),
) -> SellerProductPhotoResponse | JSONResponse:
    """Загрузить фотографию и сразу привязать её к позиции каталога.

    Одним запросом, а не двумя: без привязки Seller Admin не может довести
    новый товар до витрины — товар без фотографии покупателю не показывается,
    а связать фотографию с товаром вне рабочей книги до сих пор было нечем.

    Правила приёма файла те же, что у загрузки из книги, — общий модуль
    `photo_upload`, чтобы отклонённое в одном интерфейсе не проходило в другом.
    """
    if access is None:
        return seller_access_denied()

    owned = SellerProductRepository(session).find_for_seller_admin(access.seller_id, seller_product_id)
    if owned is None:
        # Проверка владения раньше чтения файла: чужой товар не должен успевать
        # положить байты в S3.
        return error_response(404, "SELLER_PRODUCT_NOT_FOUND", "Позиция каталога не найдена")

    try:
        file_bytes = read_validated_photo(file)
    except PhotoUploadError as exc:
        return error_response(exc.status_code, exc.code, exc.message)

    photo_storage = storage or PhotoStorage(
        bucket=settings.s3_bucket, region=settings.s3_region, endpoint_url=settings.s3_endpoint_url or None
    )
    s3_key = photo_storage.upload(file_bytes, file.content_type)
    photo_id = PhotoGateway(session).create(s3_key=s3_key, seller_id=access.seller_id)
    sort_order = SellerProductPhotoRepository(session).append(seller_product_id, photo_id)
    session.commit()

    return SellerProductPhotoResponse(
        seller_product_id=seller_product_id,
        photo_id=photo_id,
        url=build_photo_url(
            s3_key, bucket=settings.s3_bucket, region=settings.s3_region, public_base_url=settings.s3_public_base_url
        ),
        sort_order=sort_order,
    )
