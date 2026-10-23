from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.datasets import router as datasets_router
from app.api.routes.health import router as health_router
from app.api.routes.simulations import router as simulations_router

app = FastAPI(title="RESQNET API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://resqnet-en69laez7-rail-vision-ai.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(simulations_router, prefix="/api/simulations", tags=["simulations"])
app.include_router(datasets_router, prefix="/api/datasets", tags=["datasets"])