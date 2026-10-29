import httpx
from typing import Optional
from app.config.settings import settings
from app.utils.logger import logger

async def notify_admin_new_user(
    user_id: int,
    username: Optional[str] = None,
    email: Optional[str] = None,
    source: str = "telegram",
    details: Optional[str] = None
) -> None:
    """Send immediate notification to Telegram Admin and Admin Bot with inline Approve/Reject action buttons."""
    if not settings.TELEGRAM_ADMIN_ID:
        logger.warning("TELEGRAM_ADMIN_ID not configured; cannot deliver admin notification.")
        return

    user_display = f"@{username}" if username else f"ID: {user_id}"
    if email:
        user_display += f" ({email})"

    text = (
        f"🚨 <b>Pendaftaran Pengguna Baru!</b>\n\n"
        f"👤 <b>Pengguna:</b> <code>{user_display}</code>\n"
        f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"🌐 <b>Sumber:</b> <code>{source.upper()}</code>\n"
    )
    if details:
        text += f"📝 <b>Detail:</b> {details}\n"

    text += "\nSilakan pilih tindakan untuk menentukan akses pengguna ini:"

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Setujui (Approve)", "callback_data": f"adm_approve:{user_id}"},
                {"text": "⛔ Tolak (Reject)", "callback_data": f"adm_reject:{user_id}"}
            ]
        ]
    }

    tokens = []
    # Try admin bot token first, fallback to primary bot token
    if settings.ADMIN_BOT_TOKEN and not settings.ADMIN_BOT_TOKEN.startswith("mock_"):
        tokens.append(settings.ADMIN_BOT_TOKEN)
    if settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("mock_"):
        if settings.TELEGRAM_BOT_TOKEN not in tokens:
            tokens.append(settings.TELEGRAM_BOT_TOKEN)

    async with httpx.AsyncClient(timeout=10.0) as client:
        for token in tokens:
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = {
                    "chat_id": settings.TELEGRAM_ADMIN_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup
                }
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Dispatched admin registration alert for user {user_id}")
                    return
            except Exception as e:
                logger.error(f"Error dispatching admin notification via bot: {e}")

async def notify_user_approved(user_id: int) -> None:
    """Notify the user on Telegram that their account has been approved."""
    if not user_id or not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN.startswith("mock_"):
        return

    text = (
        "🎉 <b>Selamat! Akun Anda Telah Disetujui oleh Admin.</b>\n\n"
        "Akses penuh ke PKL & Job Finder SaaS telah aktif! "
        "Sekarang Anda dapat mencari lowongan kerja yang cocok dengan profil Anda dan mengirim lamaran otomatis."
    )
    reply_markup = {
        "inline_keyboard": [
            [{"text": "🚀 Cari Lowongan Kerja Sekarang", "callback_data": "btn_search"}]
        ]
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
            await client.post(
                url,
                json={"chat_id": user_id, "text": text, "parse_mode": "HTML", "reply_markup": reply_markup}
            )
            logger.info(f"Delivered approval confirmation alert to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to notify approved user {user_id}: {e}")
