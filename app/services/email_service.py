import os
import json
from datetime import datetime
import smtplib
import asyncio
import socket
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import List, Optional
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import SMTPConfig, EmailQueue
from app.utils.logger import logger

# Initialize encryption keys
SECRET_KEY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "secret.key"
)

def get_encryption_key() -> bytes:
    """Generate and load static encryption key stored in data volume."""
    if os.path.exists(SECRET_KEY_PATH):
        try:
            with open(SECRET_KEY_PATH, "rb") as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"Error reading encryption key: {e}")
            
    try:
        os.makedirs(os.path.dirname(SECRET_KEY_PATH), exist_ok=True)
        key = Fernet.generate_key()
        with open(SECRET_KEY_PATH, "wb") as f:
            f.write(key)
        return key
    except Exception as e:
        logger.error(f"Failed to save generated key, returning a temporary key: {e}")
        return Fernet.generate_key()

CIPHER = Fernet(get_encryption_key())

def encrypt_password(password: str) -> str:
    return CIPHER.encrypt(password.encode("utf-8")).decode("utf-8")

def decrypt_password(encrypted_password: str) -> str:
    return CIPHER.decrypt(encrypted_password.encode("utf-8")).decode("utf-8")


class EmailService:
    async def configure_smtp(
        self,
        session: AsyncSession,
        user_id: int,
        host: str,
        port: int,
        username: str,
        password: str,
        encryption_type: str,
        sender_name: str,
        signature: str
    ) -> SMTPConfig:
        """Saves and validates SMTP credentials for a user."""
        encryption_type = encryption_type.upper()
        if encryption_type not in ["SSL", "TLS", "NONE"]:
            raise ValueError("Tipe enkripsi harus SSL, TLS, atau NONE.")

        encrypted_pwd = encrypt_password(password)

        # Check if config already exists for user
        stmt = select(SMTPConfig).where(SMTPConfig.user_id == user_id)
        res = await session.execute(stmt)
        config = res.scalar_one_or_none()

        if config:
            config.host = host
            config.port = port
            config.username = username
            config.password_encrypted = encrypted_pwd
            config.encryption_type = encryption_type
            config.sender_name = sender_name
            config.signature = signature
            config.is_active = True
        else:
            config = SMTPConfig(
                user_id=user_id,
                host=host,
                port=port,
                username=username,
                password_encrypted=encrypted_pwd,
                encryption_type=encryption_type,
                sender_name=sender_name,
                signature=signature,
                is_active=True
            )
            session.add(config)

        await session.commit()
        
        # Verify connectivity
        await self.test_smtp_config(config)
        return config

    async def get_active_config(self, session: AsyncSession, user_id: int) -> Optional[SMTPConfig]:
        """Fetch active SMTP configuration for a user."""
        stmt = select(SMTPConfig).where((SMTPConfig.user_id == user_id) & (SMTPConfig.is_active.is_(True))).limit(1)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def test_smtp_config(self, config: SMTPConfig) -> None:
        """Sync test for SMTP credentials connectivity executed in a thread pool."""
        def _test():
            pwd = decrypt_password(config.password_encrypted)
            
            # 1. Establish socket and security connection
            try:
                if config.encryption_type == "SSL":
                    try:
                        server = smtplib.SMTP_SSL(config.host, config.port, timeout=10)
                    except ssl.SSLError as e:
                        raise ValueError(f"SSL Mismatch: Gagal menghubungkan menggunakan enkripsi SSL ke {config.host}:{config.port}. "
                                         f"Kemungkinan port ini tidak mendukung SSL. Detail: {e}")
                else:
                    server = smtplib.SMTP(config.host, config.port, timeout=10)
                    if config.encryption_type == "TLS":
                        try:
                            server.ehlo()
                            if not server.has_ext("STARTTLS"):
                                raise ValueError(f"STARTTLS Mismatch: Server SMTP {config.host}:{config.port} tidak mendukung STARTTLS. "
                                                 f"Silakan gunakan tipe enkripsi SSL atau port yang sesuai.")
                            server.starttls()
                            server.ehlo()
                        except smtplib.SMTPNotSupportedError as e:
                            raise ValueError(f"STARTTLS Mismatch: Enkripsi STARTTLS tidak didukung oleh server. Detail: {e}")
                        except ssl.SSLError as e:
                            raise ValueError(f"STARTTLS Handshake Error: Gagal jabat tangan SSL/TLS saat STARTTLS. Detail: {e}")
            except (socket.timeout, TimeoutError) as e:
                raise ValueError(f"SMTP Connection Timeout: Waktu koneksi habis saat menghubungkan ke {config.host}:{config.port}. Detail: {e}")
            except (ConnectionRefusedError, socket.gaierror) as e:
                raise ValueError(f"SMTP Connection Refused / DNS Error: Gagal menghubungi server {config.host}:{config.port}. Detail: {e}")
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"SMTP Connection Error: Gagal menghubungi server SMTP {config.host}:{config.port}. Detail: {e}")
            
            # 2. Authenticate
            try:
                server.login(config.username, pwd)
            except smtplib.SMTPAuthenticationError as e:
                raise ValueError(f"SMTP Authentication Failure: Kredensial login salah untuk pengguna '{config.username}'. "
                                 f"Pastikan email dan password aplikasi (app password) Anda benar. Detail: {e}")
            except Exception as e:
                raise ValueError(f"SMTP Authentication Error: Gagal melakukan proses autentikasi. Detail: {e}")
            finally:
                try:
                    server.quit()
                except Exception:
                    pass

        await asyncio.to_thread(_test)

    async def queue_email_draft(
        self,
        session: AsyncSession,
        user_id: int,
        company_id: int,
        recipient_email: str,
        subject: str,
        body: str,
        source: str,
        job_id: Optional[int] = None,
        attachments: Optional[List[str]] = None
    ) -> EmailQueue:
        """Saves a generated email draft to the queue for a user."""
        draft = EmailQueue(
            user_id=user_id,
            company_id=company_id,
            job_id=job_id,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            source=source,
            status="draft",
            attachments=json.dumps(attachments) if attachments else None
        )
        session.add(draft)
        await session.commit()
        return draft

    async def send_email(self, session: AsyncSession, email_id: int) -> bool:
        """Dispatch queued email draft using SMTP configuration."""
        stmt = select(EmailQueue).where(EmailQueue.id == email_id)
        res = await session.execute(stmt)
        email = res.scalar_one_or_none()
        
        if not email or email.status in ["sent", "sending"]:
            return False

        config = await self.get_active_config(session, email.user_id)
        if not config:
            email.status = "failed"
            email.error_message = f"SMTP Credentials not configured for user {email.user_id}."
            await session.commit()
            raise ValueError(f"SMTP Config is missing for user {email.user_id}. Configure SMTP via Telegram.")

        email.status = "sending"
        await session.commit()

        def _send():
            pwd = decrypt_password(config.password_encrypted)
            
            # Setup MIME message
            msg = MIMEMultipart()
            msg["From"] = f"{config.sender_name} <{config.username}>"
            msg["To"] = email.recipient_email
            msg["Subject"] = email.subject
            
            full_body = email.body
            if config.signature:
                full_body += f"\n\n--\n{config.signature}"
                
            msg.attach(MIMEText(full_body, "plain", "utf-8"))

            if email.attachments:
                try:
                    file_paths = json.loads(email.attachments)
                    for path in file_paths:
                        if os.path.exists(path):
                            with open(path, "rb") as f:
                                part = MIMEApplication(f.read(), Name=os.path.basename(path))
                            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
                            msg.attach(part)
                except Exception as e:
                    logger.error(f"Error processing attachments for email {email_id}: {e}")

            # 1. Establish connection
            try:
                if config.encryption_type == "SSL":
                    try:
                        server = smtplib.SMTP_SSL(config.host, config.port, timeout=20)
                    except ssl.SSLError as e:
                        raise ValueError(f"SSL Mismatch: Gagal menghubungkan menggunakan enkripsi SSL ke {config.host}:{config.port}. Detail: {e}")
                else:
                    server = smtplib.SMTP(config.host, config.port, timeout=20)
                    if config.encryption_type == "TLS":
                        try:
                            server.ehlo()
                            if not server.has_ext("STARTTLS"):
                                raise ValueError(f"STARTTLS Mismatch: Server SMTP {config.host}:{config.port} tidak mendukung STARTTLS.")
                            server.starttls()
                            server.ehlo()
                        except smtplib.SMTPNotSupportedError as e:
                            raise ValueError(f"STARTTLS Mismatch: Enkripsi STARTTLS tidak didukung oleh server. Detail: {e}")
                        except ssl.SSLError as e:
                            raise ValueError(f"STARTTLS Handshake Error: Gagal jabat tangan SSL/TLS saat STARTTLS. Detail: {e}")
            except (socket.timeout, TimeoutError) as e:
                raise ValueError(f"SMTP Connection Timeout: Waktu koneksi habis saat menghubungkan ke {config.host}:{config.port}. Detail: {e}")
            except (ConnectionRefusedError, socket.gaierror) as e:
                raise ValueError(f"SMTP Connection Refused / DNS Error: Gagal menghubungi server {config.host}:{config.port}. Detail: {e}")
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"SMTP Connection Error: Gagal menghubungi server SMTP {config.host}:{config.port}. Detail: {e}")
            
            # 2. Login & Send
            try:
                server.login(config.username, pwd)
                server.send_message(msg)
            except smtplib.SMTPAuthenticationError as e:
                raise ValueError(f"SMTP Authentication Failure: Kredensial login salah untuk '{config.username}'. Detail: {e}")
            except Exception as e:
                raise ValueError(f"SMTP Send Error: Gagal saat otentikasi/pengiriman pesan. Detail: {e}")
            finally:
                try:
                    server.quit()
                except Exception:
                    pass

        try:
            await asyncio.to_thread(_send)
            email.status = "sent"
            email.sent_at = datetime.utcnow()
            email.error_message = None
            await session.commit()
            logger.info(f"Email ID {email_id} successfully sent to {email.recipient_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to dispatch email ID {email_id}: {e}", exc_info=True)
            email.status = "failed"
            email.error_message = str(e)
            await session.commit()
            raise e

# Shared instance
email_service = EmailService()
