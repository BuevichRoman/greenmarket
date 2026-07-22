import uuid

from sqlalchemy.orm import Session

from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_photo_repository import SellerProductPhotoRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.mapping.mapper import Mapper
from app.parsing.google_sheets_parser import GoogleSheetsParser
from app.platform.photo_gateway import PhotoGateway
from app.platform.seller_gateway import SellerGateway
from app.publication.errors import TestModeUnavailableError
from app.publication.hash_calculator import HashCalculator
from app.publication.mode import read_mode
from app.publication.publication_result import PublicationResult
from app.publication.publication_service import PublicationService
from app.validation.business_validator import BusinessValidator
from app.validation.errors import ValidationResult
from app.validation.semantic_validator import SemanticValidator
from app.validation.structure_validator import StructureValidator
from app.validation.validator import Validator


class PublicationValidationError(Exception):
    """Каталог не прошёл Structure/Semantic/Business Validation."""

    def __init__(self, validation_result: ValidationResult):
        self.validation_result = validation_result
        super().__init__("Публикация отклонена: ошибки валидации")


class PublicationUseCase:
    """Оркестрирует Publication Pipeline (CR-001, docs/04-services/Publication_Service.md):
    GoogleSheetsParser → HashCalculator → Validator → Mapper → PublicationService.
    PublicationKey/CatalogHash генерируются здесь — не читаются из документа.

    Mode=TEST/PROD (лист _System, app/publication/mode.py) решает, в какую БД
    пишет PublicationService — известно только после парсинга, поэтому
    Validator/PublicationService строятся не в __init__, а внутри publish(),
    когда сессия уже выбрана.
    """

    def __init__(self, session: Session, test_session: Session | None = None, parser_resource=None):
        self.parser = GoogleSheetsParser(resource=parser_resource)
        self.hash_calculator = HashCalculator()
        self.mapper = Mapper()
        self.session = session
        self.test_session = test_session

    def publish(self, spreadsheet_id: str, *, seller_id: int, published_by: int) -> PublicationResult:
        workbook = self.parser.parse(spreadsheet_id)
        mode = read_mode(workbook)
        session = self._resolve_session(mode)

        catalog_hash = self.hash_calculator.compute(workbook)
        validator = Validator(
            StructureValidator(),
            SemanticValidator(ProductGroupRepository(session), ProductRepository(session), PhotoGateway(session)),
            BusinessValidator(),
        )
        validation_result = validator.validate(workbook)
        if not validation_result.is_valid:
            raise PublicationValidationError(validation_result)

        model = self.mapper.map(workbook, validation_result, seller_id)
        publication_key = str(uuid.uuid4())

        publication_service = PublicationService(
            session=session,
            seller_gateway=SellerGateway(session),
            seller_product_repository=SellerProductRepository(session),
            product_repository=ProductRepository(session),
            product_group_repository=ProductGroupRepository(session),
            catalog_publication_repository=CatalogPublicationRepository(session),
            seller_product_photo_repository=SellerProductPhotoRepository(session),
        )
        return publication_service.publish(
            model, published_by, publication_key=publication_key, catalog_hash=catalog_hash, mode=mode
        )

    def _resolve_session(self, mode: str) -> Session:
        if mode != "test":
            return self.session
        if self.test_session is None:
            raise TestModeUnavailableError(
                "Рабочая книга запросила Mode=TEST, но тестовая БД не настроена на этом окружении"
            )
        return self.test_session
