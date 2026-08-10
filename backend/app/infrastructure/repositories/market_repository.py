from decimal import Decimal

from sqlalchemy.orm import Session

from app.infrastructure.models import Market


class MarketRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_id(self, market_id: int) -> Market | None:
        return self.session.get(Market, market_id)

    def list_active(self) -> list[Market]:
        """Рынки, доступные продавцу для выбора и покупателю для показа."""
        return (
            self.session.query(Market)
            .filter(Market.is_active.is_(True))
            .order_by(Market.name)
            .all()
        )

    def list_all(self) -> list[Market]:
        """Для Admin Cabinet — включая закрытые: закрытый рынок иначе
        невозможно вернуть в работу (то же правило, что у товарных групп)."""
        return self.session.query(Market).order_by(Market.name).all()

    def create(
        self,
        *,
        name: str,
        address: str,
        type: str = Market.MARKET,
        latitude: Decimal | None = None,
        longitude: Decimal | None = None,
    ) -> Market:
        market = Market(
            name=name,
            address=address,
            # Умолчание — рынок: лавка это частный случай, который указывают явно.
            type=type,
            latitude=latitude,
            longitude=longitude,
            is_active=True,
        )
        self.session.add(market)
        self.session.flush()
        return market
