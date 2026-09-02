from fastapi import FastAPI

from app.api.routes.generate import router as generate_router
from app.api.routes.health import router as health_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # No CORS: only the backend (server-to-server) talks to the agent, never a
    # browser. The frontend goes through the backend, not straight to here.

    app.include_router(health_router)
    app.include_router(generate_router)

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()
