from app.web.routes.auth_routes import router as auth_router
from app.web.routes.admin_routes import router as admin_router
from app.web.routes.public_routes import router as public_router
from app.web.routes.api_routes import router as api_router

__all__ = ["auth_router", "admin_router", "public_router", "api_router"]
