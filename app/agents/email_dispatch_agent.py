from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.database.db import async_session_maker
from app.database.models import EmailQueue
from app.services.email_service import email_service
from app.services.google_auth_service import google_auth_service
from app.utils.logger import logger

class EmailDispatchAgent(BaseAgent):
    """Autonomous agent responsible for dispatching queued emails via Google Gmail API or SMTP."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="EmailDispatchAgent",
            feature_description="Outbound Email Delivery Engine (Google OAuth Gmail API & SMTP Dispatcher)"
        )

    async def dispatch_single(self, email_id: int) -> Tuple[bool, str]:
        """Dispatch a single queued email using Google Gmail API or SMTP."""
        start = self.mark_start()
        try:
            async with async_session_maker() as session:
                success = await email_service.send_email(session, email_id)
                if success:
                    self.mark_success(start)
                    return True, f"Email ID {email_id} successfully sent."
                else:
                    self.mark_failure(start, ValueError("Email send returned False"))
                    return False, f"Failed to send email ID {email_id}."
        except Exception as e:
            self.mark_failure(start, e)
            return False, str(e)

    async def dispatch_approved_queue(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Dispatch all approved drafts in queue."""
        start = self.mark_start()
        sent_count = 0
        failed_count = 0
        errors: List[str] = []

        try:
            async with async_session_maker() as session:
                stmt = select(EmailQueue).where(EmailQueue.status == "approved")
                if user_id:
                    stmt = stmt.where(EmailQueue.user_id == user_id)
                res = await session.execute(stmt)
                queued_emails = list(res.scalars().all())

            for draft in queued_emails:
                try:
                    async with async_session_maker() as session:
                        await email_service.send_email(session, draft.id)
                        sent_count += 1
                except Exception as e:
                    failed_count += 1
                    errors.append(f"Email {draft.id} ({draft.recipient_email}): {str(e)}")

            self.mark_success(start)
            return {
                "total_queued": len(queued_emails),
                "sent": sent_count,
                "failed": failed_count,
                "errors": errors
            }

        except Exception as e:
            self.mark_failure(start, e)
            return {
                "total_queued": 0,
                "sent": 0,
                "failed": 0,
                "errors": [str(e)]
            }

email_dispatch_agent = EmailDispatchAgent()
