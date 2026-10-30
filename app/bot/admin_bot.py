import asyncio
import html
from functools import wraps
from typing import Optional
from sqlalchemy import select, func
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import Job, Company, UserWhitelist, EmailQueue
from app.agents.access_control_agent import access_control_agent
from app.agents.scraper_agent import scraper_agent
from app.agents.self_healing_agent import self_healing_agent
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
        "serta menjalankan self-healing otomatis saat melaporkan bug.\n\n"
        "📋 <b>Daftar Perintah Admin:</b>\n"
        "• /pending - Tinjau pendaftaran user yang menunggu approval\n"
        "• /users - Kelola dan lihat semua user terdaftar\n"
        "• /stats - Ringkasan statistik database & scraper\n"
        "• /scrape - Trigger on-demand scraping sekarang\n"
        "• /approve &lt;id/username&gt; - Setujui user manual\n"
        "• /reject &lt;id/username&gt; - Tolak / suspend user\n\n"
        "🛠️ <b>Self-Healing & Auto-Deploy:</b>\n"
        "• /fix &lt;laporan bug&gt; - Lapor bug & auto-fix + auto-deploy\n"
        "• /heal - Diagnosa & perbaiki dari log error terkini\n"
        "• /logs - Lihat log sistem & stack trace error terbaru\n"
        "• /revert - Batalkan (rollback) fix terakhir"
    )
    keyboard = [
        [
            InlineKeyboardButton("⏳ User Pending", callback_data="adm_view_pending"),
            InlineKeyboardButton("👥 Semua User", callback_data="adm_view_users")
        ],
        [
            InlineKeyboardButton("📊 Statistik", callback_data="adm_view_stats"),
            InlineKeyboardButton("🚀 Trigger Scrape", callback_data="adm_trigger_scrape")
        ],
        [
            InlineKeyboardButton("🛠️ Self-Healing Dashboard", callback_data="adm_view_healing"),
            InlineKeyboardButton("📋 Log Sistem", callback_data="adm_view_logs")
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

# ----------------- SELF-HEALING & AUTO-DEPLOY HANDLERS -----------------

async def execute_self_healing_flow(target_msg, bug_report: str) -> None:
    """Executes the diagnose-and-heal pipeline with live progress, regression test, and deployment status."""
    status_msg = await target_msg.reply_text(
        "🛠️ <b>Memulai Protokol Self-Healing...</b>\n\n"
        "🔍 <i>Langkah 1/4: Membaca log sistem & memeriksa codebase...</i>",
        parse_mode="HTML"
    )

    async def update_progress(desc: str) -> None:
        try:
            await status_msg.edit_text(
                f"🛠️ <b>Self-Healing Sedang Berjalan...</b>\n\n{desc}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    result = await self_healing_agent.diagnose_and_heal(
        bug_report=bug_report,
        progress_callback=update_progress
    )

    if result.get("success"):
        commit_hash = result.get("commit_hash") or "latest"
        diff_preview = result.get("diff", "")[:900]
        escaped_diff = html.escape(diff_preview) if diff_preview else "Perubahan file terverifikasi"
        escaped_diag = html.escape(result.get("diagnosis", ""))
        escaped_expl = html.escape(result.get("explanation", ""))
        test_out = html.escape(result.get("test_output", "")[:250])

        report_text = (
            "✅ <b>Self-Healing Berhasil & Dideploy!</b>\n\n"
            f"🎯 <b>Diagnosa Akar Masalah:</b>\n<i>{escaped_diag}</i>\n\n"
            f"🔧 <b>Perbaikan Diterapkan:</b> <i>{escaped_expl}</i>\n"
            f"📁 <b>File Diperbaiki:</b> <code>{result.get('file_path')}</code>\n"
            f"🔖 <b>Commit Git:</b> <code>{commit_hash}</code>\n\n"
            f"📝 <b>Diff Patch:</b>\n<pre><code>{escaped_diff}</code></pre>\n\n"
            f"🧪 <b>Hasil Verifikasi Test Suite:</b>\n<code>{test_out}</code>\n\n"
            "🚀 <b>Deployment Status:</b> Kode diterapkan dan service <code>pkl-finder</code> direload otomatis."
        )
        keyboard = [
            [
                InlineKeyboardButton("⏪ Rollback Fix", callback_data=f"adm_revert:{commit_hash}"),
                InlineKeyboardButton("📋 Cek Log", callback_data="adm_view_logs")
            ],
            [
                InlineKeyboardButton("📊 Status Sistem", callback_data="adm_view_stats")
            ]
        ]
        await status_msg.edit_text(report_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        err_msg = html.escape(result.get("error", "Unknown error"))
        report_text = (
            "❌ <b>Self-Healing Tidak Berhasil</b>\n\n"
            f"⚠️ <b>Kendala:</b> <code>{err_msg}</code>\n\n"
            f"📁 <b>File Terkait:</b> <code>{result.get('file_path')}</code>\n\n"
            "🛡️ <i>Sistem aman: Semua perubahan file telah dibatalkan (auto-reverted) ke kondisi stabil sebelumnya.</i>"
        )
        keyboard = [
            [
                InlineKeyboardButton("📋 Periksa Log", callback_data="adm_view_logs"),
                InlineKeyboardButton("🔄 Coba Lagi", callback_data="adm_heal_recent")
            ]
        ]
        await status_msg.edit_text(report_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

@admin_guard
async def heal_cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual command: /fix or /heal <bug description>"""
    if context.args:
        bug_report = " ".join(context.args)
        await execute_self_healing_flow(update.effective_message, bug_report)
    else:
        recent_logs = self_healing_agent.get_recent_error_logs(max_lines=20)
        keyboard = [
            [
                InlineKeyboardButton("⚡ Auto-Fix Log Terakhir", callback_data="adm_heal_recent"),
                InlineKeyboardButton("📝 Ketik Laporan Manual", callback_data="adm_prompt_fix")
            ],
            [
                InlineKeyboardButton("📋 Lihat Full Log", callback_data="adm_view_logs")
            ]
        ]
        if recent_logs.strip():
            snippet = html.escape(recent_logs[-500:])
            text = (
                "🩺 <b>Self-Healing System - Error Terdeteksi</b>\n\n"
                f"Cuplikan log error terkini:\n<pre><code>{snippet}</code></pre>\n\n"
                "Pilih aksi di bawah, atau ketik langsung: <code>/fix &lt;deskripsi bug&gt;</code>"
            )
        else:
            text = (
                "🩺 <b>Self-Healing System Siap</b>\n\n"
                "Log sistem saat ini tidak menunjukkan error baru.\n"
                "Anda dapat melaporkan bug dengan cara:\n"
                "• Ketik: <code>/fix &lt;deskripsi masalah atau pesan error&gt;</code>\n"
                "• Atau klik <b>Ketik Laporan Manual</b> di bawah:"
            )
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

@admin_guard
async def logs_cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display recent system error logs."""
    logs = self_healing_agent.get_recent_error_logs(max_lines=25)
    if not logs.strip():
        logs = "Log kosong atau belum ada pesan error tercatat."
    snippet = html.escape(logs[-3000:])
    text = (
        "📋 <b>Log Sistem Terkini (pkl_finder):</b>\n\n"
        f"<pre><code>{snippet}</code></pre>"
    )
    keyboard = [
        [
            InlineKeyboardButton("⚡ Auto-Fix Error Terakhir", callback_data="adm_heal_recent"),
            InlineKeyboardButton("🔄 Refresh Log", callback_data="adm_view_logs")
        ]
    ]
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

@admin_guard
async def revert_cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manual command: /revert [commit_hash]"""
    commit_hash = context.args[0] if context.args else None
    msg = await update.message.reply_text("⏳ <i>Melakukan rollback kode dan me-reload service...</i>", parse_mode="HTML")
    success, info = await self_healing_agent.rollback(commit_hash)
    if success:
        await msg.edit_text(f"⏪ <b>Rollback Berhasil:</b>\n{info}", parse_mode="HTML")
    else:
        await msg.edit_text(f"❌ <b>Rollback Gagal:</b>\n<code>{info}</code>", parse_mode="HTML")

@admin_guard
async def healing_dashboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display self-healing diagnostics and history."""
    status = self_healing_agent.get_status()
    history = self_healing_agent.get_history(limit=3)

    text = (
        "🛠️ <b>Autonomous Self-Healing Dashboard</b>\n\n"
        f"• Status Agent: <b>{status['status']}</b>\n"
        f"• Total Runs: <code>{status['total_runs']}</code>\n"
        f"• Berhasil: 🟢 <code>{status['successful_runs']}</code> | Gagal: 🔴 <code>{status['failed_runs']}</code>\n"
        f"• AI Model: <code>{settings.PRIMARY_MODEL}</code>\n\n"
    )

    if history:
        text += "<b>Riwayat Self-Healing Terakhir:</b>\n"
        for h in history:
            icon = "🟢" if h.get("success") else "🔴"
            commit = f"[{h.get('commit_hash')}]" if h.get("commit_hash") else ""
            ts = h.get("timestamp", "")[:16].replace("T", " ")
            text += f"{icon} <code>{ts}</code> {commit} {h.get('file_path')}\n  <i>{h.get('explanation', '')[:60]}</i>\n\n"
    else:
        text += "<i>Belum ada riwayat self-healing yang tercatat.</i>\n\n"

    text += "💡 <i>Ketik <code>/fix &lt;deskripsi bug&gt;</code> untuk memicu perbaikan instan.</i>"

    keyboard = [
        [
            InlineKeyboardButton("⚡ Auto-Fix Dari Log", callback_data="adm_heal_recent"),
            InlineKeyboardButton("📝 Lapor Bug Manual", callback_data="adm_prompt_fix")
        ],
        [
            InlineKeyboardButton("📋 Cek Log Sistem", callback_data="adm_view_logs"),
            InlineKeyboardButton("🔄 Refresh", callback_data="adm_view_healing")
        ]
    ]

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

@admin_guard
async def admin_text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text bug reports sent directly to the Admin Bot."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    state = context.user_data.get("state")

    if state == "AWAITING_BUG_REPORT" or text.lower().startswith(("bug:", "fix:", "error:", "lapor:")):
        context.user_data["state"] = None
        for prefix in ["bug:", "fix:", "error:", "lapor:"]:
            if text.lower().startswith(prefix):
                text = text[len(prefix):].strip()
                break
        await execute_self_healing_flow(update.effective_message, text)

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
    elif data == "adm_view_healing":
        await healing_dashboard_handler(update, context)
    elif data == "adm_view_logs":
        await logs_cmd_handler(update, context)
    elif data == "adm_heal_recent":
        await query.answer("Memulai auto-fix dari log...")
        recent_logs = self_healing_agent.get_recent_error_logs(max_lines=30)
        report = f"Terjadi error pada log sistem:\n{recent_logs}"
        await execute_self_healing_flow(query.message, report)
    elif data == "adm_prompt_fix":
        context.user_data["state"] = "AWAITING_BUG_REPORT"
        await query.answer()
        await query.message.reply_text(
            "📝 <b>Silakan kirim pesan berisi deskripsi bug atau error yang Anda alami.</b>\n\n"
            "Contoh:\n"
            "<code>Scraping glints error timeout saat keyword Python</code>\n"
            "atau paste langsung potongan traceback error Anda.",
            parse_mode="HTML"
        )
    elif data.startswith("adm_revert:"):
        commit_hash = data.split(":", 1)[1]
        await query.answer("Memproses rollback...")
        success, info = await self_healing_agent.rollback(commit_hash)
        if success:
            await query.edit_message_text(f"{query.message.text_html}\n\n⏪ <b>Rollback Berhasil:</b>\n{info}", parse_mode="HTML")
        else:
            await query.edit_message_text(f"{query.message.text_html}\n\n❌ <b>Rollback Gagal:</b>\n<code>{info}</code>", parse_mode="HTML")
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
    app.add_handler(CommandHandler(["start", "help", "menu"], start_handler))
    app.add_handler(CommandHandler("pending", pending_handler))
    app.add_handler(CommandHandler("users", users_handler))
    app.add_handler(CommandHandler(["stats", "stat"], stats_handler))
    app.add_handler(CommandHandler("scrape", scrape_handler))
    app.add_handler(CommandHandler("approve", approve_cmd_handler))
    app.add_handler(CommandHandler("reject", reject_cmd_handler))
    app.add_handler(CommandHandler(["heal", "fix", "selfheal"], heal_cmd_handler))
    app.add_handler(CommandHandler(["logs", "log"], logs_cmd_handler))
    app.add_handler(CommandHandler("revert", revert_cmd_handler))
    app.add_handler(CommandHandler("healing", healing_dashboard_handler))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_message_handler))

def run_admin_bot_polling() -> None:
    """Run polling loop for dedicated Admin Bot in background thread with clean event loop."""
    token = settings.ADMIN_BOT_TOKEN
    if not token or token.startswith("mock_"):
        logger.info("ADMIN_BOT_TOKEN not configured; skipping dedicated Admin Bot thread.")
        return

    try:
        logger.info("Starting Dedicated Admin Bot polling (@nigaballsblotbot)...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = ApplicationBuilder().token(token).concurrent_updates(True).build()
        setup_admin_bot(app)
        # stop_signals=None prevents 'set_wakeup_fd only works in main thread' in background thread
        app.run_polling(stop_signals=None, poll_interval=1.0)
    except Exception as e:
        logger.error(f"Error during Admin Bot runtime: {e}", exc_info=True)
