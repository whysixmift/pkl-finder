import os
import uvicorn
from typing import Dict, Any
from fastapi import FastAPI, Request
from app.config.settings import settings
from app.utils.logger import logger

def create_bot_http_app(bot_username: str = "Unknown") -> FastAPI:
    """Create FastAPI application for Bot status, health, and webhook receiver on Port 20128."""
    app = FastAPI(
        title="PKL Finder Bot Server",
        description="Telegram Bot Health & Webhook Service",
        version="2.0.0"
    )

    @app.get("/")
    async def bot_root() -> Dict[str, Any]:
        return {
            "service": "pkl-finder-bot",
            "port": settings.BOT_PORT,
            "status": "online",
            "bot_username": bot_username,
            "description": "Telegram Bot Service Branch"
        }

    @app.get("/health")
    async def bot_health() -> Dict[str, Any]:
        return {
            "status": "healthy",
            "port": settings.BOT_PORT,
            "bot_username": bot_username,
            "telegram_configured": bool(settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("your_"))
        }

    @app.post("/webhook")
    async def bot_webhook(request: Request):
        """Optional webhook receiver for Telegram updates."""
        data = await request.json()
        logger.debug(f"[Bot Webhook] Received update: {data.get('update_id')}")
        return {"ok": True}

    return app

async def run_bot_http_server(bot_username: str = "Unknown", host: str = settings.HOST, port: int = settings.BOT_PORT) -> None:
    """Run uvicorn server for Bot service port 20128."""
    logger.info(f"Starting Bot HTTP Service on http://{host}:{port}...")
    app = create_bot_http_app(bot_username)
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False
    )
    server = uvicorn.Server(config)
    await server.serve()
