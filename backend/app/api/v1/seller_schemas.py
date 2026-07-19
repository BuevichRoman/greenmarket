from datetime import datetime

from pydantic import BaseModel


class SellerStatusResponse(BaseModel):
    seller_id: int
    is_active: bool
    current_catalog_version: int
    published_product_count: int
    last_published_at: datetime | None
