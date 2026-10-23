from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.database.connection import check_database_connection

router = APIRouter()


@router.get("/health")
def get_health() -> JSONResponse:
    if check_database_connection():
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ok",
                "api": "ok",
                "database": "connected",
            },
        )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "unhealthy",
            "api": "ok",
            "database": "disconnected",
        },
    )
