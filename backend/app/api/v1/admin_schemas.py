from datetime import datetime

from pydantic import BaseModel


class AdminActivationRequest(BaseModel):
    activation_code: str


class AdminActivationResponse(BaseModel):
    access_token: str


class AdminIdentityResponse(BaseModel):
    admin_id: int
    user_id: int


class SellerOnboardingRequest(BaseModel):
    user_id: int


class SellerActivationCodeResponse(BaseModel):
    seller_id: int
    activation_code: str


class SellerSummary(BaseModel):
    seller_id: int
    user_id: int
    name: str
    is_active: bool
    current_catalog_version: int
    activated_at: datetime | None
    activation_code_expires_at: datetime | None


class SellerListResponse(BaseModel):
    sellers: list[SellerSummary]
