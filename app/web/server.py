import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config.settings import settings
from app.database.db import init_db
from app.web.routes import auth_router, admin_router, public_router, api_router
from app.utils.logger import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager to ensure DB is initialized on boot."""
    logger.info("Initializing Web Application (Port 20129)...")
    await init_db()
    yield
    logger.info("Web Application shutdown completed.")

def create_web_app() -> FastAPI:
    """Create and configure FastAPI application for Web Release."""
    app = FastAPI(
        title="PKL Finder SaaS",
        description="Autonomous Multi-Tenant AI Internship Hunter Platform",
        version="2.0.0",
        lifespan=lifespan
    )

    # Register Routers
    app.include_router(public_router)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(api_router)

    # Global Exception Handler
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        if request.url.path.startswith("/admin"):
            return RedirectResponse(url="/admin/dashboard")
        return RedirectResponse(url="/")

    return app

web_app = create_web_app()

async def run_web_server(host: str = settings.HOST, port: int = settings.WEB_PORT) -> None:
    """Run uvicorn server for web dashboard."""
    logger.info(f"Starting Web Application on http://{host}:{port}...")
    config = uvicorn.Config(
        app=web_app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_web_server())
