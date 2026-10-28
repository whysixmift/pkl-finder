import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, func, or_
from app.agents.base_agent import BaseAgent
from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import UserWhitelist
from app.utils.logger import logger

class AccessControlAgent(BaseAgent):
    """Agent responsible for Multi-Tenant SaaS user whitelist authorization and management."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="AccessControlAgent",
            feature_description="SaaS User Authorization & Whitelist Governance (Username & User ID)"
        )

    async def is_allowed(self, user_id: int, username: Optional[str] = None) -> bool:
        """Determines if a user has access to use the bot and SaaS features.
        Admin is always authorized. Whitelisted users (by user ID or username) are authorized.
        """
        start = self.mark_start()
        try:
            # 1. Configured Admin always bypasses whitelist
            if settings.TELEGRAM_ADMIN_ID and user_id == settings.TELEGRAM_ADMIN_ID:
                self.mark_success(start)
                return True

            clean_username = username.strip().lstrip("@").lower() if username else None

            async with async_session_maker() as session:
                # Query whitelist table
                stmt = select(UserWhitelist).where(UserWhitelist.is_active.is_(True))
                conditions = [UserWhitelist.telegram_id == user_id]
                if clean_username:
                    conditions.append(func.lower(UserWhitelist.username) == clean_username)
                stmt = stmt.where(or_(*conditions))

                res = await session.execute(stmt)
                record = res.scalar_one_or_none()

                if record:
                    # Auto-bind telegram_id if it was previously registered only by username
                    if not record.telegram_id and user_id:
                        record.telegram_id = user_id
                        record.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        await session.commit()
                        logger.info(f"[{self.agent_name}] Linked Telegram ID {user_id} to username @{record.username}")
                    
                    self.mark_success(start)
                    return True

            self.mark_success(start)
            return False

        except Exception as e:
            self.mark_failure(start, e)
            logger.error(f"[{self.agent_name}] Error validating access for user {user_id}: {e}")
            return False

    async def add_to_whitelist(self, identifier: str, notes: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Add user to whitelist. Supports username (e.g. @johndoe or johndoe) OR telegram user_id (e.g. 123456789).
        Mandatory requirement: MUST support both username and user ID!
        """
        start = self.mark_start()
        try:
            identifier_str = str(identifier).strip()
            if not identifier_str:
                return False, "Identifier cannot be empty.", None

            telegram_id: Optional[int] = None
            username: Optional[str] = None

            # Detect if input is pure numeric (User ID) or text (Username)
            if re.fullmatch(r"^\d+$", identifier_str):
                telegram_id = int(identifier_str)
            else:
                username = identifier_str.lstrip("@").strip()

            async with async_session_maker() as session:
                # Check for existing record
                stmt = select(UserWhitelist)
                if telegram_id is not None:
                    stmt = stmt.where(UserWhitelist.telegram_id == telegram_id)
                elif username:
                    stmt = stmt.where(func.lower(UserWhitelist.username) == username.lower())

                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()

                if existing:
                    existing.is_active = True
                    if notes:
                        existing.notes = notes
                    existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await session.commit()
                    self.mark_success(start)
                    return True, f"User '{identifier_str}' updated and active in whitelist.", {
                        "id": existing.id,
                        "telegram_id": existing.telegram_id,
                        "username": existing.username,
                        "notes": existing.notes,
                        "is_active": existing.is_active
                    }

                new_user = UserWhitelist(
                    telegram_id=telegram_id,
                    username=username,
                    notes=notes or "Added via Admin Dashboard",
                    is_active=True
                )
                session.add(new_user)
                await session.commit()
                await session.refresh(new_user)
                self.mark_success(start)
                return True, f"User '{identifier_str}' successfully added to whitelist.", {
                    "id": new_user.id,
                    "telegram_id": new_user.telegram_id,
                    "username": new_user.username,
                    "notes": new_user.notes,
                    "is_active": new_user.is_active
                }

        except Exception as e:
            self.mark_failure(start, e)
            return False, f"Failed to add user to whitelist: {str(e)}", None

    async def list_whitelisted_users(self) -> List[Dict[str, Any]]:
        """List all whitelisted users for admin dashboard."""
        start = self.mark_start()
        try:
            async with async_session_maker() as session:
                stmt = select(UserWhitelist).order_by(UserWhitelist.id.desc())
                res = await session.execute(stmt)
                users = res.scalars().all()
                data = [
                    {
                        "id": u.id,
                        "telegram_id": u.telegram_id,
                        "username": u.username,
                        "notes": u.notes,
                        "is_active": u.is_active,
                        "created_at": u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "",
                        "updated_at": u.updated_at.strftime("%Y-%m-%d %H:%M:%S") if u.updated_at else ""
                    }
                    for u in users
                ]
                self.mark_success(start)
                return data
        except Exception as e:
            self.mark_failure(start, e)
            return []

    async def toggle_status(self, whitelist_id: int) -> Tuple[bool, str]:
        """Toggle active/suspended status for a whitelisted user."""
        start = self.mark_start()
        try:
            async with async_session_maker() as session:
                stmt = select(UserWhitelist).where(UserWhitelist.id == whitelist_id)
                res = await session.execute(stmt)
                user = res.scalar_one_or_none()
                if not user:
                    return False, "User not found."
                user.is_active = not user.is_active
                user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
                status_str = "Active" if user.is_active else "Suspended"
                self.mark_success(start)
                return True, f"Status updated to {status_str}."
        except Exception as e:
            self.mark_failure(start, e)
            return False, str(e)

    async def remove_from_whitelist(self, whitelist_id: int) -> Tuple[bool, str]:
        """Remove a user record from the whitelist."""
        start = self.mark_start()
        try:
            async with async_session_maker() as session:
                stmt = select(UserWhitelist).where(UserWhitelist.id == whitelist_id)
                res = await session.execute(stmt)
                user = res.scalar_one_or_none()
                if not user:
                    return False, "User not found."
                await session.delete(user)
                await session.commit()
                self.mark_success(start)
                return True, "User successfully removed from whitelist."
        except Exception as e:
            self.mark_failure(start, e)
            return False, str(e)

# Singleton Agent Instance
access_control_agent = AccessControlAgent()
