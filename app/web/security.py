import time
import hmac
import hashlib
import json
import base64
from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from app.config.settings import settings

def create_admin_session() -> str:
    """Create a signed session token for admin authentication."""
    payload = {
        "admin": True,
        "exp": int(time.time()) + 86400 * 7  # 7 days validity
    }
    raw = json.dumps(payload).encode("utf-8")
    encoded_payload = base64.urlsafe_b64encode(raw).decode("utf-8")
    signature = hmac.new(
        settings.SESSION_SECRET_KEY.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return f"{encoded_payload}.{signature}"

def verify_admin_session(token: Optional[str]) -> bool:
    """Validate signed session token."""
    if not token or "." not in token:
        return False
    try:
        encoded_payload, signature = token.split(".", 1)
        expected_sig = hmac.new(
            settings.SESSION_SECRET_KEY.encode("utf-8"),
            encoded_payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return False

        payload_bytes = base64.urlsafe_b64decode(encoded_payload.encode("utf-8"))
        payload = json.loads(payload_bytes.decode("utf-8"))

        if payload.get("exp", 0) < int(time.time()):
            return False
        return bool(payload.get("admin", False))
    except Exception:
        return False

def verify_admin_password(password: str) -> bool:
    """Constant-time verification of admin password 'uranium235aregoated'."""
    expected = settings.ADMIN_PASSWORD
    return hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))

async def require_admin(request: Request) -> bool:
    """FastAPI route dependency ensuring admin authentication."""
    cookie = request.cookies.get("pkl_admin_session")
    if not verify_admin_session(cookie):
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/admin/login"}
        )
    return True
