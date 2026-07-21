from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.v1.catalog import router as catalog_router
from app.api.v1.photos import router as photos_router
from app.api.v1.publications import router as publications_router
from app.api.v1.seller import router as seller_router
from app.infrastructure.database import get_session

app = FastAPI(
    title="GreenMarket Backend",
    version="1.0.0",
)
app.include_router(publications_router)
app.include_router(catalog_router)
app.include_router(seller_router)
app.include_router(photos_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Ошибка валидации запроса",
                "details": [str(e) for e in exc.errors()],
            }
        },
    )


@app.get("/health")
def health(session: Session = Depends(get_session)):
    try:
        session.execute(text("SELECT 1"))
    except OperationalError as exc:
        detail = str(exc.orig) if exc.orig else str(exc)
        return {"status": "DOWN", "database": detail}
    return {"status": "UP", "database": "UP"}
