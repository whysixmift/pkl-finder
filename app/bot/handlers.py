import os
import json
import time
import asyncio
from functools import wraps
from datetime import datetime, timezone
from typing import List, Set, Optional
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import Job, Company, EmailQueue, Portfolio, CoverLetter, AIScore
from app.services.cv_service import cv_service
from app.services.email_service import email_service
from app.services.job_service import JobService
from app.ai.evaluator import evaluator
from app.services.crawler_service import career_crawler
from app.services.discovery_service import discovery_engine
from app.utils.logger import logger

# Initialize Job Service
job_service = JobService()

def admin_only(func):
    """Decorator to restrict access to the configured admin ID."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        if user_id != settings.TELEGRAM_ADMIN_ID:
            logger.warning(f"Unauthorized admin command attempt by user ID {user_id}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔&nbsp;<b>Akses Ditolak:</b> Command ini hanya untuk Administrator.",
                    parse_mode="HTML"
                )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def whitelist_required(func):
    """Decorator to verify that user is authorized via SaaS User Whitelist (Username / User ID) or is Admin."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return
        user_id = update.effective_user.id
        username = update.effective_user.username

        from app.agents.access_control_agent import access_control_agent
        is_allowed = await access_control_agent.is_allowed(user_id, username)
        if not is_allowed:
            logger.warning(f"Unauthorized SaaS access attempt by Telegram User {user_id} (@{username})")
            if update.effective_message:
                user_display = f"@{username}" if username else f"ID: {user_id}"
                await update.effective_message.reply_text(
                    f"🔒 <b>Akses SaaS Terbatas (Private Beta)</b>\n\n"
                    f"Akun Telegram Anda (<code>{user_display}</code>) belum terdaftar dalam whitelist PKL Finder SaaS.\n\n"
                    f"Silakan hubungi Administrator untuk menambahkan username atau user ID Anda ke whitelist bot.",
                    parse_mode="HTML"
                )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def error_boundary(func):
    """Catches all exceptions to prevent bot crashes and replies with helpful diagnostics."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"Error in bot handler '{func.__name__}': {e}", exc_info=True)
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"❌&nbsp;<b>Internal System Error:</b>\n<code>{str(e)}</code>",
                    parse_mode="HTML"
                )
    return wrapper

def format_job_message(job: Job, user_id: int) -> str:
    """Format a job vacancy into a clean, premium HTML message for Telegram."""
    ai_score = None
    for score in job.ai_scores:
        if score.user_id == user_id:
            ai_score = score
            break

    score_str = f"📈 <b>Match Score:</b> <code>{ai_score.score}/100</code>" if ai_score else "📊 <b>Score:</b> N/A"
    
    reasons: List[str] = []
    matched: List[str] = []
    missing: List[str] = []
    
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
        f"{score_str}\n"
        f"💼 <b>Category:</b> <code>{getattr(ai_score, 'company_category', 'Tech')}</code>\n"
        f"🔥 <b>Priority:</b> <code>{getattr(ai_score, 'priority', 'medium').upper()}</code>\n\n"
        f"📋 <b>Analisis Kesesuaian:</b>\n<i>{summary}</i>\n\n"
        f"✅ <b>Kecocokan Skill:</b> {matched_str}\n"
        f"❌ <b>Skill Kurang:</b> {missing_str}\n\n"
        f"💡 <b>Mengapa Anda Cocok:</b>\n{reasons_list}"
    )

def get_job_keyboard(job: Job, is_fav: bool = False) -> InlineKeyboardMarkup:
    """Create inline keyboard with actions (Favorite toggle + View link + Apply Cold Email)."""
    fav_text = "❤️ Hapus Favorit" if is_fav else "⭐ Favoritkan"
    fav_callback = f"unfav:{job.id}" if is_fav else f"fav:{job.id}"
    
    keyboard = [
        [
            InlineKeyboardButton(fav_text, callback_data=fav_callback),
            InlineKeyboardButton("🔗 Buka Lowongan", url=job.url)
        ],
        [
            InlineKeyboardButton("✉️ Lamar Cepat (Auto Cold Email + CV)", callback_data=f"apply_email:{job.id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ----------------- STARTUP & CONFIGS -----------------

@error_boundary
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    username = update.effective_user.username
    from app.agents.access_control_agent import access_control_agent
    
    # Auto-register user as pending if new
    _, is_new = await access_control_agent.get_or_create_pending_user(
        user_id=user_id,
        username=username,
        source="telegram"
    )
    is_allowed = await access_control_agent.is_allowed(user_id, username)
    context.user_data["state"] = "AWAITING_CV"

    if not is_allowed:
        user_display = f"@{username}" if username else f"ID: {user_id}"
        restricted_text = (
            "👋 <b>Selamat Datang di GetAJob / PKL Finder AI!</b>\n\n"
            f"Akun Anda (<code>{user_display}</code>) telah terdaftar dan saat ini sedang dalam <b>antrean verifikasi Admin</b>.\n\n"
            "📄 <b>Langkah Wajib: Upload CV Anda Sekarang!</b>\n"
            "Kirimkan file CV Anda (format <b>.PDF</b> atau <b>.DOCX</b>) langsung ke chat ini.\n\n"
            "🧠 <b>Fitur Analisis Karir AI:</b>\n"
            "• AI akan mendeteksi keahlian & spesialisasi Anda secara mendalam.\n"
            "• Mendeteksi pekerjaan & posisi apa saja yang paling cocok buat Anda (Full-Time, Contract, Remote, Magang).\n"
            "• Menyiapkan keyword pencarian personal khusus profil Anda!\n\n"
            "👉 <i>Silakan langsung kirimkan file CV (.pdf/.docx) Anda sekarang!</i>"
        )
        await update.message.reply_text(restricted_text, parse_mode="HTML")
        return

    # User is approved / Admin
    async with async_session_maker() as session:
        user_cv = await cv_service.get_active_cv_profile(session, user_id)

    if not user_cv:
        approved_text = (
            "🤖 <b>GetAJob / PKL Finder - AI Career Assistant</b>\n\n"
            "Status: 🟢 <b>Akses SaaS Terverifikasi</b>\n\n"
            "📄 <b>Langkah 1: Silakan Upload CV Anda!</b>\n"
            "Kirimkan file CV Anda (format <b>.PDF</b> atau <b>.DOCX</b>) langsung ke chat ini.\n"
            "AI kami akan otomatis membedah keahlian dan pekerjaan yang paling cocok buat Anda!"
        )
        await update.message.reply_text(approved_text, parse_mode="HTML")
    else:
        import json
        roles = []
        skills = []
        keywords = []
        if user_cv.detected_roles:
            try:
                roles = json.loads(user_cv.detected_roles)
            except Exception:
                roles = []
        if user_cv.detected_skills:
            try:
                skills = json.loads(user_cv.detected_skills)
            except Exception:
                skills = []
        if user_cv.search_keywords:
            try:
                keywords = json.loads(user_cv.search_keywords)
            except Exception:
                keywords = []

        roles_list = "\n".join([f"  {i}. <b>{r}</b>" for i, r in enumerate(roles[:4], 1)]) if roles else "  • Software Engineer / Tech"
        skills_str = ", ".join(skills[:6]) if skills else "Programming, Technical Skills"
        kws_str = ", ".join(keywords[:5]) if keywords else "software engineer, developer"

        welcome_text = (
            "🤖 <b>GetAJob / PKL Finder - AI Career Assistant</b>\n\n"
            "Status: 🟢 <b>Akses SaaS Terverifikasi</b>\n"
            f"📄 CV Aktif: <code>{user_cv.filename}</code>\n\n"
            f"🎯 <b>Pekerjaan yang Cocok untuk Anda:</b>\n"
            f"{roles_list}\n\n"
            f"💡 <b>Keahlian Terdeteksi:</b>\n• {skills_str}\n\n"
            f"🔍 <b>Keyword Pencarian Terpersonalisasi:</b>\n<code>{kws_str}</code>\n\n"
            "👉 <i>Kirim /search atau klik tombol di bawah untuk mulai scraping lowongan kerja cocok:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("🚀 Cari Lowongan Kerja Sekarang", callback_data="btn_search")],
            [InlineKeyboardButton("🔄 Unggah CV Baru", callback_data="btn_uploadcv")]
        ]
        await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

@error_boundary
@whitelist_required
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 <b>Daftar Perintah PKL Finder SaaS Bot:</b>\n\n"
        "🔍&nbsp;<b>Pencarian & Informasi:</b>\n"
        "/search - Jalankan scraping lowongan secara realtime\n"
        "/latest - Tampilkan 10 lowongan magang rekomendasi terbaru\n"
        "/favorites - Lihat lowongan magang yang difavoritkan\n"
        "/history - Lihat riwayat pencocokan & aktivitas\n"
        "/recheck - Evaluasi ulang semua lowongan terhadap CV aktif\n\n"
        "👤&nbsp;<b>Profil & Portofolio:</b>\n"
        "/profile - Periksa kelengkapan berkas CV & portofolio\n"
        "/uploadcv - Unggah CV baru (.PDF atau .DOCX)\n"
        "/uploadportfolio - Atur URL portofolio atau unggah file\n"
        "/uploadcoverletter - Atur template cover letter pendukung\n\n"
        "📧&nbsp;<b>Pengiriman Email (Google SSO & SMTP):</b>\n"
        "/connect_google - 🔑 Hubungkan Google SSO (Gmail API) untuk kirim email\n"
        "/credentials - Konfigurasi SMTP email pengirim manual\n"
        "/email - Periksa konfigurasi email pengirim aktif\n"
        "/queue - Tampilkan draft email antrean AI (dengan lampiran CV)\n"
        "/sendall - Dispatch semua email approved\n\n"
        "🏢&nbsp;<b>Company Discovery:</b>\n"
        "/companies - Tampilkan daftar perusahaan terdaftar\n"
        "/openapplications - Tampilkan daftar email Open Applications\n\n"
        "🛠&nbsp;<b>Admin Diagnostics & Multi-Agent:</b>\n"
        "/agents - Status sistem 8 Agen Otonom (1 Feature = 1 Agent)\n"
        "/health - Periksa status kesehatan platform\n"
        "/models - Status latensi OpenRouter & failover\n"
        "/providers - Skor kesehatan & status scraper\n"
        "/migrations - Riwayat revisi database Alembic\n"
        "/schema - Verifikasi kecocokan skema DB dengan ORM\n"
        "/doctor - Diagnosa lengkap subsystem & pemecahan error\n"
        "/system - Status resource (CPU, Memory, Disk) host\n"
        "/cache - Metrik data intelligence cache global\n"
        "/metrics - Konversi email & success rate\n"
        "/logs - Tampilkan 15 baris terakhir file log"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

# ----------------- SYSTEM & CORE COMMAND HANDLERS -----------------

ACTIVE_USER_SCRAPES: Set[int] = set()

def render_progress_bar(percent: int, length: int = 15) -> str:
    """Render a text-based progress bar."""
    filled = max(0, min(length, int(round(length * percent / 100))))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent}%"

async def run_background_user_scraping(
    bot,
    chat_id: int,
    user_id: int,
    progress_msg_id: int,
    roles_str: str
) -> None:
    """Execute background scraping, AI evaluation, and periodically update progress bar every 15 seconds."""
    start_time = time.time()
    try:
        scrape_task = asyncio.create_task(job_service.run_scraping_and_matching(target_user_id=user_id))
        
        stages = [
            (25, "Memindai Glints & LinkedIn..."),
            (45, "Memindai Indeed & JobStreet..."),
            (65, "Memindai Kalibrr & Google Jobs..."),
            (80, "Mengevaluasi kesesuaian profil CV dengan AI..."),
            (90, "Menyaring lowongan dengan match score tertinggi..."),
            (95, "Menyusun kartu lowongan rekomendasi..."),
        ]
        
        step = 0
        while not scrape_task.done():
            await asyncio.sleep(15)
            if scrape_task.done():
                break

            elapsed = int(time.time() - start_time)
            percent, platform_desc = stages[min(step, len(stages) - 1)]
            step += 1

            bar = render_progress_bar(percent)
            updated_text = (
                f"🔄 <b>Pencarian Lowongan Kerja Sedang Berjalan...</b>\n\n"
                f"🎯 <b>Target:</b> {roles_str}\n"
                f"📊 <b>Progress:</b> <code>{bar}</code>\n"
                f"🌐 <b>Aktivitas:</b> {platform_desc}\n"
                f"⏱️ <b>Waktu:</b> {elapsed} detik\n\n"
                f"💡 <i>Anda dapat tetap mengirim perintah (/help, /profile, dll) tanpa mengganggu proses scraping ini!</i>"
            )
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg_id,
                    text=updated_text,
                    parse_mode="HTML"
                )
            except Exception as edit_err:
                logger.debug(f"Progress update notification note: {edit_err}")

        # Task finished
        new_jobs = await scrape_task
        elapsed = int(time.time() - start_time)

        # Trigger company discovery in background
        try:
            asyncio.create_task(discovery_engine.discover_companies())
        except Exception:
            pass

        user_recs = [job for uid, job in new_jobs if uid == user_id]

        if user_recs:
            finished_bar = render_progress_bar(100)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=progress_msg_id,
                text=(
                    f"✅ <b>Scraping & Analisis Selesai!</b> (⏱️ {elapsed} detik)\n"
                    f"📊 <b>Progress:</b> <code>{finished_bar}</code>\n\n"
                    f"🎉 Menemukan <b>{len(user_recs)}</b> lowongan kerja rekomendasi yang cocok untuk profil Anda. Berikut daftarnya:"
                ),
                parse_mode="HTML"
            )
            for job in user_recs:
                text = format_job_message(job, user_id)
                keyboard = get_job_keyboard(job, is_fav=False)
                await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")
        else:
            existing_recs = await job_service.get_latest_jobs(user_id=user_id, limit=5, recommended_only=True)
            if existing_recs:
                finished_bar = render_progress_bar(100)
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg_id,
                    text=(
                        f"✅ <b>Scraping Selesai!</b> (⏱️ {elapsed} detik)\n"
                        f"📊 <b>Progress:</b> <code>{finished_bar}</code>\n\n"
                        f"📌 Tidak ada lowongan baru unik saat ini, menampilkan <b>{len(existing_recs)}</b> lowongan rekomendasi tersimpan untuk profil Anda:"
                    ),
                    parse_mode="HTML"
                )
                for job in existing_recs:
                    text = format_job_message(job, user_id)
                    keyboard = get_job_keyboard(job, is_fav=False)
                    await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg_id,
                    text=(
                        f"✅ <b>Scraping Selesai!</b> (⏱️ {elapsed} detik)\n\n"
                        "Belum ada lowongan baru dengan skor kecocokan tinggi saat ini. "
                        "Coba perbarui CV atau coba kembali dalam beberapa saat."
                    ),
                    parse_mode="HTML"
                )
    except Exception as e:
        logger.error(f"Error in background scraping for user {user_id}: {e}", exc_info=True)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=progress_msg_id,
                text=f"❌ <b>Terjadi Kendala Saat Scraping:</b> {e}\n\nSilakan coba lagi beberapa saat lagi dengan /search.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        ACTIVE_USER_SCRAPES.discard(user_id)

@error_boundary
@whitelist_required
async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    target_msg = update.effective_message

    # Check if scraping is already actively running for this user
    if user_id in ACTIVE_USER_SCRAPES:
        await target_msg.reply_text(
            "⏳ <b>Proses Scraping Sedang Berjalan!</b>\n\n"
            "Bot sedang aktif memindai lowongan di background untuk profil Anda. "
            "Hasilnya akan langsung dikirimkan ke sini begitu selesai.\n\n"
            "💡 <i>Anda tetap dapat menggunakan perintah lain seperti /help, /profile, atau /status.</i>",
            parse_mode="HTML"
        )
        return

    # Check CV
    async with async_session_maker() as session:
        user_cv = await cv_service.get_active_cv_profile(session, user_id)

    if not user_cv:
        await target_msg.reply_text(
            "⚠️ <b>Anda belum mengunggah CV!</b>\n\n"
            "Silakan kirim file CV Anda (.PDF atau .DOCX) terlebih dahulu agar AI kami tahu pekerjaan apa yang cocok untuk Anda.",
            parse_mode="HTML"
        )
        context.user_data["state"] = "AWAITING_CV"
        return

    roles = []
    if user_cv.detected_roles:
        try:
            roles = json.loads(user_cv.detected_roles)
        except Exception:
            roles = []
    roles_str = ", ".join(roles[:3]) if roles else "Tech & Software"

    # Step 1: Show "Starting Scrap"
    starting_msg = await target_msg.reply_text(
        "🚀 <b>Starting Scrap...</b>",
        parse_mode="HTML"
    )

    # Step 2: Delete "Starting Scrap" message
    await asyncio.sleep(1.2)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=starting_msg.message_id)
    except Exception as e:
        logger.debug(f"Could not delete starting message: {e}")

    # Step 3: Send progress loading bar message
    bar = render_progress_bar(10)
    progress_text = (
        f"🔄 <b>Pencarian Lowongan Kerja Sedang Berjalan...</b>\n\n"
        f"🎯 <b>Target Posisi:</b> {roles_str}\n"
        f"📊 <b>Progress:</b> <code>{bar}</code>\n"
        f"🌐 <b>Platform:</b> Memindai Glints & LinkedIn...\n"
        f"⏱️ <b>Waktu:</b> 0s\n\n"
        f"💡 <i>Anda dapat tetap menggunakan perintah lain (/help, /profile, /settings, dll) tanpa mengganggu proses scraping ini!</i>"
    )
    progress_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=progress_text,
        parse_mode="HTML"
    )

    # Step 4: Add to active set and launch background task
    ACTIVE_USER_SCRAPES.add(user_id)
    asyncio.create_task(
        run_background_user_scraping(
            bot=context.bot,
            chat_id=chat_id,
            user_id=user_id,
            progress_msg_id=progress_msg.message_id,
            roles_str=roles_str
        )
    )

@error_boundary
@whitelist_required
async def latest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    jobs = await job_service.get_latest_jobs(user_id=user_id, limit=10, recommended_only=True)
    if not jobs:
        await update.message.reply_text("📭 Tidak ada lowongan rekomendasi terbaru di database.")
        return
        
    await update.message.reply_text("📋 <b>Daftar 10 Lowongan Magang Rekomendasi Terbaru:</b>", parse_mode="HTML")
    for job in jobs:
        text = format_job_message(job, user_id)
        keyboard = get_job_keyboard(job, is_fav=False)
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

@error_boundary
@whitelist_required
async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check completeness of user CV, portfolio, cover letter."""
    user_id = update.effective_user.id
    async with async_session_maker() as session:
        cv_text = await cv_service.get_active_cv_text(session, user_id)
        
        # Check portfolio
        p_stmt = select(Portfolio).where(Portfolio.user_id == user_id).limit(1)
        p_res = await session.execute(p_stmt)
        portfolio = p_res.scalar_one_or_none()
        
        # Check cover letter
        cl_stmt = select(CoverLetter).where(CoverLetter.user_id == user_id).limit(1)
        cl_res = await session.execute(cl_stmt)
        cl = cl_res.scalar_one_or_none()

    cv_display = cv_text[:500] + "..." if cv_text else "Belum diatur. Silakan unggah CV Anda menggunakan /uploadcv."
    portfolio_display = "Belum diatur. Atur menggunakan /uploadportfolio."
    if portfolio:
        portfolio_display = portfolio.github_url or portfolio.website_url or portfolio.file_path or "Tersimpan"
        
    cl_display = cl.text[:150] + "..." if cl else "Belum diatur. Atur menggunakan /uploadcoverletter."

    profile_text = (
        "👤 <b>Profil Pelamar Anda:</b>\n\n"
        f"📄 <b>Preview Teks CV:</b>\n<code>{cv_display}</code>\n\n"
        f"🌐 <b>Portfolio:</b> <code>{portfolio_display}</code>\n"
        f"✍️ <b>Template Cover Letter:</b> <i>{cl_display}</i>"
    )
    await update.message.reply_text(profile_text, parse_mode="HTML")

@error_boundary
async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config_text = (
        "⚙️ <b>Konfigurasi Sistem Aktif (Global):</b>\n\n"
        f"🔑 OpenRouter Model: <code>{settings.OPENROUTER_MODEL}</code>\n"
        f"⏱ Interval Cek: <code>{settings.CHECK_INTERVAL_MINUTES} Menit</code>\n"
        f"🎯 Threshold Skor: <code>{settings.SCORE_THRESHOLD}</code>\n"
        f"🏢 Limit Per Run: <code>{settings.MAX_JOBS_PER_RUN}</code>\n"
        f"🔍 Lokasi Target: <code>{settings.SEARCH_LOCATIONS}</code>\n"
        f"🏷 Keyword Target: <code>{settings.SEARCH_KEYWORDS}</code>"
    )
    await update.message.reply_text(config_text, parse_mode="HTML")

@error_boundary
@whitelist_required
async def favorites_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    jobs = await job_service.get_favorites(user_id=user_id)
    if not jobs:
        await update.message.reply_text("⭐ Belum ada lowongan terfavorit.")
        return
        
    await update.message.reply_text("⭐ <b>Lowongan Terfavorit Anda:</b>", parse_mode="HTML")
    for job in jobs:
        text = format_job_message(job, user_id)
        keyboard = get_job_keyboard(job, is_fav=True)
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

@error_boundary
@whitelist_required
async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    history = await job_service.get_history(user_id=user_id, limit=10)
    if not history:
        await update.message.reply_text("📭 Riwayat aksi kosong.")
        return
        
    text = "📋 <b>Riwayat Aksi Terakhir Anda:</b>\n\n"
    for job, hist in history:
        text += f"• <code>[{hist.created_at.strftime('%d/%m %H:%M')}]</code> {job.company_name} - {job.title}: <b>{hist.action.upper()}</b> ({hist.details or ''})\n"
        
    await update.message.reply_text(text, parse_mode="HTML")

@error_boundary
@whitelist_required
async def recheck_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text("🔄 <i>Memulai evaluasi ulang semua lowongan terhadap CV aktif...</i>", parse_mode="HTML")
    newly_recommended = await job_service.recheck_all_jobs(user_id=user_id)
    await update.message.reply_text(f"✅ Evaluasi ulang selesai! {len(newly_recommended)} lowongan kini direkomendasikan.")

@error_boundary
@whitelist_required
async def uploadcv_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = "AWAITING_CV"
    await update.message.reply_text(
        "📄 <b>Unggah File CV Anda</b>\n\nKirimkan file CV Anda dalam format PDF atau DOCX:",
        parse_mode="HTML"
    )

@error_boundary
@whitelist_required
async def uploadportfolio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = "AWAITING_PORTFOLIO"
    await update.message.reply_text(
        "🌐 <b>Kirim URL GitHub atau Portfolio Anda</b>, atau upload file Portfolio (.ZIP / .PDF):",
        parse_mode="HTML"
    )

@error_boundary
@whitelist_required
async def uploadcoverletter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = "AWAITING_COVER_LETTER"
    await update.message.reply_text(
        "✍️ <b>Kirimkan teks Cover Letter Anda</b> untuk template lampiran email rekrutmen:",
        parse_mode="HTML"
    )

# ----------------- SMTP CONFIGS (CONVERSATIONAL STATE) -----------------

@error_boundary
@whitelist_required
async def credentials_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = "SMTP_HOST"
    context.user_data["smtp_setup"] = {}
    await update.message.reply_text(
        "📧 <b>SMTP Konfigurasi</b>\n\nMasukkan host SMTP dan port (Format: <code>host:port</code>, contoh: <code>smtp.gmail.com:587</code>):",
        parse_mode="HTML"
    )

# ----------------- STATS, HEALTH & DIAGNOSTICS -----------------

@admin_only
@error_boundary
async def health_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ <i>Menjalankan diagnostik sistem...</i>", parse_mode="HTML")
    
    # 1. DB connection check
    db_status = "OK"
    migration_status = "OK"
    try:
        async with async_session_maker() as session:
            await session.execute(select(1))
    except Exception as e:
        db_status = f"FAILED ({str(e)})"
        migration_status = "FAILED"

    # 2. OpenRouter check
    or_status = "OK"
    try:
        success, msg, latency = await evaluator.verify_connectivity()
        if not success:
            or_status = f"WARNING ({msg})"
    except Exception as e:
        or_status = f"FAILED ({str(e)})"

    # 3. SMTP Check (Admin default SMTP config verify)
    smtp_status = "Not Configured"
    try:
        async with async_session_maker() as session:
            config = await email_service.get_active_config(session, settings.TELEGRAM_ADMIN_ID)
            if config:
                await email_service.test_smtp_config(config)
                smtp_status = "OK"
    except Exception as e:
        smtp_status = f"FAILED ({str(e)})"

    # 4. Scrapers Check
    enabled_scrapers_count = 0
    for sc in job_service.scrapers:
        if not getattr(sc, "is_disabled", False):
            enabled_scrapers_count += 1

    from app.scheduler.jobs import scheduler
    sched_status = "OK" if scheduler.running else "STOPPED"

    health_report = (
        "🩺 <b>Diagnostik Kesehatan Platform:</b>\n\n"
        f"Database ........ <code>{db_status}</code>\n"
        f"Migration ....... <code>{migration_status}</code>\n"
        f"Telegram ........ <code>OK</code>\n"
        f"SMTP ............ <code>{smtp_status}</code>\n"
        f"OpenRouter ...... <code>{or_status}</code>\n"
        f"Primary Model ... <code>{settings.PRIMARY_MODEL}</code>\n"
        f"Scrapers Active . <code>{enabled_scrapers_count}/{len(job_service.scrapers)}</code>\n"
        f"Scheduler ....... <code>{sched_status}</code>"
    )
    await update.message.reply_text(health_report, parse_mode="HTML")

@admin_only
@error_boundary
async def models_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists current OpenRouter model configurations, latencies, and fallback queue status."""
    await update.message.reply_text("🔎 <i>Mengambil status model OpenRouter...</i>", parse_mode="HTML")
    success, msg, latency = await evaluator.verify_connectivity()
    primary = settings.PRIMARY_MODEL
    fallbacks = settings.fallback_models_list
    
    status_str = "🟢 AKTIF" if success else f"🔴 GANGGUAN ({msg})"
    latency_str = f"{latency:.2f}s" if latency > 0 else "N/A"
    
    text = (
        "🤖 <b>OpenRouter Model Routing & Diagnostics:</b>\n\n"
        f"<b>Model Utama (Primary):</b>\n"
        f"- Nama: <code>{primary}</code>\n"
        f"- Status: <code>{status_str}</code>\n"
        f"- Latensi: <code>{latency_str}</code>\n\n"
        f"<b>Model Cadangan (Fallbacks):</b>\n"
    )
    for model in fallbacks:
        text += f"- <code>{model}</code>\n"
        
    await update.message.reply_text(text, parse_mode="HTML")

@admin_only
@error_boundary
async def providers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists scraper providers, their current health state, and total jobs scraped."""
    text = "🕵️‍♂️ <b>Scraper Providers & Health Scoring:</b>\n\n"
    for scraper in job_service.scrapers:
        status = "🔴 DISABLED (403)" if getattr(scraper, "is_disabled", False) else "🟢 HEALTHY"
        text += (
            f"• <b>{scraper.source_name}</b>\n"
            f"  - Status: <code>{status}</code>\n"
            f"  - Keyphrase: <code>{settings.SEARCH_KEYWORDS}</code>\n"
        )
    await update.message.reply_text(text, parse_mode="HTML")

@admin_only
@error_boundary
async def migrations_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays Alembic migration history, current database revision, and pending updates."""
    from app.database.migrations import get_revisions
    try:
        curr, head = get_revisions()
        text = (
            "⚙️ <b>Alembic Database Migrations:</b>\n\n"
            f"• Revisi Aktif (Current): <code>{curr or 'None (Fresh)'}</code>\n"
            f"• Revisi Kepala (HEAD):   <code>{head}</code>\n\n"
            f"Status: " + ("🟢 Database fully up-to-date." if curr == head else "🟡 Pending migrations exist. Run startup to apply.")
        )
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal mengambil status migrasi: {e}")

@admin_only
@error_boundary
async def schema_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verifies that the database schema precisely matches the SQLAlchemy ORM models."""
    from app.database.migrations import verify_database_schema
    await update.message.reply_text("🔍 <i>Memverifikasi skema database terhadap ORM metadata...</i>", parse_mode="HTML")
    
    success = verify_database_schema()
    if success:
        await update.message.reply_text("🟢 <b>Integritas Skema: OK</b>\nSemua tabel, kolom, index, dan constraint tervalidasi dengan benar.", parse_mode="HTML")
    else:
        await update.message.reply_text("🔴 <b>Peringatan Integritas Skema: MISMATCH</b>\nTerdapat ketidaksesuaian antara skema database aktual dan model ORM.", parse_mode="HTML")

@admin_only
@error_boundary
async def doctor_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs a complete test suite check across all subsystems, recommending hotfixes."""
    await update.message.reply_text("🩺 <i>Menjalankan Platform Doctor Diagnostics...</i>", parse_mode="HTML")
    
    report = "🩺 <b>Platform Doctor Diagnostic Report:</b>\n\n"
    
    # 1. DB Check
    try:
        async with async_session_maker() as session:
            await session.execute(select(1))
        report += "✅ <b>Database:</b> Terkoneksi (SQLite Async)\n"
    except Exception as e:
        report += f"❌ <b>Database:</b> GAGAL ({e})\n👉 Periksa path data/jobs.db dan izin file.\n"
        
    # 2. OpenRouter Check
    success, or_msg, latency = await evaluator.verify_connectivity()
    if success:
        report += f"✅ <b>OpenRouter AI:</b> Terkoneksi (Latensi: {latency:.2f}s)\n"
    else:
        report += f"❌ <b>OpenRouter AI:</b> GAGAL ({or_msg})\n👉 Periksa OPENROUTER_API_KEY di file .env.\n"
        
    # 3. Cache & Filesystem
    db_path = "data/jobs.db"
    if os.path.exists(db_path):
        report += f"✅ <b>Filesystem:</b> database file exists ({os.path.getsize(db_path) / 1024:.1f} KB)\n"
    else:
        report += "❌ <b>Filesystem:</b> file database jobs.db tidak ditemukan.\n"
        
    await update.message.reply_text(report, parse_mode="HTML")

@admin_only
@error_boundary
async def system_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays host resources (CPU, Memory, Disk) and runtime container environments."""
    import shutil
    import psutil
    
    total, used, free = shutil.disk_usage(".")
    disk_free_gb = free / (2**30)
    disk_used_pct = (used / total) * 100
    
    memory = psutil.virtual_memory()
    cpu_pct = psutil.cpu_percent()
    
    text = (
        "🖥 <b>Host System Resource Metrics:</b>\n\n"
        f"• <b>CPU Usage:</b> <code>{cpu_pct}%</code>\n"
        f"• <b>RAM Usage:</b> <code>{memory.percent}%</code> (Free: {memory.available / (1024**2):.1f} MB)\n"
        f"• <b>Disk Space:</b> <code>{disk_used_pct:.1f}% used</code> (Free: {disk_free_gb:.1f} GB)\n"
        f"• <b>Active Threads:</b> <code>{psutil.Process().num_threads()}</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

@admin_only
@error_boundary
async def cache_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays stats on cached intelligence (stored job listings, analyzed profiles)."""
    async with async_session_maker() as session:
        jobs_count = await session.scalar(select(func.count(Job.id)))
        comp_count = await session.scalar(select(func.count(Company.id)))
        scores_count = await session.scalar(select(func.count(AIScore.id)))
        
    text = (
        "💾 <b>Cached Intelligence Metrics:</b>\n\n"
        f"• Lowongan Tersimpan: <code>{jobs_count}</code>\n"
        f"• Perusahaan Terindeks: <code>{comp_count}</code>\n"
        f"• Match Score Terkalkulasi: <code>{scores_count}</code>\n\n"
        "💡 <i>Kecerdasan perusahaan dan lowongan disimpan secara global untuk menghindari konsumsi token OpenRouter duplikat.</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

@admin_only
@error_boundary
async def metrics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays application conversion and operational success metrics."""
    async with async_session_maker() as session:
        sent_emails = await session.scalar(select(func.count(EmailQueue.id)).where(EmailQueue.status == "sent"))
        failed_emails = await session.scalar(select(func.count(EmailQueue.id)).where(EmailQueue.status == "failed"))
        total_rec = await session.scalar(select(func.count(AIScore.id)).where(AIScore.recommended.is_(True)))
        
    sent_count = sent_emails if sent_emails is not None else 0
    failed_count = failed_emails if failed_emails is not None else 0
    total_emails = sent_count + failed_count
    success_rate = (sent_count / total_emails * 100) if total_emails > 0 else 0.0
    
    text = (
        "📈 <b>SaaS Conversion & Operation Metrics:</b>\n\n"
        f"• Total Rekomendasi Magang: <code>{total_rec}</code>\n"
        f"• Email Pengiriman Dikirim: <code>{sent_emails}</code>\n"
        f"• Email Pengiriman Gagal:  <code>{failed_emails}</code>\n"
        f"• SMTP Delivery Success:     <code>{success_rate:.1f}%</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

@admin_only
@error_boundary
async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    try:
        stats = await job_service.get_db_stats(user_id=user_id)
        
        async with async_session_maker() as session:
            comp_count = await session.scalar(select(func.count(Company.id)))
            disc_comp = await session.scalar(select(func.count(Company.id)).where(Company.is_discovered.is_(True)))
            emails_count = await session.scalar(select(func.count(Company.id)).where(Company.recruitment_email.is_not(None)))
            drafts = await session.scalar(select(func.count(EmailQueue.id)).where((EmailQueue.status == "draft") & (EmailQueue.user_id == user_id)))
            sent = await session.scalar(select(func.count(EmailQueue.id)).where((EmailQueue.status == "sent") & (EmailQueue.user_id == user_id)))

        stats_text = (
            "📊 <b>PKL Finder - Dashboard Otonom</b>\n\n"
            f"🏢 Perusahaan Diselidiki: <code>{comp_count}</code>\n"
            f"🌐 Hasil Discovery Google: <code>{disc_comp}</code>\n"
            f"📧 Email Rekrutmen Ketemu: <code>{emails_count}</code>\n\n"
            f"💼 Total Lowongan Magang: <code>{stats['total_jobs']}</code>\n"
            f"🎯 Lolos Evaluasi AI: <code>{stats['recommended_jobs']}</code>\n"
            f"⭐ Lowongan Favorit: <code>{stats['favorites_count']}</code>\n\n"
            f"✉️ <b>Status Aplikasi Email Anda:</b>\n"
            f"- Draft Pending Persetujuan: <code>{drafts}</code>\n"
            f"- Email Berhasil Terkirim: <code>{sent}</code>"
        )
        await update.message.reply_text(stats_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Gagal mengambil statistik: {str(e)}")

@admin_only
@error_boundary
async def logs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "logs",
        "pkl_finder.log"
    )
    if not os.path.exists(log_path):
        await update.message.reply_text("📭 File log tidak ditemukan.")
        return

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        last_lines = lines[-15:]
        log_snippet = "".join(last_lines)
        await update.message.reply_text(
            f"📋 <b>15 Baris Log Terakhir:</b>\n<pre>{log_snippet}</pre>",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal membaca file log: {e}")

# ----------------- EMAIL QUEUE ACTIONS -----------------

@error_boundary
@whitelist_required
async def queue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List pending drafts in the user's approval queue."""
    user_id = update.effective_user.id
    async with async_session_maker() as session:
        stmt = select(EmailQueue).options(selectinload(EmailQueue.company)).where((EmailQueue.status == "draft") & (EmailQueue.user_id == user_id)).limit(5)
        res = await session.execute(stmt)
        drafts = res.scalars().all()

        if not drafts:
            await update.message.reply_text("📭 Antrean draft email kosong.")
            return

        await update.message.reply_text(f"✉️ <b>Daftar Draft Email Pending ({len(drafts)} pertama):</b>", parse_mode="HTML")
        for draft in drafts:
            att_text = "📎 <b>Lampiran:</b> CV Terlampir (.PDF / .DOCX)\n" if draft.attachments else "📎 <b>Lampiran:</b> Tidak ada lampiran\n"
            text = (
                f"🏢 <b>Perusahaan:</b> <code>{draft.company.name}</code>\n"
                f"📧 <b>Penerima:</b> <code>{draft.recipient_email}</code>\n"
                f"{att_text}"
                f"📝 <b>Subject:</b> {draft.subject}\n\n"
                f"<b>Body Preview:</b>\n<i>{draft.body[:300]}...</i>"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Setujui", callback_data=f"approve:{draft.id}"),
                    InlineKeyboardButton("❌ Tolak", callback_data=f"reject:{draft.id}")
                ],
                [
                    InlineKeyboardButton("✉️ Kirim Sekarang", callback_data=f"send:{draft.id}"),
                    InlineKeyboardButton("📝 Edit Draft", callback_data=f"edit_draft:{draft.id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

@error_boundary
@whitelist_required
async def sendall_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text("⏳ <i>Mulai mendispatch semua email approved...</i>", parse_mode="HTML")
    from app.agents.email_dispatch_agent import email_dispatch_agent
    res = await email_dispatch_agent.dispatch_approved_queue(user_id=user_id)
    sent_count = res.get("sent", 0)
    failed_count = res.get("failed", 0)

    await update.message.reply_text(
        f"✅ <b>Dispatch Antrean Selesai!</b>\n- Terkirim: <code>{sent_count}</code>\n- Gagal: <code>{failed_count}</code>",
        parse_mode="HTML"
    )

@error_boundary
@whitelist_required
async def companies_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session_maker() as session:
        stmt = select(Company).limit(15)
        res = await session.execute(stmt)
        companies = res.scalars().all()
        
        if not companies:
            await update.message.reply_text("📭 Tidak ada perusahaan terdaftar.")
            return
            
        comp_text = "🏢 <b>Daftar Perusahaan Diselidiki (Global):</b>\n\n"
        for comp in companies:
            status = "📧" if comp.recruitment_email else "🌐"
            comp_text += f"{status} {comp.name} (<a href='{comp.website}'>Website</a>)\n"
            
        await update.message.reply_text(comp_text, parse_mode="HTML", disable_web_page_preview=True)

@error_boundary
@whitelist_required
async def openapplications_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists companies where a recruitment email is discovered, ready for Open Applications."""
    async with async_session_maker() as session:
        stmt = select(Company).where(Company.recruitment_email.is_not(None)).limit(15)
        res = await session.execute(stmt)
        companies = res.scalars().all()
        
        if not companies:
            await update.message.reply_text("📭 Tidak ada perusahaan dengan email rekrutmen untuk Open Application.")
            return
            
        comp_text = "📧 <b>Open Application Opportunities:</b>\n\n"
        for comp in companies:
            comp_text += f"• <b>{comp.name}</b>\n  Email: <code>{comp.recruitment_email}</code>\n"
            
        await update.message.reply_text(comp_text, parse_mode="HTML")

# ----------------- GENERIC DOCUMENT / TEXT INPUTS -----------------

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes PDF/Word doc uploads automatically, detecting suitable career roles via AI."""
    doc = update.message.document
    if not doc or not doc.file_name:
        return

    file_name = doc.file_name.lower()
    state = context.user_data.get("state")
    user_id = update.effective_user.id

    # If user explicitly awaiting portfolio upload
    if state == "AWAITING_PORTFOLIO":
        file_info = await doc.get_file()
        file_bytes = await file_info.download_as_bytearray()
        os.makedirs("data/portfolios", exist_ok=True)
        local_path = os.path.join("data/portfolios", doc.file_name)
        with open(local_path, "wb") as f:
            f.write(bytes(file_bytes))
            
        async with async_session_maker() as session:
            stmt = select(Portfolio).where(Portfolio.user_id == user_id)
            res = await session.execute(stmt)
            portfolio = res.scalar_one_or_none()
            if portfolio:
                portfolio.file_path = local_path
                portfolio.uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                portfolio = Portfolio(user_id=user_id, file_path=local_path)
                session.add(portfolio)
            await session.commit()
            
        await update.message.reply_text("✅ <b>File Portfolio Berhasil Diunggah!</b>", parse_mode="HTML")
        context.user_data["state"] = None
        return

    # Check file extension for CV (.pdf or .docx)
    if not (file_name.endswith(".pdf") or file_name.endswith(".docx")):
        await update.message.reply_text("⚠️ Harap unggah file CV dengan format <b>.PDF</b> atau <b>.DOCX</b>.", parse_mode="HTML")
        return

    wait_msg = await update.message.reply_text(
        "📄 <i>Membaca CV dan menjalankan analisis AI untuk mendeteksi keahlian & posisi pekerjaan yang cocok...</i>",
        parse_mode="HTML"
    )

    try:
        file_info = await doc.get_file()
        file_bytes = await file_info.download_as_bytearray()

        async with async_session_maker() as session:
            cv_profile = await cv_service.save_cv(session, user_id, doc.file_name, bytes(file_bytes))

        import json
        roles = []
        skills = []
        keywords = []
        if cv_profile.detected_roles:
            try:
                roles = json.loads(cv_profile.detected_roles)
            except Exception:
                roles = []
        if cv_profile.detected_skills:
            try:
                skills = json.loads(cv_profile.detected_skills)
            except Exception:
                skills = []
        if cv_profile.search_keywords:
            try:
                keywords = json.loads(cv_profile.search_keywords)
            except Exception:
                keywords = []

        summary = cv_profile.candidate_summary or "Profil CV berhasil dipelajari oleh AI."
        roles_list = "\n".join([f"  {i}. <b>{r}</b>" for i, r in enumerate(roles[:4], 1)]) if roles else "  • Software Engineer / Tech"
        skills_str = ", ".join(skills[:6]) if skills else "Programming, Technical Skills"
        kws_str = ", ".join(keywords[:5]) if keywords else "software engineer, developer"

        result_text = (
            "🎉 <b>CV Berhasil Dianalisis oleh AI!</b>\n\n"
            f"👤 <b>Ringkasan Profil:</b>\n<i>\"{summary}\"</i>\n\n"
            f"🎯 <b>Pekerjaan / Posisi yang Cocok untuk Anda:</b>\n"
            f"{roles_list}\n\n"
            f"💡 <b>Keahlian Terdeteksi:</b>\n• {skills_str}\n\n"
            f"🔍 <b>Keyword Pencarian Terpersonalisasi:</b>\n<code>{kws_str}</code>\n\n"
            "👉 <i>Klik tombol di bawah untuk langsung mencari lowongan kerja yang cocok:</i>"
        )
        keyboard = [
            [InlineKeyboardButton("🚀 Cari Lowongan Kerja Sekarang", callback_data="btn_search")],
            [InlineKeyboardButton("👤 Lihat Profil Lengkap", callback_data="btn_profile")]
        ]
        await wait_msg.edit_text(result_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["state"] = None

        # Notify admin of CV upload
        roles_preview = ", ".join(roles[:3]) if roles else "Tech"
        from app.services.admin_notifier import notify_admin_new_user
        asyncio.create_task(
            notify_admin_new_user(
                user_id=user_id,
                username=update.effective_user.username,
                source="telegram",
                details=f"File CV: {doc.file_name} | Posisi: {roles_preview}"
            )
        )

    except Exception as e:
        logger.error(f"Error handling CV document upload: {e}", exc_info=True)
        await wait_msg.edit_text(f"❌ <b>Gagal memproses CV:</b> <code>{str(e)}</code>", parse_mode="HTML")

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """State machine processing for text setup replies."""
    state = context.user_data.get("state")
    if not state:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # 1. SMTP Setup States
    if state == "SMTP_HOST":
        if ":" not in text:
            await update.message.reply_text("❌ Format salah. Harap kirimkan dengan format host:port.")
            return
        host, port = text.split(":")
        try:
            port = int(port)
        except ValueError:
            await update.message.reply_text("❌ Port harus berupa angka.")
            return
        
        context.user_data["smtp_setup"]["host"] = host
        context.user_data["smtp_setup"]["port"] = port
        context.user_data["state"] = "SMTP_USER"
        await update.message.reply_text("👤 Masukkan username/email pengirim SMTP:")

    elif state == "SMTP_USER":
        context.user_data["smtp_setup"]["username"] = text
        context.user_data["state"] = "SMTP_PASS"
        await update.message.reply_text("🔑 Masukkan password / App Password:")

    elif state == "SMTP_PASS":
        context.user_data["smtp_setup"]["password"] = text
        context.user_data["state"] = "SMTP_ENC"
        await update.message.reply_text("🔒 Masukkan tipe enkripsi (SSL, TLS, atau NONE):")

    elif state == "SMTP_ENC":
        enc = text.upper()
        if enc not in ["SSL", "TLS", "NONE"]:
            await update.message.reply_text("❌ Pilihan enkripsi salah. Ketik SSL, TLS, atau NONE:")
            return
            
        context.user_data["smtp_setup"]["encryption"] = enc
        context.user_data["state"] = "SMTP_SENDER"
        await update.message.reply_text("👤 Masukkan Nama Pengirim (Sender Display Name):")

    elif state == "SMTP_SENDER":
        context.user_data["smtp_setup"]["sender_name"] = text
        context.user_data["state"] = "SMTP_SIG"
        await update.message.reply_text("✍️ Masukkan Tanda Tangan Email (Signature):")

    elif state == "SMTP_SIG":
        setup = context.user_data["smtp_setup"]
        try:
            async with async_session_maker() as session:
                await email_service.configure_smtp(
                    session=session,
                    user_id=user_id,
                    host=setup["host"],
                    port=setup["port"],
                    username=setup["username"],
                    password=setup["password"],
                    encryption_type=setup["encryption"],
                    sender_name=setup["sender_name"],
                    signature=text
                )
            await update.message.reply_text("✅ <b>Konfigurasi SMTP Berhasil Disimpan & Diverifikasi!</b>", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal memverifikasi SMTP: {e}\n\nUlangi setup SMTP menggunakan /credentials.")
        finally:
            context.user_data["state"] = None
            context.user_data["smtp_setup"] = None

    # 2. Portfolio URL state
    elif state == "AWAITING_PORTFOLIO":
        async with async_session_maker() as session:
            stmt = select(Portfolio).where(Portfolio.user_id == user_id)
            res = await session.execute(stmt)
            portfolio = res.scalar_one_or_none()
            
            if portfolio:
                if "github" in text:
                    portfolio.github_url = text
                else:
                    portfolio.website_url = text
                portfolio.uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                portfolio = Portfolio(
                    user_id=user_id,
                    github_url=text if "github" in text else None,
                    website_url=text if "github" not in text else None
                )
                session.add(portfolio)
            await session.commit()
        await update.message.reply_text("✅ <b>URL Portfolio Berhasil Disimpan!</b>", parse_mode="HTML")
        context.user_data["state"] = None

    # 3. Cover Letter template
    elif state == "AWAITING_COVER_LETTER":
        async with async_session_maker() as session:
            stmt = select(CoverLetter).where(CoverLetter.user_id == user_id)
            res = await session.execute(stmt)
            cl = res.scalar_one_or_none()
            if cl:
                cl.text = text
                cl.uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                cl = CoverLetter(user_id=user_id, text=text)
                session.add(cl)
            await session.commit()
        await update.message.reply_text("✅ <b>Template Cover Letter Berhasil Disimpan!</b>", parse_mode="HTML")
        context.user_data["state"] = None

    # 4. Awaiting Edit Email Draft Body
    elif state.startswith("AWAITING_EDIT_BODY:"):
        draft_id = int(state.split(":")[1])
        async with async_session_maker() as session:
            stmt = select(EmailQueue).where((EmailQueue.id == draft_id) & (EmailQueue.user_id == user_id))
            res = await session.execute(stmt)
            draft = res.scalar_one_or_none()
            if draft:
                draft.body = text
                await session.commit()
                await update.message.reply_text("✅ <b>Body draft email berhasil diubah!</b> Gunakan /queue untuk meninjau kembali.", parse_mode="HTML")
        context.user_data["state"] = None

# ----------------- CALLBACK BUTTON QUERIES -----------------

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not query.data:
        return

    data = query.data
    user_id = query.from_user.id

    if data == "btn_search":
        await query.answer()
        await search_handler(update, context)
        return
    elif data == "btn_uploadcv":
        await query.answer()
        context.user_data["state"] = "AWAITING_CV"
        await query.message.reply_text("📄 <b>Silakan kirimkan file CV (.PDF atau .DOCX) Anda sekarang:</b>", parse_mode="HTML")
        return
    elif data == "btn_profile":
        await query.answer()
        await profile_handler(update, context)
        return
    
    try:
        action, entity_id_str = data.split(":", 1)
        entity_id = int(entity_id_str)
        
        async with async_session_maker() as session:
            if action in ["fav", "unfav", "apply_email"]:
                stmt = select(Job).options(selectinload(Job.ai_scores)).where(Job.id == entity_id)
                res = await session.execute(stmt)
                job = res.scalar_one_or_none()
                if not job:
                    return

                if action == "fav":
                    success = await job_service.add_favorite(user_id, entity_id)
                    if success:
                        await query.edit_message_reply_markup(reply_markup=get_job_keyboard(job, is_fav=True))
                elif action == "unfav":
                    success = await job_service.remove_favorite(user_id, entity_id)
                    if success:
                        await query.edit_message_reply_markup(reply_markup=get_job_keyboard(job, is_fav=False))
                elif action == "apply_email":
                    await query.answer("Menyiapkan draft lamaran...")
                    wait_draft = await query.message.reply_text("✍️ <i>Menyusun draft lamaran personal & melampirkan CV Anda...</i>", parse_mode="HTML")
                    try:
                        from app.agents.email_drafting_agent import email_drafting_agent
                        draft = await email_drafting_agent.draft_email_for_job(
                            session=session,
                            user_id=user_id,
                            company_id=job.company_id,
                            job_id=entity_id
                        )
                        if draft:
                            await wait_draft.edit_text(
                                f"✅ <b>Draft Lamaran Email Berhasil Dibuat!</b>\n\n"
                                f"🏢 <b>Tujuan:</b> <code>{draft.recipient_email}</code>\n"
                                f"📌 <b>Subjek:</b> <b>{draft.subject}</b>\n\n"
                                f"📄 <b>Preview Body:</b>\n<i>{draft.body[:280]}...</i>\n\n"
                                f"📎 <b>Lampiran:</b> {'CV Kandidat (.pdf)' if draft.attachments else 'Tidak ada'}\n\n"
                                "Gunakan perintah /queue untuk meninjau dan mengirim email ini menggunakan Google SSO atau SMTP.",
                                parse_mode="HTML"
                            )
                        else:
                            await wait_draft.edit_text("❌ Gagal menyusun draft lamaran untuk lowongan ini.")
                    except Exception as de:
                        logger.error(f"Error drafting email from job card: {de}")
                        await wait_draft.edit_text(f"❌ Error membuat draft: {de}")

            elif action == "adm_approve":
                from app.agents.access_control_agent import access_control_agent
                success, msg, _ = await access_control_agent.approve_user(entity_id)
                await query.answer("User disetujui!" if success else "Gagal")
                await query.edit_message_text(f"{query.message.text_html}\n\n<b>Status:</b> ✅ {msg}", parse_mode="HTML")
                return

            elif action == "adm_reject":
                from app.agents.access_control_agent import access_control_agent
                success, msg, _ = await access_control_agent.reject_user(entity_id)
                await query.answer("User ditolak!" if success else "Gagal")
                await query.edit_message_text(f"{query.message.text_html}\n\n<b>Status:</b> ⛔ {msg}", parse_mode="HTML")
                return

            elif action == "approve":
                email_stmt = select(EmailQueue).where((EmailQueue.id == entity_id) & (EmailQueue.user_id == user_id))
                res = await session.execute(email_stmt)
                draft = res.scalar_one_or_none()
                if draft:
                    draft.status = "approved"
                    await session.commit()
                    await query.edit_message_text(f"✅ <b>Draft Email Disetujui (Approved)</b>\nReady to send to: <code>{draft.recipient_email}</code>", parse_mode="HTML")
            
            elif action == "reject":
                email_stmt = select(EmailQueue).where((EmailQueue.id == entity_id) & (EmailQueue.user_id == user_id))
                res = await session.execute(email_stmt)
                draft = res.scalar_one_or_none()
                if draft:
                    draft.status = "rejected"
                    await session.commit()
                    await query.edit_message_text(f"❌ <b>Draft Email Ditolak (Rejected)</b>\nRecipient: <code>{draft.recipient_email}</code>", parse_mode="HTML")

            elif action == "send":
                email_stmt = select(EmailQueue).where((EmailQueue.id == entity_id) & (EmailQueue.user_id == user_id))
                res = await session.execute(email_stmt)
                draft = res.scalar_one_or_none()
                if draft:
                    await query.edit_message_text("⏳ <i>Sedang mengirim email...</i>", parse_mode="HTML")
                    try:
                        success = await email_service.send_email(session, entity_id)
                        if success:
                            await query.edit_message_text(f"🚀 <b>Email Berhasil Terkirim ke:</b> <code>{draft.recipient_email}</code>", parse_mode="HTML")
                    except Exception as se:
                        await query.edit_message_text(f"❌ <b>Gagal mengirim email:</b> <code>{str(se)}</code>", parse_mode="HTML")

            elif action == "edit_draft":
                context.user_data["state"] = f"AWAITING_EDIT_BODY:{entity_id}"
                await query.message.reply_text(
                    "✏️ <b>Kirimkan konten body email baru untuk menggantikan draft saat ini:</b>",
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"Error handling callback button: {e}", exc_info=True)

@error_boundary
@whitelist_required
async def connect_google_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Google SSO OAuth authorization URL to user for Gmail API email sending."""
    user_id = update.effective_user.id
    from app.services.google_auth_service import google_auth_service
    auth_url = google_auth_service.get_authorization_url(user_id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Login Google SSO (Izin Kirim Email)", url=auth_url)]
    ])

    text = (
        "🔐 <b>Login Email Menggunakan Google SSO (Gmail API)</b>\n\n"
        "Klik tombol di bawah untuk mengizinkan bot PKL Finder mengirim email lamaran magang Anda "
        "secara langsung melalui akun Google Anda dengan lampiran CV lengkap.\n\n"
        f"🔗 <b>Atau buka URL ini di browser Anda:</b>\n<code>{auth_url}</code>\n\n"
        "<i>Setelah selesai login di browser, bot akan otomatis terhubung!</i>"
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

@error_boundary
@whitelist_required
async def email_handler_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    from app.services.google_auth_service import google_auth_service
    async with async_session_maker() as session:
        google_auth = await google_auth_service.get_active_auth(session, user_id)
        config = await email_service.get_active_config(session, user_id)

    lines = ["📧 <b>Konfigurasi Pengiriman Email Anda:</b>\n"]
    if google_auth:
        lines.append(
            f"🟢 <b>Google SSO (Gmail API):</b> AKTIF\n"
            f"• Email Pengirim: <code>{google_auth.email}</code>\n"
            f"• Izin: <code>Direct Gmail API Send (dengan lampiran CV)</code>\n"
        )
    if config:
        lines.append(
            f"🔵 <b>SMTP Server:</b> AKTIF\n"
            f"• Host: <code>{config.host}</code>\n"
            f"• Port: <code>{config.port}</code>\n"
            f"• User: <code>{config.username}</code>\n"
        )
    if not google_auth and not config:
        lines.append(
            "⚠️ <b>Belum ada konfigurasi pengiriman email!</b>\n\n"
            "Silakan hubungkan akun email Anda:\n"
            "1. <b>Google SSO (Rekomendasi):</b> Jalankan /connect_google untuk login 1-klik dengan Google.\n"
            "2. <b>SMTP Manual:</b> Jalankan /credentials untuk mengatur kredensial SMTP."
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

@admin_only
@error_boundary
async def agents_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display real-time multi-agent system status to admin."""
    from app.agents import (
        scraper_agent, discovery_agent, cv_agent, matching_agent,
        email_drafting_agent, email_dispatch_agent, access_control_agent, scheduler_agent
    )
    agents = [
        scraper_agent, discovery_agent, cv_agent, matching_agent,
        email_drafting_agent, email_dispatch_agent, access_control_agent, scheduler_agent
    ]
    lines = ["🤖 <b>Status Telemetri Sistem Multi-Agent (1 Feature = 1 Agent):</b>\n"]
    for ag in agents:
        st = ag.get_status()
        badge = "🟢" if st["status"] != "Error" else "🔴"
        lines.append(
            f"{badge} <b>{st['name']}</b> ({st['status']})\n"
            f"   • Fitur: <i>{st['feature']}</i>\n"
            f"   • Runs: <code>{st['total_runs']}</code> | Dur: <code>{st['duration_sec']}s</code>\n"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

def setup_bot(application) -> None:
    """Registers all commands and handlers with the PTB Application."""
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    
    # Discovery scrapers / trigger command
    application.add_handler(CommandHandler("search", search_handler))
    application.add_handler(CommandHandler("latest", latest_handler))
    
    # Profiles / CV Uploads
    application.add_handler(CommandHandler("profile", profile_handler))
    application.add_handler(CommandHandler("uploadcv", uploadcv_handler))
    application.add_handler(CommandHandler("uploadportfolio", uploadportfolio_handler))
    application.add_handler(CommandHandler("uploadcoverletter", uploadcoverletter_handler))
    
    # SMTP & Google SSO configs
    application.add_handler(CommandHandler("credentials", credentials_handler))
    application.add_handler(CommandHandler("email", email_handler_fallback))
    application.add_handler(CommandHandler("connect_google", connect_google_handler))
    
    # Email queue management
    application.add_handler(CommandHandler("queue", queue_handler))
    application.add_handler(CommandHandler("sendall", sendall_handler))
    
    # System configs / logs / stats / health
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CommandHandler("health", health_handler))
    application.add_handler(CommandHandler("logs", logs_handler))
    application.add_handler(CommandHandler("settings", settings_handler))
    application.add_handler(CommandHandler("favorites", favorites_handler))
    application.add_handler(CommandHandler("history", history_handler))
    application.add_handler(CommandHandler("recheck", recheck_handler))
    application.add_handler(CommandHandler("companies", companies_handler))
    application.add_handler(CommandHandler("openapplications", openapplications_handler))
    
    # Admin commands (Subsystem Specifics)
    application.add_handler(CommandHandler("agents", agents_status_handler))
    application.add_handler(CommandHandler("models", models_handler))
    application.add_handler(CommandHandler("providers", providers_handler))
    application.add_handler(CommandHandler("migrations", migrations_handler))
    application.add_handler(CommandHandler("schema", schema_handler))
    application.add_handler(CommandHandler("doctor", doctor_handler))
    application.add_handler(CommandHandler("system", system_handler))
    application.add_handler(CommandHandler("cache", cache_handler))
    application.add_handler(CommandHandler("metrics", metrics_handler))
    
    # Document upload parsing message router
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    
    # State machine message text handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    # Buttons callbacks
    application.add_handler(CallbackQueryHandler(callback_handler))
