import re
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, func, or_
from app.agents.base_agent import BaseAgent
from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import UserWhitelist
from app.services.admin_notifier import notify_admin_new_user, notify_user_approved
from app.utils.logger import logger

class AccessControlAgent(BaseAgent):
    """Agent responsible for Multi-Tenant SaaS user whitelist authorization, approval workflows, and governance."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="AccessControlAgent",
            feature_description="SaaS User Authorization & Whitelist Approval Governance (Username, User ID & Email)"
        )

    async def is_allowed(self, user_id: int, username: Optional[str] = None) -> bool:
        """Determines if a user has approved access to use the bot and SaaS features.
        Admin is always authorized. Whitelisted users must be active and status=='approved'.
        """
        start = self.mark_start()
        try:
            # 1. Configured Admin always bypasses whitelist
            if settings.TELEGRAM_ADMIN_ID and user_id == settings.TELEGRAM_ADMIN_ID:
                self.mark_success(start)
                return True

            clean_username = username.strip().lstrip("@").lower() if username else None

            async with async_session_maker() as session:
                # Query whitelist table for active and approved record
                stmt = select(UserWhitelist).where(
                    UserWhitelist.is_active.is_(True),
                    UserWhitelist.status == "approved"
                )
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

    async def get_or_create_pending_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        email: Optional[str] = None,
        source: str = "telegram",
        details: Optional[str] = None
    ) -> Tuple[UserWhitelist, bool]:
        """Check if user is registered; if not, create a pending approval record and alert the admin."""
        start = self.mark_start()
        clean_username = username.strip().lstrip("@") if username else None

        async with async_session_maker() as session:
            stmt = select(UserWhitelist)
            conditions = [UserWhitelist.telegram_id == user_id]
            if clean_username:
                conditions.append(func.lower(UserWhitelist.username) == clean_username.lower())
            if email:
                conditions.append(func.lower(UserWhitelist.email) == email.lower())
            stmt = stmt.where(or_(*conditions))

            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()

            if existing:
                self.mark_success(start)
                return existing, False

            # Create new pending record
            new_user = UserWhitelist(
                telegram_id=user_id if user_id > 0 else None,
                username=clean_username,
                email=email,
                notes=f"Auto-registered via {source.upper()}",
                status="pending",
                source=source,
                is_active=False
            )
            session.add(new_user)
            await session.commit()
            await session.refresh(new_user)

            # Fire off admin notification
            try:
                asyncio.create_task(
                    notify_admin_new_user(
                        user_id=user_id,
                        username=clean_username,
                        email=email,
                        source=source,
                        details=details
                    )
                )
            except Exception as e:
                logger.error(f"Failed to queue admin alert task: {e}")

            self.mark_success(start)
            logger.info(f"[{self.agent_name}] Created pending registration for User {user_id} (@{clean_username})")
            return new_user, True

    async def approve_user(self, identifier: Any) -> Tuple[bool, str, Optional[int]]:
        """Approve a pending or suspended user. Can be user_id (int/str) or whitelist_id."""
        start = self.mark_start()
        try:
            async with async_session_maker() as session:
                target = str(identifier).strip().lstrip("@")
                stmt = select(UserWhitelist)

                if target.isdigit():
                    num_val = int(target)
                    stmt = stmt.where(or_(UserWhitelist.id == num_val, UserWhitelist.telegram_id == num_val))
                else:
                    stmt = stmt.where(func.lower(UserWhitelist.username) == target.lower())

                res = await session.execute(stmt)
                user = res.scalar_one_or_none()

                if not user:
                    self.mark_failure(start, ValueError("User not found"))
                    return False, f"User '{identifier}' tidak ditemukan.", None

                user.status = "approved"
                user.is_active = True
                user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()

                target_tg_id = user.telegram_id
                if target_tg_id:
                    asyncio.create_task(notify_user_approved(target_tg_id))

                self.mark_success(start)
                user_label = f"@{user.username}" if user.username else f"ID {user.telegram_id}"
                return True, f"User {user_label} berhasil disetujui (Approved).", target_tg_id

        except Exception as e:
            self.mark_failure(start, e)
            logger.error(f"[{self.agent_name}] Error approving user {identifier}: {e}")
            return False, f"Gagal menyetujui user: {str(e)}", None

    async def reject_user(self, identifier: Any) -> Tuple[bool, str, Optional[int]]:
        """Reject or suspend a user."""
        start = self.mark_start()
        try:
            async with async_session_maker() as session:
                target = str(identifier).strip().lstrip("@")
                stmt = select(UserWhitelist)

                if target.isdigit():
                    num_val = int(target)
                    stmt = stmt.where(or_(UserWhitelist.id == num_val, UserWhitelist.telegram_id == num_val))
                else:
                    stmt = stmt.where(func.lower(UserWhitelist.username) == target.lower())

                res = await session.execute(stmt)
                user = res.scalar_one_or_none()

                if not user:
                    self.mark_failure(start, ValueError("User not found"))
                    return False, f"User '{identifier}' tidak ditemukan.", None

                user.status = "rejected"
                user.is_active = False
                user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()

                self.mark_success(start)
                user_label = f"@{user.username}" if user.username else f"ID {user.telegram_id}"
                return True, f"User {user_label} berhasil ditolak (Rejected).", user.telegram_id

        except Exception as e:
            self.mark_failure(start, e)
            logger.error(f"[{self.agent_name}] Error rejecting user {identifier}: {e}")
            return False, f"Gagal menolak user: {str(e)}", None

    async def add_to_whitelist(self, identifier: str, notes: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Manually add or activate a user to whitelist with immediate approval."""
        start = self.mark_start()
        try:
            identifier_str = str(identifier).strip()
            if not identifier_str:
                return False, "Identifier cannot be empty.", None

            telegram_id: Optional[int] = None
            username: Optional[str] = None

            if re.fullmatch(r"^\d+$", identifier_str):
                telegram_id = int(identifier_str)
            else:
                username = identifier_str.lstrip("@").strip()

            async with async_session_maker() as session:
                stmt = select(UserWhitelist)
                if telegram_id is not None:
                    stmt = stmt.where(UserWhitelist.telegram_id == telegram_id)
                elif username:
                    stmt = stmt.where(func.lower(UserWhitelist.username) == username.lower())

                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()

                if existing:
                    existing.is_active = True
                    existing.status = "approved"
                    if notes:
                        existing.notes = notes
                    existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await session.commit()
                    self.mark_success(start)
                    return True, f"User '{identifier_str}' updated and active in whitelist.", {
                        "id": existing.id,
                        "telegram_id": existing.telegram_id,
                        "username": existing.username,
                        "status": existing.status,
                        "notes": existing.notes,
                        "is_active": existing.is_active
                    }

                new_user = UserWhitelist(
                    telegram_id=telegram_id,
                    username=username,
                    notes=notes or "Added via Admin Dashboard",
                    status="approved",
                    source="admin_manual",
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
                    "status": new_user.status,
                    "notes": new_user.notes,
                    "is_active": new_user.is_active
                }

        except Exception as e:
            self.mark_failure(start, e)
            return False, f"Failed to add user to whitelist: {str(e)}", None

    async def list_whitelisted_users(self) -> List[Dict[str, Any]]:
        """List all users for admin dashboard and bot."""
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
                        "email": u.email,
                        "notes": u.notes,
                        "status": getattr(u, "status", "approved"),
                        "source": getattr(u, "source", "telegram"),
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

    async def list_pending_users(self) -> List[Dict[str, Any]]:
        """List users specifically awaiting admin approval."""
        all_users = await self.list_whitelisted_users()
        return [u for u in all_users if u.get("status") == "pending"]

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
                if user.is_active:
                    user.status = "approved"
                else:
                    user.status = "rejected"
                user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
                status_str = "Approved / Active" if user.is_active else "Suspended / Rejected"
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
