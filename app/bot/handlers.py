import json
import logging
from functools import wraps
from typing import Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from app.config.settings import settings
from app.services.job_service import JobService
from app.database.models import Job, AIScore
from app.ai.evaluator import CANDIDATE_PROFILE
from app.utils.logger import logger

job_service = JobService()

def admin_only(func):
    """Decorator to restrict access to the configured admin ID."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        if user_id != settings.TELEGRAM_ADMIN_ID:
            logger.warning(f"Unauthorized access attempt by user ID {user_id}")
            await update.effective_message.reply_text(
                "⛔️ <b>Akses Ditolak:</b> Anda tidak diizinkan menggunakan bot ini.",
                parse_mode="HTML"
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def format_job_message(job: Job) -> str:
    """Format a job vacancy into a clean, premium HTML message for Telegram."""
    ai_score = job.ai_score
    score_str = f"📈 <b>Match Score:</b> <code>{ai_score.score}/100</code>" if ai_score else "📊 <b>Score:</b> N/A"
    
    reasons = []
    matched = []
    missing = []
    
    if ai_score:
        try:
            reasons = json.loads(ai_score.reason) if ai_score.reason else []
        except Exception:
            reasons = [ai_score.reason] if ai_score.reason else []
            
        try:
            matched = json.loads(ai_score.matched_skills) if ai_score.matched_skills else []
        except Exception:
            matched = [ai_score.matched_skills] if ai_score.matched_skills else []
            
        try:
            missing = json.loads(ai_score.missing_skills) if ai_score.missing_skills else []
        except Exception:
            missing = [ai_score.missing_skills] if ai_score.missing_skills else []
            
    reasons_list = "\n".join([f"• {r}" for r in reasons]) if reasons else "• Tidak ada detail alasan."
    matched_str = ", ".join(matched) if matched else "Tidak ada"
    missing_str = ", ".join(missing) if missing else "Tidak ada"
    summary = ai_score.summary if ai_score else "Tidak ada analisis."

    return (
        f"🚀 <b>PKL / Internship Baru Ditemukan!</b>\n\n"
        f"🏢 <b>Perusahaan:</b> <code>{job.company_name}</code>\n"
        f"💼 <b>Posisi:</b> <b>{job.title}</b>\n"
        f"📍 <b>Lokasi:</b> <code>{job.location}</code>\n"
        f"🌐 <b>Sumber:</b> <code>{job.source.upper()}</code>\n"
        f"💰 <b>Gaji:</b> <code>{job.salary or 'Tidak disebutkan'}</code>\n"
        f"⏱ <b>Tipe:</b> <code>{job.employment_type or 'Internship'} ({job.work_mode or 'On-site'})</code>\n"
        f"{score_str}\n\n"
        f"✅ <b>Matched Skills:</b> {matched_str}\n"
        f"❌ <b>Missing Skills:</b> {missing_str}\n\n"
        f"📝 <b>Analisis AI:</b>\n<i>{summary}</i>\n\n"
        f"🎯 <b>Alasan Kelayakan:</b>\n{reasons_list}"
    )

def get_job_keyboard(job: Job, is_fav: bool = False) -> InlineKeyboardMarkup:
    """Create inline keyboard with actions (Favorite toggle + View link)."""
    fav_text = "❤️ Hapus Favorit" if is_fav else "⭐ Favoritkan"
    fav_callback = f"unfav:{job.id}" if is_fav else f"fav:{job.id}"
    
    keyboard = [
        [
            InlineKeyboardButton(fav_text, callback_data=fav_callback),
            InlineKeyboardButton("🔗 Buka Lowongan", url=job.url)
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

@admin_only
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message on /start."""
    welcome_text = (
        "🤖 <b>Halo! Selamat datang di PKL Finder Bot!</b>\n\n"
        "Saya adalah asisten AI pribadi Anda yang memantau lowongan magang/PKL dari berbagai portal lowongan secara real-time.\n\n"
        "Gunakan perintah /help untuk melihat daftar perintah yang tersedia."
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

@admin_only
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send list of commands on /help."""
    help_text = (
        "🛠 <b>Daftar Perintah PKL Finder Bot:</b>\n\n"
        "🔍 /search - Jalankan scraping lowongan baru secara instan\n"
        "📈 /latest - Tampilkan magang/PKL rekomendasi terbaru\n"
        "👤 /profile - Lihat profil kandidat AI Anda\n"
        "📊 /stats - Tampilkan statistik database lowongan\n"
        "🔄 /recheck - Evaluasi ulang kecocokan semua lowongan di database\n"
        "⚙️ /settings - Tampilkan konfigurasi lingkungan bot\n"
        "📜 /history - Riwayat lowongan yang direkomendasikan sebelumnya\n"
        "⭐ /favorites - Tampilkan daftar lowongan terfavorit"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

@admin_only
async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger manual scrape and matching, send new recommendations."""
    await update.message.reply_text("⏳ <i>Sedang melakukan pencarian lowongan magang baru...</i>", parse_mode="HTML")
    
    try:
        new_jobs = await job_service.run_scraping_and_matching()
        if not new_jobs:
            await update.message.reply_text("✅ Pencarian selesai. Tidak ditemukan lowongan baru yang cocok.")
            return

        await update.message.reply_text(f"🎉 <b>Ditemukan {len(new_jobs)} lowongan baru yang cocok!</b> Sending details...", parse_mode="HTML")
        for job in new_jobs:
            text = format_job_message(job)
            keyboard = get_job_keyboard(job, is_fav=False)
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Error executing manual search: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Terjadi kesalahan saat melakukan pencarian: <code>{str(e)}</code>", parse_mode="HTML")

@admin_only
async def latest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the latest 5 matched jobs."""
    try:
        jobs = await job_service.get_latest_jobs(limit=5, recommended_only=True)
        if not jobs:
            await update.message.reply_text("📭 Belum ada lowongan rekomendasi di database.")
            return

        await update.message.reply_text("📋 <b>5 Lowongan Rekomendasi Terbaru:</b>", parse_mode="HTML")
        for job in jobs:
            text = format_job_message(job)
            keyboard = get_job_keyboard(job, is_fav=False)
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error fetching latest jobs: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Terjadi kesalahan: <code>{str(e)}</code>", parse_mode="HTML")

@admin_only
async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show candidate profile used for AI evaluation."""
    profile_text = (
        "👤 <b>Profil Pencocokan AI (Resume/CV):</b>\n"
        f"<pre>{CANDIDATE_PROFILE.strip()}</pre>"
    )
    await update.message.reply_text(profile_text, parse_mode="HTML")

@admin_only
async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show database statistics."""
    try:
        stats = await job_service.get_db_stats()
        
        breakdown_text = ""
        for src, count in stats["source_breakdown"].items():
            breakdown_text += f"- {src.upper()}: <code>{count}</code>\n"
            
        stats_text = (
            "📊 <b>Statistik Database PKL Finder:</b>\n\n"
            f"📦 Total Lowongan Disimpan: <code>{stats['total_jobs']}</code>\n"
            f"🎯 Lolos Evaluasi AI (Recommended): <code>{stats['recommended_jobs']}</code>\n"
            f"⭐ Disimpan ke Favorit: <code>{stats['favorites_count']}</code>\n\n"
            f"🌐 <b>Rincian Berdasarkan Sumber:</b>\n{breakdown_text or 'Belum ada data'}"
        )
        await update.message.reply_text(stats_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Terjadi kesalahan: <code>{str(e)}</code>", parse_mode="HTML")

@admin_only
async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show environment configurations."""
    # Hide sensitive API Keys
    api_key_masked = "Not Configured"
    if settings.OPENROUTER_API_KEY and not settings.OPENROUTER_API_KEY.startswith("your_"):
        api_key_masked = f"{settings.OPENROUTER_API_KEY[:6]}...{settings.OPENROUTER_API_KEY[-4:]}"
        
    bot_token_masked = "Not Configured"
    if settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("your_"):
        bot_token_masked = f"{settings.TELEGRAM_BOT_TOKEN[:10]}...{settings.TELEGRAM_BOT_TOKEN[-5:]}"

    settings_text = (
        "⚙️ <b>Konfigurasi Sistem Bot (.env):</b>\n\n"
        f"🤖 <b>Model AI:</b> <code>{settings.OPENROUTER_MODEL}</code>\n"
        f"🔑 <b>OpenRouter Key:</b> <code>{api_key_masked}</code>\n"
        f"Token Bot Telegram: <code>{bot_token_masked}</code>\n"
        f"Admin Telegram ID: <code>{settings.TELEGRAM_ADMIN_ID}</code>\n"
        f"Database URL: <code>{settings.DATABASE_URL}</code>\n\n"
        f"⏰ Interval Scan: <code>{settings.CHECK_INTERVAL_MINUTES} Menit</code>\n"
        f"⚖️ Ambang Batas Skor (Threshold): <code>{settings.SCORE_THRESHOLD}</code>\n"
        f"Limit Scraping per Sesi: <code>{settings.MAX_JOBS_PER_RUN}</code>\n"
        f"Timezone: <code>{settings.TIMEZONE}</code>\n\n"
        f"🔍 <b>Kata Kunci Pencarian:</b>\n<code>{settings.SEARCH_KEYWORDS}</code>\n\n"
        f"📍 <b>Target Lokasi:</b>\n<code>{settings.SEARCH_LOCATIONS}</code>"
    )
    await update.message.reply_text(settings_text, parse_mode="HTML")

@admin_only
async def recheck_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger manual AI recheck on all database records."""
    await update.message.reply_text("🔄 <i>Memulai evaluasi ulang semua lowongan dalam database. Proses ini memakan waktu...</i>", parse_mode="HTML")
    try:
        new_jobs = await job_service.recheck_all_jobs()
        if not new_jobs:
            await update.message.reply_text("✅ Evaluasi selesai. Tidak ada lowongan yang berubah menjadi rekomendasi.")
            return

        await update.message.reply_text(f"🎉 <b>Re-evaluasi Selesai! Ditemukan {len(new_jobs)} lowongan yang direkomendasikan:</b>", parse_mode="HTML")
        for job in new_jobs:
            text = format_job_message(job)
            keyboard = get_job_keyboard(job, is_fav=False)
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error during recheck: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Terjadi kesalahan: <code>{str(e)}</code>", parse_mode="HTML")

@admin_only
async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show last 10 recommended jobs from logs/history."""
    try:
        histories = await job_service.get_history(limit=10)
        if not histories:
            await update.message.reply_text("📭 Belum ada riwayat evaluasi lowongan.")
            return

        history_text = "📜 <b>10 Riwayat Aktivitas Lowongan Terakhir:</b>\n\n"
        for job, hist in histories:
            score = f"({job.ai_score.score}/100)" if job.ai_score else ""
            history_text += (
                f"- [{hist.created_at.strftime('%Y-%m-%d %H:%M')}] "
                f"<b>{hist.action.upper()}</b>: {job.title} di <i>{job.company_name}</i> {score}\n"
            )
        await update.message.reply_text(history_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error fetching history: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Terjadi kesalahan: <code>{str(e)}</code>", parse_mode="HTML")

@admin_only
async def favorites_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of favorite jobs."""
    try:
        jobs = await job_service.get_favorites()
        if not jobs:
            await update.message.reply_text("⭐ Daftar favorit Anda masih kosong. Tekan tombol 'Favoritkan' pada lowongan yang Anda sukai.")
            return

        await update.message.reply_text(f"⭐️ <b>Daftar Lowongan Favorit Anda ({len(jobs)}):</b>", parse_mode="HTML")
        for job in jobs:
            text = format_job_message(job)
            keyboard = get_job_keyboard(job, is_fav=True)
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error fetching favorites: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Terjadi kesalahan: <code>{str(e)}</code>", parse_mode="HTML")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback button clicks (Favoriting / Unfavoriting)."""
    query = update.callback_query
    if not query or not query.data:
        return
        
    await query.answer()
    
    # Authorized admin check
    if query.from_user.id != settings.TELEGRAM_ADMIN_ID:
        logger.warning(f"Unauthorized callback query from user ID {query.from_user.id}")
        return

    data = query.data
    try:
        # Resolve command and job_id
        action, job_id_str = data.split(":")
        job_id = int(job_id_str)
        
        from app.database.db import async_session_maker
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        async with async_session_maker() as session:
            stmt = select(Job).options(selectinload(Job.ai_score)).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalar_one_or_none()
            
        if not job:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("❌ Lowongan tidak ditemukan.")
            return

        if action == "fav":
            success = await job_service.add_favorite(job) if False else await job_service.add_favorite(job_id)
            if success:
                keyboard = get_job_keyboard(job, is_fav=True)
                await query.edit_message_reply_markup(reply_markup=keyboard)
                logger.info(f"Job {job_id} favorited successfully.")
        elif action == "unfav":
            success = await job_service.remove_favorite(job_id)
            if success:
                keyboard = get_job_keyboard(job, is_fav=False)
                await query.edit_message_reply_markup(reply_markup=keyboard)
                logger.info(f"Job {job_id} unfavorited successfully.")
                
    except Exception as e:
        logger.error(f"Error processing callback: {e}", exc_info=True)

def setup_bot(application) -> None:
    """Registers all commands and handlers with the PTB Application."""
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("search", search_handler))
    application.add_handler(CommandHandler("latest", latest_handler))
    application.add_handler(CommandHandler("profile", profile_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CommandHandler("recheck", recheck_handler))
    application.add_handler(CommandHandler("settings", settings_handler))
    application.add_handler(CommandHandler("history", history_handler))
    application.add_handler(CommandHandler("favorites", favorites_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))
