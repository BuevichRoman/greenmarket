import uuid

from sqlalchemy.orm import Session

from app.infrastructure.repositories.catalog_publication_repository import CatalogPublicationRepository
from app.infrastructure.repositories.product_group_repository import ProductGroupRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.infrastructure.repositories.seller_product_repository import SellerProductRepository
from app.mapping.mapper import Mapper
from app.parsing.google_sheets_parser import GoogleSheetsParser
from app.platform.seller_gateway import SellerGateway
from app.publication.hash_calculator import HashCalculator
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
    """

    def __init__(self, session: Session, parser_resource=None):
        self.parser = GoogleSheetsParser(resource=parser_resource)
        self.hash_calculator = HashCalculator()
        self.mapper = Mapper()
        self.validator = Validator(
            StructureValidator(),
            SemanticValidator(ProductGroupRepository(session), ProductRepository(session)),
            BusinessValidator(),
        )
        self.publication_service = PublicationService(
            session=session,
            seller_gateway=SellerGateway(session),
            seller_product_repository=SellerProductRepository(session),
            product_repository=ProductRepository(session),
            product_group_repository=ProductGroupRepository(session),
            catalog_publication_repository=CatalogPublicationRepository(session),
        )

    def publish(self, spreadsheet_id: str, *, seller_id: int, published_by: int) -> PublicationResult:
        workbook = self.parser.parse(spreadsheet_id)
        catalog_hash = self.hash_calculator.compute(workbook)

        validation_result = self.validator.validate(workbook)
        if not validation_result.is_valid:
            raise PublicationValidationError(validation_result)

        model = self.mapper.map(workbook, validation_result, seller_id)
        publication_key = str(uuid.uuid4())

        return self.publication_service.publish(
            model, published_by, publication_key=publication_key, catalog_hash=catalog_hash
        )
