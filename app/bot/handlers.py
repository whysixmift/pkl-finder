import os
import json
import logging
from functools import wraps
from typing import Dict, Any, List, Optional
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from app.config.settings import settings
from app.services.job_service import JobService
from app.services.email_service import email_service, decrypt_password, encrypt_password
from app.services.cv_service import cv_service
from app.services.crawler_service import career_crawler
from app.services.discovery_service import discovery_engine
from app.database.db import async_session_maker
from app.database.models import Job, AIScore, Company, Favorite, History, SMTPConfig, EmailQueue, CVProfile, Portfolio, CoverLetter
from app.ai.evaluator import evaluator, CANDIDATE_PROFILE
from app.utils.logger import logger
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

job_service = JobService()

def admin_only(func):
    """Decorator to restrict access to the configured admin ID (Issue 10)."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return
        
        user_id = update.effective_user.id
        if user_id != settings.TELEGRAM_ADMIN_ID:
            logger.warning(f"Unauthorized access attempt by user ID {user_id}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔&nbsp;<b>Akses Ditolak:</b> Anda tidak diizinkan menggunakan bot ini.",
                    parse_mode="HTML"
                )
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def error_boundary(func):
    """Catches all exceptions to prevent bot crashes and replies with helpful diagnostics (Issue 10)."""
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
        f"{score_str}\n"
        f"💼 <b>Category:</b> <code>{getattr(ai_score, 'company_category', 'Tech')}</code>\n"
        f"🔥 <b>Priority:</b> <code>{getattr(ai_score, 'priority', 'medium').upper()}</code>\n\n"
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

# ----------------- STARTUP & CONFIGS -----------------

@admin_only
@error_boundary
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = (
        "🤖 <b>PKL Finder - Autonomous Assistant</b>\n\n"
        "Asisten AI otonom untuk pencarian lowongan magang/PKL, crawler perusahaan, "
        "kolektor email rekrutmen, dan SMTP email dispatcher otonom.\n\n"
        "Kirim /help untuk melihat semua daftar perintah yang tersedia."
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

@admin_only
@error_boundary
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "⚙️&nbsp;<b>Sistem Utama:</b>\n"
        "/search - Cari lowongan magang & matching AI\n"
        "/latest - Tampilkan magang rekomendasi terbaru\n"
        "/favorites - Lihat lowongan terfavorit\n"
        "/stats - Tampilkan dashboard & statistik data\n"
        "/settings - Tampilkan konfigurasi lingkungan\n"
        "/health - Diagnostik server & koneksi API\n"
        "/logs - Cek visual 15 baris log terakhir\n\n"
        "👤&nbsp;<b>Profil & CV:</b>\n"
        "/profile - Lihat CV otonom aktif\n"
        "/uploadcv - Unggah CV baru (PDF/DOCX)\n"
        "/uploadportfolio - Atur portfolio (ZIP/PDF/GitHub)\n"
        "/uploadcoverletter - Simpan template cover letter\n\n"
        "📧&nbsp;<b>SMTP & Application Queue:</b>\n"
        "/credentials - Konfigurasi SMTP email pengirim\n"
        "/email - Periksa konfigurasi SMTP aktif\n"
        "/queue - Tampilkan draft email antrean AI\n"
        "/sendall - Dispatch semua email approved\n\n"
        "🏢&nbsp;<b>Company Discovery:</b>\n"
        "/companies - Tampilkan daftar perusahaan terdaftar\n"
        "/openapplications - Tampilkan daftar Open Applications"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


# ----------------- SYSTEM & CORE COMMAND HANDLERS -----------------

@admin_only
@error_boundary
async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔍 <i>Memulai scraping dan matching AI...</i>", parse_mode="HTML")
    new_jobs = await job_service.run_scraping_and_matching()
    
    # Run the company discovery and career crawling engine as part of search
    await update.message.reply_text("🏢 <i>Menjalankan Crawler Perusahaan & Harvester Email...</i>", parse_mode="HTML")
    try:
        await discovery_engine.discover_companies()
        await career_crawler.crawl_all_companies()
    except Exception as ce:
        logger.error(f"Error during company crawling: {ce}")

    if new_jobs:
        await update.message.reply_text(f"✅ Scraping selesai! Menemukan {len(new_jobs)} lowongan baru rekomendasi.")
        for job in new_jobs:
            text = format_job_message(job)
            keyboard = get_job_keyboard(job, is_fav=False)
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text("✅ Scraping selesai! Tidak ada lowongan baru yang direkomendasikan saat ini.")

@admin_only
@error_boundary
async def latest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    jobs = await job_service.get_latest_jobs(limit=10, recommended_only=True)
    if not jobs:
        await update.message.reply_text("📭 Tidak ada lowongan rekomendasi terbaru di database.")
        return
        
    await update.message.reply_text(f"📋 <b>Daftar 10 Lowongan Rekomendasi Terbaru:</b>", parse_mode="HTML")
    for job in jobs:
        text = format_job_message(job)
        keyboard = get_job_keyboard(job, is_fav=False)
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

@admin_only
@error_boundary
async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session_maker() as session:
        cv_text = await cv_service.get_active_cv_text(session)
        
        # Check portfolio
        p_stmt = select(Portfolio).order_by(desc(Portfolio.uploaded_at)).limit(1)
        p_res = await session.execute(p_stmt)
        portfolio = p_res.scalar_one_or_none()
        
        # Check cover letter
        cl_stmt = select(CoverLetter).order_by(desc(CoverLetter.uploaded_at)).limit(1)
        cl_res = await session.execute(cl_stmt)
        cl = cl_res.scalar_one_or_none()

    cv_display = cv_text[:500] + "..." if cv_text else "Default CV Profile (Julian - SMK Negeri 2 Bekasi)"
    portfolio_display = "Belum diatur"
    if portfolio:
        portfolio_display = portfolio.github_url or portfolio.website_url or portfolio.file_path or "Tersimpan"
        
    cl_display = cl.text[:150] + "..." if cl else "Belum diatur"

    profile_text = (
        "👤 <b>Profil Pelamar Aktif:</b>\n\n"
        f"📄 <b>CV Teks Preview:</b>\n<i>{cv_display}</i>\n\n"
        f"🌐 <b>Portfolio:</b> <code>{portfolio_display}</code>\n"
        f"✉️ <b>Cover Letter:</b> <code>{cl_display}</code>"
    )
    await update.message.reply_text(profile_text, parse_mode="HTML")

@admin_only
@error_boundary
async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config_text = (
        "⚙️ <b>Konfigurasi Sistem Aktif:</b>\n\n"
        f"🔑 OpenRouter Model: <code>{settings.OPENROUTER_MODEL}</code>\n"
        f"⏱ Interval Cek: <code>{settings.CHECK_INTERVAL_MINUTES} Menit</code>\n"
        f"🎯 Threshold Skor: <code>{settings.SCORE_THRESHOLD}</code>\n"
        f"🏢 Limit Per Run: <code>{settings.MAX_JOBS_PER_RUN}</code>\n"
        f"🔍 Lokasi Target: <code>{settings.SEARCH_LOCATIONS}</code>\n"
        f"🏷 Keyword Target: <code>{settings.SEARCH_KEYWORDS}</code>"
    )
    await update.message.reply_text(config_text, parse_mode="HTML")

@admin_only
@error_boundary
async def favorites_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    jobs = await job_service.get_favorites()
    if not jobs:
        await update.message.reply_text("⭐ Belum ada lowongan terfavorit.")
        return
        
    await update.message.reply_text("⭐ <b>Lowongan Terfavorit Anda:</b>", parse_mode="HTML")
    for job in jobs:
        text = format_job_message(job)
        keyboard = get_job_keyboard(job, is_fav=True)
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

@admin_only
@error_boundary
async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history = await job_service.get_history(limit=10)
    if not history:
        await update.message.reply_text("📭 Riwayat aksi kosong.")
        return
        
    text = "📋 <b>Riwayat Aksi Terakhir:</b>\n\n"
    for job, hist in history:
        text += f"• <code>[{hist.created_at.strftime('%d/%m %H:%M')}]</code> {job.company_name} - {job.title}: <b>{hist.action.upper()}</b> ({hist.details or ''})\n"
        
    await update.message.reply_text(text, parse_mode="HTML")

@admin_only
@error_boundary
async def recheck_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔄 <i>Memulai evaluasi ulang semua lowongan terhadap CV aktif...</i>", parse_mode="HTML")
    newly_recommended = await job_service.recheck_all_jobs()
    await update.message.reply_text(f"✅ Evaluasi ulang selesai! {len(newly_recommended)} lowongan kini direkomendasikan.")

# ----------------- CV / PORTFOLIO UPLOADS -----------------

@admin_only
@error_boundary
async def uploadcv_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = "AWAITING_CV"
    await update.message.reply_text(
        "📂 <b>Kirim file CV Anda (PDF atau DOCX)</b> untuk digunakan oleh pencocokan AI.",
        parse_mode="HTML"
    )

@admin_only
@error_boundary
async def uploadportfolio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = "AWAITING_PORTFOLIO"
    await update.message.reply_text(
        "🌐 <b>Kirim URL GitHub atau Portfolio Anda</b>, atau upload file Portfolio (.ZIP / .PDF):",
        parse_mode="HTML"
    )

@admin_only
@error_boundary
async def uploadcoverletter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["state"] = "AWAITING_COVER_LETTER"
    await update.message.reply_text(
        "✍️ <b>Kirimkan teks Cover Letter Anda</b> untuk template lampiran email rekrutmen:",
        parse_mode="HTML"
    )

# ----------------- SMTP CONFIGS (CONVERSATIONAL STATE) -----------------

@admin_only
@error_boundary
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
    try:
        async with async_session_maker() as session:
            await session.execute(select(1))
    except Exception as e:
        db_status = f"FAILED ({str(e)})"

    # 2. OpenRouter check
    or_status = "OK"
    try:
        success, msg = await evaluator.verify_connectivity()
        if not success:
            or_status = f"WARNING ({msg})"
    except Exception as e:
        or_status = f"FAILED ({str(e)})"

    # 3. SMTP Check
    smtp_status = "Not Configured"
    try:
        async with async_session_maker() as session:
            config = await email_service.get_active_config(session)
            if config:
                await email_service.test_smtp_config(config)
                smtp_status = "OK"
    except Exception as e:
        smtp_status = f"FAILED ({str(e)})"

    # 4. Scrapers Check
    scraper_statuses = []
    for sc in job_service.scrapers:
        status = "Disabled (403)" if getattr(sc, "is_disabled", False) else "OK"
        scraper_statuses.append(f"- {sc.source_name.upper()}: <code>{status}</code>")
    scrapers_str = "\n".join(scraper_statuses)

    from app.scheduler.jobs import scheduler
    sched_status = "OK" if scheduler.running else "STOPPED"

    health_report = (
        "🩺 <b>Diagnostik Kesehatan Platform:</b>\n\n"
        f"Database ........ <code>{db_status}</code>\n"
        f"OpenRouter ...... <code>{or_status}</code>\n"
        f"SMTP Server ..... <code>{smtp_status}</code>\n"
        f"Scheduler ....... <code>{sched_status}</code>\n"
        f"Configured Model: <code>{settings.OPENROUTER_MODEL}</code>\n\n"
        f"<b>Status Scraper Portal:</b>\n{scrapers_str}"
    )
    await update.message.reply_text(health_report, parse_mode="HTML")

@admin_only
@error_boundary
async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        stats = await job_service.get_db_stats()
        
        async with async_session_maker() as session:
            comp_count = await session.scalar(select(func.count(Company.id)))
            disc_comp = await session.scalar(select(func.count(Company.id)).where(Company.is_discovered == True))
            emails_count = await session.scalar(select(func.count(Company.id)).where(Company.recruitment_email != None))
            drafts = await session.scalar(select(func.count(EmailQueue.id)).where(EmailQueue.status == "draft"))
            sent = await session.scalar(select(func.count(EmailQueue.id)).where(EmailQueue.status == "sent"))

        stats_text = (
            "📊 <b>PKL Finder - Dashboard Otonom</b>\n\n"
            f"🏢 Perusahaan Diselidiki: <code>{comp_count}</code>\n"
            f"🌐 Hasil Discovery Google: <code>{disc_comp}</code>\n"
            f"📧 Email Rekrutmen Ketemu: <code>{emails_count}</code>\n\n"
            f"💼 Total Lowongan Magang: <code>{stats['total_jobs']}</code>\n"
            f"🎯 Lolos Evaluasi AI: <code>{stats['recommended_jobs']}</code>\n"
            f"⭐ Lowongan Favorit: <code>{stats['favorites_count']}</code>\n\n"
            f"✉️ <b>Status Aplikasi Email:</b>\n"
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

@admin_only
@error_boundary
async def queue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List pending drafts in the approval queue."""
    async with async_session_maker() as session:
        stmt = select(EmailQueue).options(selectinload(EmailQueue.company)).where(EmailQueue.status == "draft").limit(5)
        res = await session.execute(stmt)
        drafts = res.scalars().all()

        if not drafts:
            await update.message.reply_text("📭 Antrean draft email kosong.")
            return

        await update.message.reply_text(f"✉️ <b>Daftar Draft Email Pending ({len(drafts)} pertama):</b>", parse_mode="HTML")
        for draft in drafts:
            text = (
                f"🏢 <b>Perusahaan:</b> <code>{draft.company.name}</code>\n"
                f"📧 <b>Penerima:</b> <code>{draft.recipient_email}</code>\n"
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

@admin_only
@error_boundary
async def sendall_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ <i>Mulai mendispatch semua email approved...</i>", parse_mode="HTML")
    
    async with async_session_maker() as session:
        stmt = select(EmailQueue).where(EmailQueue.status == "approved")
        res = await session.execute(stmt)
        approved_emails = res.scalars().all()
        
        if not approved_emails:
            await update.message.reply_text("📭 Tidak ada email dengan status 'approved' dalam antrean.")
            return

        sent_count = 0
        failed_count = 0
        for email in approved_emails:
            try:
                success = await email_service.send_email(session, email.id)
                if success:
                    sent_count += 1
            except Exception as se:
                logger.error(f"Failed to send email ID {email.id}: {se}")
                failed_count += 1
                
        await update.message.reply_text(
            f"✅ Dispatch Selesai!\n- Terkirim: <code>{sent_count}</code>\n- Gagal: <code>{failed_count}</code>",
            parse_mode="HTML"
        )

# ----------------- MSG DISCOVERY & BROWSER -----------------

@admin_only
@error_boundary
async def companies_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session_maker() as session:
        stmt = select(Company).limit(15)
        res = await session.execute(stmt)
        companies = res.scalars().all()
        
        if not companies:
            await update.message.reply_text("📭 Tidak ada perusahaan terdaftar.")
            return
            
        comp_text = "🏢 <b>Daftar Perusahaan Diselidiki:</b>\n\n"
        for comp in companies:
            status = "📧" if comp.recruitment_email else "🌐"
            comp_text += f"{status} {comp.name} (<a href='{comp.website}'>Website</a>)\n"
            
        await update.message.reply_text(comp_text, parse_mode="HTML", disable_web_page_preview=True)

# ----------------- GENERIC DOCUMENT / TEXT INPUTS -----------------

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes PDF/Word doc uploads based on user state."""
    state = context.user_data.get("state")
    if not state or state not in ["AWAITING_CV", "AWAITING_PORTFOLIO"]:
        return

    doc = update.message.document
    file_info = await doc.get_file()
    file_bytes = await file_info.download_as_bytearray()

    async with async_session_maker() as session:
        if state == "AWAITING_CV":
            try:
                await cv_service.save_cv(session, doc.file_name, bytes(file_bytes))
                await update.message.reply_text("✅ <b>CV Berhasil Diunggah!</b> Teks berhasil diekstrak untuk pencocokan AI.", parse_mode="HTML")
            except Exception as e:
                await update.message.reply_text(f"❌ Gagal memproses CV: {e}")
            finally:
                context.user_data["state"] = None
                
        elif state == "AWAITING_PORTFOLIO":
            # Save file path reference
            os.makedirs("data/portfolios", exist_ok=True)
            local_path = os.path.join("data/portfolios", doc.file_name)
            with open(local_path, "wb") as f:
                f.write(bytes(file_bytes))
                
            portfolio = Portfolio(file_path=local_path)
            session.add(portfolio)
            await session.commit()
            await update.message.reply_text("✅ <b>File Portfolio Berhasil Diunggah!</b>", parse_mode="HTML")
            context.user_data["state"] = None

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """State machine processing for text setup replies."""
    state = context.user_data.get("state")
    if not state:
        return

    text = update.message.text.strip()
    
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

    elif state == "SMTP_USER":
        pass # state falls through

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
            portfolio = Portfolio(github_url=text if "github" in text else None, website_url=text if "github" not in text else None)
            session.add(portfolio)
            await session.commit()
        await update.message.reply_text("✅ <b>URL Portfolio Berhasil Disimpan!</b>", parse_mode="HTML")
        context.user_data["state"] = None

    # 3. Cover Letter template
    elif state == "AWAITING_COVER_LETTER":
        async with async_session_maker() as session:
            cl = CoverLetter(text=text)
            session.add(cl)
            await session.commit()
        await update.message.reply_text("✅ <b>Template Cover Letter Berhasil Disimpan!</b>", parse_mode="HTML")
        context.user_data["state"] = None

    # 4. Awaiting Edit Email Draft Body
    elif state.startswith("AWAITING_EDIT_BODY:"):
        draft_id = int(state.split(":")[1])
        async with async_session_maker() as session:
            stmt = select(EmailQueue).where(EmailQueue.id == draft_id)
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
    if not query or not query.data:
        return
        
    await query.answer()
    
    if query.from_user.id != settings.TELEGRAM_ADMIN_ID:
        return

    data = query.data
    try:
        action, entity_id_str = data.split(":")
        entity_id = int(entity_id_str)
        
        async with async_session_maker() as session:
            if action in ["fav", "unfav"]:
                # Favorite operations
                stmt = select(Job).options(selectinload(Job.ai_score)).where(Job.id == entity_id)
                res = await session.execute(stmt)
                job = res.scalar_one_or_none()
                if not job:
                    return

                if action == "fav":
                    success = await job_service.add_favorite(entity_id)
                    if success:
                        await query.edit_message_reply_markup(reply_markup=get_job_keyboard(job, is_fav=True))
                elif action == "unfav":
                    success = await job_service.remove_favorite(entity_id)
                    if success:
                        await query.edit_message_reply_markup(reply_markup=get_job_keyboard(job, is_fav=False))

            elif action == "approve":
                # Queue approval operations
                stmt = select(EmailQueue).where(EmailQueue.id == entity_id)
                res = await session.execute(stmt)
                draft = res.scalar_one_or_none()
                if draft:
                    draft.status = "approved"
                    await session.commit()
                    await query.edit_message_text(f"✅ <b>Draft Email Disetujui (Approved)</b>\nReady to send to: <code>{draft.recipient_email}</code>", parse_mode="HTML")
            
            elif action == "reject":
                # Queue rejection
                stmt = select(EmailQueue).where(EmailQueue.id == entity_id)
                res = await session.execute(stmt)
                draft = res.scalar_one_or_none()
                if draft:
                    draft.status = "rejected"
                    await session.commit()
                    await query.edit_message_text(f"❌ <b>Draft Email Ditolak (Rejected)</b>\nRecipient: <code>{draft.recipient_email}</code>", parse_mode="HTML")

            elif action == "send":
                # Instant send
                stmt = select(EmailQueue).where(EmailQueue.id == entity_id)
                res = await session.execute(stmt)
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
                # Trigger edit conversation
                context.user_data["state"] = f"AWAITING_EDIT_BODY:{entity_id}"
                await query.message.reply_text(
                    "✏️ <b>Kirimkan konten body email baru untuk menggantikan draft saat ini:</b>",
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"Error handling callback button: {e}", exc_info=True)

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
    
    # SMTP configs
    application.add_handler(CommandHandler("credentials", credentials_handler))
    application.add_handler(CommandHandler("email", settings_handler if False else email_handler_fallback if False else start_handler)) # mapping to settings or configs
    
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
    
    # Document upload parsing message router
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    
    # State machine message text handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    # Buttons callbacks
    application.add_handler(CallbackQueryHandler(callback_handler))

# Helper to bypass command overrides
async def email_handler_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with async_session_maker() as session:
        config = await email_service.get_active_config(session)
    if config:
        await update.message.reply_text(f"📧 <b>SMTP Terkonfigurasi:</b>\nHost: <code>{config.host}</code>\nPort: <code>{config.port}</code>\nUser: <code>{config.username}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("📭 SMTP belum dikonfigurasi. Jalankan /credentials.")
