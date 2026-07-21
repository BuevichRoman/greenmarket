from pydantic import BaseModel


class PhotoUploadResponse(BaseModel):
    photo_id: int
