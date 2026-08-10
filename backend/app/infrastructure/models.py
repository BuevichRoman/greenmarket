"""ORM-модели, отображающие существующую схему GreenMarket.

Database First: таблицы уже созданы миграциями в ../../database/migrations/
(001-006). Эти классы только описывают уже существующие столбцы для запросов
через SQLAlchemy — они не создают и не изменяют схему (Base.metadata.create_all
здесь сознательно не вызывается).

Платформенные таблицы Seller/User/Photo (iBronevik) намеренно не отображаются
как ORM-модели — GreenMarket ими не владеет. Внешние ключи на них (seller_id,
moderator_id, published_by, photo_id) остаются обычными столбцами без
relationship().
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database import Base


class ProductGroup(Base):
    __tablename__ = "ProductGroup"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("ProductGroup.id"))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean)
    # server_default повторяет DEFAULT CURRENT_TIMESTAMP из миграций 001/002:
    # без него ORM подставляет в INSERT явный NULL и падает на NOT NULL.
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    parent: Mapped["ProductGroup | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["ProductGroup"]] = relationship(back_populates="parent")
    products: Mapped[list["Product"]] = relationship(back_populates="group")


class Product(Base):
    __tablename__ = "Product"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_group_id: Mapped[int] = mapped_column(ForeignKey("ProductGroup.id"))
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped["ProductGroup"] = relationship(back_populates="products")


class SellerProduct(Base):
    __tablename__ = "SellerProduct"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("Product.id"))
    seller_name: Mapped[str] = mapped_column(String(200))
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    stock: Mapped[float] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(Text)
    origin_country: Mapped[str | None] = mapped_column(String(100))
    supply_date: Mapped[date | None] = mapped_column(Date)
    is_published: Mapped[bool] = mapped_column(Boolean)
    moderation_status: Mapped[str] = mapped_column(String(30))
    moderator_id: Mapped[int | None] = mapped_column(Integer)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime)
    moderation_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    product: Mapped["Product | None"] = relationship()


class SellerProductPhoto(Base):
    __tablename__ = "SellerProductPhoto"

    seller_product_id: Mapped[int] = mapped_column(ForeignKey("SellerProduct.id"), primary_key=True)
    photo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer)


class CatalogPublication(Base):
    __tablename__ = "CatalogPublication"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    publication_key: Mapped[str] = mapped_column(String(36))
    catalog_hash: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(DateTime)
    published_by: Mapped[int] = mapped_column(Integer)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    deactivated_count: Mapped[int] = mapped_column(Integer, default=0)


class Administrator(Base):
    """Учётная запись администратора GreenMarket (миграция 013).

    В отличие от Seller — своя таблица GreenMarket, а не платформенная: роль
    `users.id_role` намеренно не участвует в доступе. `user_id` нужен потому,
    что `SellerProduct.moderator_id` — FK на `users(id_user)`.
    """

    __tablename__ = "Administrator"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean)
    access_token: Mapped[str | None] = mapped_column(String(64))
    activation_code: Mapped[str | None] = mapped_column(String(32))
    activation_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

class SellerProfileChange(Base):
    """Журнал изменений полей профиля продавца (миграция 015).

    Сами значения профиля живут в платформенных `users_prop_items_*`, где нет
    ни автора, ни времени — отсюда отдельная таблица GreenMarket. `author_role`
    хранится строкой ('SELLER'/'ADMIN'): по одному `author_user_id` роль не
    восстановить, администратор тоже пользователь платформы.
    """

    __tablename__ = "SellerProfileChange"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    author_user_id: Mapped[int] = mapped_column(Integer)
    author_role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
