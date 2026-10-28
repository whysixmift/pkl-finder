import os
import json
import base64
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any, List
import httpx
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import UserGoogleAuth, EmailQueue
from app.services.email_service import encrypt_password, decrypt_password
from app.utils.logger import logger

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid"
]

class GoogleAuthService:
    """Manages Google OAuth2 SSO authentication and Gmail API direct email dispatch."""

    def get_redirect_uri(self) -> str:
        """Resolve Google OAuth callback URI."""
        if settings.GOOGLE_REDIRECT_URI:
            return settings.GOOGLE_REDIRECT_URI
        base = settings.WEB_BASE_URL.rstrip("/")
        return f"{base}/api/auth/google/callback"

    def get_authorization_url(self, user_id: int) -> str:
        """Construct Google OAuth2 authorization URL requesting Gmail Send permission."""
        state_payload = {"user_id": user_id, "timestamp": datetime.now(timezone.utc).timestamp()}
        encoded_state = base64.urlsafe_b64encode(json.dumps(state_payload).encode()).decode()

        redirect_uri = self.get_redirect_uri()
        scopes = " ".join(GMAIL_SCOPES)

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID or "mock_client_id",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scopes,
            "access_type": "offline",
            "prompt": "consent",
            "state": encoded_state
        }
        return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def decode_state(self, state: str) -> Optional[int]:
        """Extract user_id from state parameter."""
        try:
            raw = base64.urlsafe_b64decode(state.encode()).decode()
            data = json.loads(raw)
            return int(data.get("user_id", 0))
        except Exception as e:
            logger.error(f"Failed to decode OAuth state: {e}")
            return None

    async def handle_oauth_callback(
        self,
        session: AsyncSession,
        code: str,
        state: str
    ) -> Tuple[bool, str, int]:
        """Exchange authorization code for tokens, retrieve Google email, and store credentials."""
        user_id = self.decode_state(state)
        if not user_id:
            return False, "Invalid or expired state parameter.", 0

        redirect_uri = self.get_redirect_uri()

        # Exchange code for tokens
        token_payload = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                token_resp = await client.post(GOOGLE_TOKEN_URL, data=token_payload)
                if token_resp.status_code != 200:
                    err_msg = token_resp.text
                    logger.error(f"Google OAuth token exchange failed ({token_resp.status_code}): {err_msg}")
                    return False, f"Failed token exchange with Google: {err_msg}", user_id

                token_data = token_resp.json()
                access_token = token_data.get("access_token")
                refresh_token = token_data.get("refresh_token")
                expires_in = token_data.get("expires_in", 3600)

                # Fetch Google account profile email
                userinfo_resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                if userinfo_resp.status_code != 200:
                    logger.error(f"Failed to fetch Google userinfo: {userinfo_resp.text}")
                    return False, "Failed to retrieve Google account info.", user_id

                userinfo_data = userinfo_resp.json()
                google_email = userinfo_data.get("email", "unknown@gmail.com")

            # Encrypt tokens
            enc_access = encrypt_password(access_token)
            enc_refresh = encrypt_password(refresh_token) if refresh_token else None
            expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=expires_in)

            # Upsert into database
            stmt = select(UserGoogleAuth).where(UserGoogleAuth.user_id == user_id)
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()

            if existing:
                existing.email = google_email
                existing.access_token_encrypted = enc_access
                if enc_refresh:
                    existing.refresh_token_encrypted = enc_refresh
                existing.token_expiry = expiry
                existing.scopes = " ".join(GMAIL_SCOPES)
                existing.is_active = True
                existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                record = UserGoogleAuth(
                    user_id=user_id,
                    email=google_email,
                    access_token_encrypted=enc_access,
                    refresh_token_encrypted=enc_refresh,
                    token_expiry=expiry,
                    scopes=" ".join(GMAIL_SCOPES),
                    is_active=True
                )
                session.add(record)

            await session.commit()
            logger.info(f"Successfully linked Google account {google_email} for user {user_id}")
            return True, f"Berhasil login dengan Google: {google_email} (Gmail API aktif)", user_id

        except Exception as e:
            logger.error(f"Exception handling Google OAuth callback: {e}", exc_info=True)
            return False, f"Error processing Google SSO callback: {str(e)}", user_id

    async def get_active_auth(self, session: AsyncSession, user_id: int) -> Optional[UserGoogleAuth]:
        """Retrieve active Google Auth configuration for user."""
        stmt = select(UserGoogleAuth).where(
            (UserGoogleAuth.user_id == user_id) & (UserGoogleAuth.is_active.is_(True))
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_valid_access_token(self, session: AsyncSession, user_id: int) -> Optional[str]:
        """Return a valid decrypted access token, automatically refreshing if expired."""
        auth = await self.get_active_auth(session, user_id)
        if not auth:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Check if token is expired or expires within 60 seconds
        if auth.token_expiry and auth.token_expiry <= (now + timedelta(seconds=60)):
            if not auth.refresh_token_encrypted:
                logger.warning(f"Google token for user {user_id} expired and no refresh token is present.")
                return None

            try:
                refresh_token = decrypt_password(auth.refresh_token_encrypted)
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        GOOGLE_TOKEN_URL,
                        data={
                            "client_id": settings.GOOGLE_CLIENT_ID,
                            "client_secret": settings.GOOGLE_CLIENT_SECRET,
                            "refresh_token": refresh_token,
                            "grant_type": "refresh_token"
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        new_access = data.get("access_token")
                        expires_in = data.get("expires_in", 3600)
                        auth.access_token_encrypted = encrypt_password(new_access)
                        auth.token_expiry = now + timedelta(seconds=expires_in)
                        auth.updated_at = now
                        await session.commit()
                        logger.info(f"Refreshed Google access token for user {user_id}")
                        return new_access
                    else:
                        logger.error(f"Failed to refresh Google token ({resp.status_code}): {resp.text}")
                        return None
            except Exception as e:
                logger.error(f"Error during Google token refresh for user {user_id}: {e}")
                return None

        return decrypt_password(auth.access_token_encrypted)

    async def send_gmail(
        self,
        session: AsyncSession,
        email_record: EmailQueue
    ) -> Tuple[bool, Optional[str]]:
        """Dispatch email directly via Gmail API using OAuth credentials."""
        access_token = await self.get_valid_access_token(session, email_record.user_id)
        if not access_token:
            return False, "No active Google OAuth credentials found or token could not be refreshed."

        auth = await self.get_active_auth(session, email_record.user_id)
        sender_email = auth.email if auth else "me"

        # Build RFC 2822 MIME message
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = email_record.recipient_email
        msg["Subject"] = email_record.subject

        # Attach text body
        msg.attach(MIMEText(email_record.body, "plain", "utf-8"))

        # Attach CV and other attachments
        if email_record.attachments:
            try:
                file_paths = json.loads(email_record.attachments)
                for path in file_paths:
                    if path and os.path.exists(path):
                        filename = os.path.basename(path)
                        with open(path, "rb") as f:
                            part = MIMEApplication(f.read(), Name=filename)
                        part['Content-Disposition'] = f'attachment; filename="{filename}"'
                        msg.attach(part)
                        logger.info(f"Attached file '{filename}' to Gmail message ID {email_record.id}")
            except Exception as att_err:
                logger.error(f"Error attaching files to Gmail message: {att_err}")

        # Base64url encode the message bytes
        raw_bytes = msg.as_bytes()
        raw_encoded = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    GMAIL_SEND_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    },
                    json={"raw": raw_encoded}
                )

                if resp.status_code in [200, 201]:
                    data = resp.json()
                    msg_id = data.get("id", "sent")
                    logger.info(f"Gmail message sent successfully! Google Msg ID: {msg_id}")
                    return True, msg_id
                else:
                    err_text = resp.text
                    logger.error(f"Gmail API send failed ({resp.status_code}): {err_text}")
                    return False, f"Gmail API Error ({resp.status_code}): {err_text}"

        except Exception as e:
            logger.error(f"Exception dispatching email via Gmail API: {e}", exc_info=True)
            return False, str(e)

# Shared Service Instance
google_auth_service = GoogleAuthService()
