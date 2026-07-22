from pydantic import BaseModel


class PhotoUploadResponse(BaseModel):
    photo_id: int


class PhotoInfo(BaseModel):
    photo_id: int
    url: str


class PhotoListResponse(BaseModel):
    photos: list[PhotoInfo]
