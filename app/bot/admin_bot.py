import asyncio
from functools import wraps
from typing import Optional
from sqlalchemy import select, func
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import Job, Company, UserWhitelist, EmailQueue
from app.agents.access_control_agent import access_control_agent
from app.agents.scraper_agent import scraper_agent
from app.utils.logger import logger

def admin_guard(func):
    """Ensure handler only responds to configured TELEGRAM_ADMIN_ID."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return
        if update.effective_user.id != settings.TELEGRAM_ADMIN_ID:
            logger.warning(f"Unauthorized Admin Bot access attempt by User ID {update.effective_user.id}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ <b>Akses Ditolak:</b> Bot ini khusus Administrator sistem.",
                    parse_mode="HTML"
                )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

@admin_guard
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin bot greeting and command menu."""
    text = (
        "👑 <b>Admin Dashboard Bot - GetAJob / PKL Finder</b>\n\n"
        f"Halo Administrator (ID: <code>{settings.TELEGRAM_ADMIN_ID}</code>)!\n"
        "Gunakan bot ini untuk mengelola persetujuan user baru, memantau lowongan, "
        "dan mengontrol scraping secara otonom.\n\n"
        "📋 <b>Daftar Perintah Admin:</b>\n"
        "• /pending - Tinjau pendaftaran user yang menunggu approval\n"
        "• /users - Kelola dan lihat semua user terdaftar\n"
        "• /stats - Ringkasan statistik database & scraper\n"
        "• /scrape - Trigger on-demand scraping sekarang\n"
        "• /approve &lt;id/username&gt; - Setujui user manual\n"
        "• /reject &lt;id/username&gt; - Tolak / suspend user\n"
        "• /broadcast &lt;pesan&gt; - Kirim pesan ke semua user aktif"
    )
    keyboard = [
        [
            InlineKeyboardButton("⏳ User Pending", callback_data="adm_view_pending"),
            InlineKeyboardButton("👥 Semua User", callback_data="adm_view_users")
        ],
        [
            InlineKeyboardButton("📊 Statistik", callback_data="adm_view_stats"),
            InlineKeyboardButton("🚀 Trigger Scrape", callback_data="adm_trigger_scrape")
        ]
    ]
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

@admin_guard
async def pending_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display pending users waiting for admin approval."""
    pending_users = await access_control_agent.list_pending_users()
    if not pending_users:
        msg = "✅ <b>Semua Bersih!</b> Tidak ada user yang menunggu persetujuan saat ini."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    text = f"⏳ <b>Daftar User Menunggu Persetujuan ({len(pending_users)} user):</b>\n\n"
    keyboard = []

    for u in pending_users[:10]:
        uid = u.get("telegram_id") or u.get("id")
        uname = u.get("username")
        display = f"@{uname}" if uname else f"ID: {uid}"
        source = u.get("source", "telegram").upper()
        email = u.get("email", "")
        extra = f" ({email})" if email else ""

        text += f"• <b>{display}</b>{extra} | <i>{source}</i>\n  Terdaftar: {u.get('created_at', '-')}\n\n"
        keyboard.append([
            InlineKeyboardButton(f"✅ Approve {display}", callback_data=f"adm_approve:{uid}"),
            InlineKeyboardButton(f"⛔ Reject", callback_data=f"adm_reject:{uid}")
        ])

    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="adm_view_pending")])

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

@admin_guard
async def users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display summary of all users with active/pending/rejected breakdown."""
    all_users = await access_control_agent.list_whitelisted_users()
    if not all_users:
        msg = "ℹ️ Belum ada user terdaftar di database."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    total = len(all_users)
    approved = sum(1 for u in all_users if u.get("status") == "approved")
    pending = sum(1 for u in all_users if u.get("status") == "pending")
    rejected = sum(1 for u in all_users if u.get("status") == "rejected")

    text = (
        f"👥 <b>Ringkasan User Whitelist:</b>\n"
        f"• Total Pengguna: <b>{total}</b>\n"
        f"• Approved: 🟢 <b>{approved}</b>\n"
        f"• Pending: ⏳ <b>{pending}</b>\n"
        f"• Rejected / Suspended: 🔴 <b>{rejected}</b>\n\n"
        f"<b>10 User Terbaru:</b>\n"
    )

    keyboard = []
    for u in all_users[:10]:
        uid = u.get("telegram_id") or u.get("id")
        uname = u.get("username")
        display = f"@{uname}" if uname else f"ID: {uid}"
        stat = u.get("status", "unknown").upper()
        icon = "🟢" if stat == "APPROVED" else ("⏳" if stat == "PENDING" else "🔴")
        text += f"{icon} {display} [{stat}] - {u.get('source', '').upper()}\n"

        if stat == "PENDING":
            keyboard.append([
                InlineKeyboardButton(f"✅ Approve {display}", callback_data=f"adm_approve:{uid}"),
                InlineKeyboardButton(f"⛔ Reject", callback_data=f"adm_reject:{uid}")
            ])

    keyboard.append([
        InlineKeyboardButton("⏳ Lihat Yang Pending", callback_data="adm_view_pending"),
        InlineKeyboardButton("🔄 Refresh", callback_data="adm_view_users")
    ])

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

@admin_guard
async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display system and database metrics."""
    async with async_session_maker() as session:
        job_count = await session.scalar(select(func.count(Job.id))) or 0
        company_count = await session.scalar(select(func.count(Company.id))) or 0
        email_count = await session.scalar(select(func.count(EmailQueue.id))) or 0
        user_count = await session.scalar(select(func.count(UserWhitelist.id))) or 0

    text = (
        "📊 <b>Statistik Platform PKL & Job Finder:</b>\n\n"
        f"💼 Total Lowongan Tersimpan: <b>{job_count}</b>\n"
        f"🏢 Total Perusahaan Terdeteksi: <b>{company_count}</b>\n"
        f"📧 Total Antrean Email: <b>{email_count}</b>\n"
        f"👥 Total User Terdaftar: <b>{user_count}</b>\n\n"
        f"🤖 Model AI Utama: <code>{settings.PRIMARY_MODEL}</code>\n"
        f"🌐 Web Platform: <a href='{settings.WEB_BASE_URL}'>{settings.WEB_BASE_URL}</a>"
    )

    keyboard = [
        [
            InlineKeyboardButton("🚀 Jalankan Scrape", callback_data="adm_trigger_scrape"),
            InlineKeyboardButton("🔄 Refresh", callback_data="adm_view_stats")
        ]
    ]

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

@admin_guard
async def scrape_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger scraper agent from admin bot."""
    status_msg = await update.effective_message.reply_text("🚀 <i>Menjalankan Scraper Multi-Platform... Mohon tunggu.</i>", parse_mode="HTML")
    try:
        new_jobs = await scraper_agent.run()
        await status_msg.edit_text(
            f"✅ <b>Scraping Selesai!</b>\n\n"
            f"Ditemukan <b>{len(new_jobs)}</b> lowongan baru yang disimpan ke database.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in admin scrape trigger: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Scraping Gagal:</b> <code>{str(e)}</code>", parse_mode="HTML")

@admin_guard
async def approve_cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual command: /approve <user_id or username>"""
    if not context.args:
        await update.message.reply_text("Penggunaan: <code>/approve &lt;user_id atau @username&gt;</code>", parse_mode="HTML")
        return

    target = context.args[0]
    success, msg, _ = await access_control_agent.approve_user(target)
    if success:
        await update.message.reply_text(f"✅ {msg}", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ {msg}", parse_mode="HTML")

@admin_guard
async def reject_cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual command: /reject <user_id or username>"""
    if not context.args:
        await update.message.reply_text("Penggunaan: <code>/reject &lt;user_id atau @username&gt;</code>", parse_mode="HTML")
        return

    target = context.args[0]
    success, msg, _ = await access_control_agent.reject_user(target)
    if success:
        await update.message.reply_text(f"⛔ {msg}", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ {msg}", parse_mode="HTML")

@admin_guard
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle interactive inline buttons."""
    query = update.callback_query
    data = query.data or ""

    if data == "adm_view_pending":
        await pending_handler(update, context)
    elif data == "adm_view_users":
        await users_handler(update, context)
    elif data == "adm_view_stats":
        await stats_handler(update, context)
    elif data == "adm_trigger_scrape":
        await query.answer("Memulai scraping...")
        await scrape_handler(update, context)
    elif data.startswith("adm_approve:"):
        target = data.split(":", 1)[1]
        success, msg, _ = await access_control_agent.approve_user(target)
        await query.answer("User disetujui!" if success else "Gagal menyetujui")
        await query.edit_message_text(
            f"{query.message.text_html}\n\n<b>Tindakan:</b> ✅ {msg}",
            parse_mode="HTML"
        )
    elif data.startswith("adm_reject:"):
        target = data.split(":", 1)[1]
        success, msg, _ = await access_control_agent.reject_user(target)
        await query.answer("User ditolak!" if success else "Gagal menolak")
        await query.edit_message_text(
            f"{query.message.text_html}\n\n<b>Tindakan:</b> ⛔ {msg}",
            parse_mode="HTML"
        )

def setup_admin_bot(app) -> None:
    """Register all command and callback handlers for Admin Bot."""
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", start_handler))
    app.add_handler(CommandHandler("pending", pending_handler))
    app.add_handler(CommandHandler("users", users_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("scrape", scrape_handler))
    app.add_handler(CommandHandler("approve", approve_cmd_handler))
    app.add_handler(CommandHandler("reject", reject_cmd_handler))
    app.add_handler(CallbackQueryHandler(callback_query_handler))

def run_admin_bot_polling() -> None:
    """Run polling loop for dedicated Admin Bot."""
    token = settings.ADMIN_BOT_TOKEN
    if not token or token.startswith("mock_"):
        logger.info("ADMIN_BOT_TOKEN not configured; skipping dedicated Admin Bot thread.")
        return

    try:
        logger.info("Starting Dedicated Admin Bot polling (@nigaballsblotbot)...")
        app = ApplicationBuilder().token(token).concurrent_updates(True).build()
        setup_admin_bot(app)
        app.run_polling()
    except Exception as e:
        logger.error(f"Error during Admin Bot runtime: {e}", exc_info=True)
