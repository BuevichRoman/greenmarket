from pydantic import BaseModel


class AdminActivationRequest(BaseModel):
    activation_code: str


class AdminActivationResponse(BaseModel):
    access_token: str


class AdminIdentityResponse(BaseModel):
    admin_id: int
    user_id: int
