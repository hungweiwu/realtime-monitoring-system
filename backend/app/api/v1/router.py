from fastapi import APIRouter

from app.api.v1 import admin, analytics, auth, metrics, records, users, ws

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(records.router)
api_router.include_router(metrics.router)
api_router.include_router(analytics.router)
api_router.include_router(admin.router)
api_router.include_router(ws.router)
