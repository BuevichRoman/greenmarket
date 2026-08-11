from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.v1.admin import router as admin_router
from app.api.v1.admin_catalog import router as admin_catalog_router
from app.api.v1.admin_markets import router as admin_markets_router
from app.api.v1.admin_moderation import router as admin_moderation_router
from app.api.v1.admin_profile import router as admin_profile_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.photos import router as photos_router
from app.api.v1.publications import router as publications_router
from app.api.v1.seller import router as seller_router
from app.core.deployed_commit import read_deployed_commit
from app.infrastructure.database import get_session

app = FastAPI(
    title="GreenMarket Backend",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    # Фронтендов у продукта несколько и они множатся: Customer UI Андрея
    # (green-market-nine) и сборка заместителя (basket-ef9u, 11.08.2026).
    # Суффикс `-[a-z0-9-]+` покрывает preview-развёртывания Vercel, которые
    # получают собственный поддомен на каждый коммит, — иначе каждая ветка
    # фронта упиралась бы в CORS.
    allow_origin_regex=r"^https://(green-market-nine|basket-ef9u)(-[a-z0-9-]+)?\.vercel\.app$",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(publications_router)
app.include_router(catalog_router)
app.include_router(seller_router)
app.include_router(photos_router)
app.include_router(admin_router)
app.include_router(admin_catalog_router)
app.include_router(admin_markets_router)
app.include_router(admin_moderation_router)
app.include_router(admin_profile_router)


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
    # `commit` присутствует всегда, в том числе как null: проверка расхождения
    # снаружи должна отличать «прод не знает своей версии» от «прод не ответил».
    commit = read_deployed_commit()
    try:
        session.execute(text("SELECT 1"))
    except OperationalError as exc:
        detail = str(exc.orig) if exc.orig else str(exc)
        return {"status": "DOWN", "database": detail, "commit": commit}
    return {"status": "UP", "database": "UP", "commit": commit}
