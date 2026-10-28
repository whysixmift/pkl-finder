# PKL Finder - Multi-Tenant AI Internship Hunter SaaS

PKL Finder adalah platform SaaS otomatisasi pencarian magang/PKL (Praktik Kerja Lapangan) dan pengiriman cold email berbasis Multi-Agent System (`1 Feature = 1 Agent`). Sistem ini mengintegrasikan crawler lowongan kerja multi-platform, evaluasi semantik AI menggunakan LLM via OpenRouter, drafting cold email otomatis berlampiran CV fisik, integrasi Google SSO (Gmail API OAuth2), antarmuka Telegram Bot (Port 20128), serta Web SaaS Platform & Admin Dashboard interaktif (Port 20129).

---

## Arsitektur Dual-Port VPS

Aplikasi dirancang dengan arsitektur dual-service independen yang dapat dideploy di VPS:

```
                              +-------------------------------------------+
                              |              VPS HOST SERVER              |
                              +-------------------------------------------+
                                            /               \
                                           /                 \
                                  PORT 20128                 PORT 20129
                                       |                          |
                                       v                          v
                        +----------------------------+  +----------------------------+
                        |    TELEGRAM BOT BRANCH     |  |       WEB SAAS BRANCH      |
                        | - Bot Polling / Webhook    |  | - FastAPI Web Server       |
                        | - Health Service           |  | - Admin Dashboard          |
                        | - Status & Metrics         |  | - Google OAuth2 Callbacks  |
                        +----------------------------+  +----------------------------+
                                       \                          /
                                        \                        /
                                         v                      v
                                +-----------------------------------+
                                |     SHARED MULTI-AGENT ENGINE     |
                                |       (1 Feature = 1 Agent)       |
                                +-----------------------------------+
                                                  |
                                                  v
                                +-----------------------------------+
                                |    SQLAlchemy 2.0 (SQLite / DB)   |
                                +-----------------------------------+
```

- **Port `20128` (Bot Branch)**: Menjalankan listener Telegram Bot dan endpoint HTTP `/health` serta `/metrics`.
- **Port `20129` (Web SaaS Branch)**: Menjalankan antarmuka SaaS Web, Google OAuth2 SSO callback, dan Admin Dashboard interaktif.

---

## Multi-Agent Architecture ("1 Feature = 1 Agent")

Seluruh fungsionalitas modular diisolasi ke dalam agen-agen otonom di `app/agents/`, mewarisi `BaseAgent` dengan pelacakan telemetri real-time:

| Agen | File | Deskripsi Fitur |
| :--- | :--- | :--- |
| **ScraperAgent** | [`app/agents/scraper_agent.py`](file:///home/avrjulian/pkl-finder/app/agents/scraper_agent.py) | Crawler agregator lowongan magang dari Glints, LinkedIn, Indeed, JobStreet, Kalibrr, dan Google Jobs. |
| **DiscoveryAgent** | [`app/agents/discovery_agent.py`](file:///home/avrjulian/pkl-finder/app/agents/discovery_agent.py) | Harvesting data PT baru dan email rekrutmen/HR secara otomatis dari direktori web. |
| **CVAgent** | [`app/agents/cv_agent.py`](file:///home/avrjulian/pkl-finder/app/agents/cv_agent.py) | Ekstraksi teks CV (`.pdf`, `.docx`), penyimpanan fisik file CV di `data/cvs/`, dan pemetaan skill. |
| **MatchingAgent** | [`app/agents/matching_agent.py`](file:///home/avrjulian/pkl-finder/app/agents/matching_agent.py) | Evaluasi kesesuaian semantik antara profil CV siswa dan kualifikasi lowongan menggunakan LLM OpenRouter. |
| **EmailDraftingAgent** | [`app/agents/email_drafting_agent.py`](file:///home/avrjulian/pkl-finder/app/agents/email_drafting_agent.py) | Pembuatan draft cold email personalisasi berdasarkan profil kandidat dan info PT tujuan, otomatis melampirkan file CV fisik. |
| **EmailDispatchAgent** | [`app/agents/email_dispatch_agent.py`](file:///home/avrjulian/pkl-finder/app/agents/email_dispatch_agent.py) | Pengiriman email otomatis multi-protokol: prioritas via Google SSO (Gmail API `gmail.send`), fallback ke SMTP terenkripsi. |
| **AccessControlAgent** | [`app/agents/access_control_agent.py`](file:///home/avrjulian/pkl-finder/app/agents/access_control_agent.py) | Whitelist akses bot berbasis SaaS, mendukung otentikasi via **Telegram Username** (`@user`) maupun **User ID** (numerik). |
| **SchedulerAgent** | [`app/agents/scheduler_agent.py`](file:///home/avrjulian/pkl-finder/app/agents/scheduler_agent.py) | Pengatur jadwal otomatis di latar belakang untuk crawling berkala, evaluasi match, dan pemeliharaan antrean. |

---

## Google SSO & Otomatisasi Pengiriman Email dengan CV

1. **Google SSO Authorization**:
   - Pengguna dapat menghubungkan akun Google mereka via command Telegram `/connect_google` atau via Web di `http://<IP_VPS>:20129/auth/google`.
   - Menggunakan scope `https://www.googleapis.com/auth/gmail.send` untuk izin pengiriman email langsung atas nama pengguna tanpa perlu konfigurasi App Password SMTP yang rumit.
   - Token OAuth2 disimpan secara terenkripsi (AES-Fernet) di tabel `user_google_auth` dan diperbarui secara otomatis saat kedaluwarsa.
2. **Auto-Attach CV Fisik**:
   - File CV asli yang diunggah pengguna (`.pdf` atau `.docx`) disimpan secara persisten di folder `data/cvs/`.
   - Ketika `EmailDraftingAgent` membuat draft, path file CV langsung ditautkan ke kolom `attachment_path` pada `email_queue`.
   - `EmailDispatchAgent` secara otomatis menyematkan file CV tersebut sebagai lampiran MIME saat email dikirim ke HR/rekrutmen PT tujuan.

---

## Web SaaS & Admin Dashboard (Port 20129)

Akses Admin Dashboard tersedia melalui browser di:
```
http://<IP_VPS_ATAU_DOMAIN>:20129/admin
```

- **Password Admin**: `uranium235aregoated`
- **Fitur Dashboard**:
  - **Overview Metrics**: Total PT dicari, lowongan aktif, antrean email, dan pengguna terdaftar.
  - **PT & Company Catalog**: Daftar lengkap PT hasil pencarian scraper & discovery, lengkap dengan status, industri, dan kontak email HR.
  - **User Whitelist Management**:
    - Tambah pengguna bot menggunakan **Telegram Username** (contoh: `@username` atau `username`) **ATAU Telegram User ID** (contoh: `123456789`).
    - Pengguna yang didaftarkan langsung mendapatkan hak akses untuk menggunakan seluruh fitur bot seketika.
    - Opsi toggle status aktif/non-aktif dan hapus akses user.
  - **Environment (.env) Manager**:
    - **Visual Form Editor**: Edit Telegram Bot Token, OpenRouter API Keys, Google SSO Credentials, Port VPS (20128/20129), dan kriteria pencarian dengan toggle show/hide password.
    - **Raw .env Editor**: Editor teks mentah langsung di browser untuk paste konfigurasi secara cepat tanpa perlu membuka SSH terminal VPS.
    - **Live In-Memory Reload**: Perubahan langsung dimuat ke runtime aplikasi secara otomatis.
  - **Agent Telemetry**: Monitoring status hidup dan histori eksekusi dari ke-8 agen.
  - **Email Queue Management**: Pemantauan status draft, email terkirim, dan status lampiran CV.

---

## Cara Menjalankan & Deploy ke VPS

### 1. Konfigurasi Lingkungan (`.env`)
Salin file template `.env.example` ke `.env` lalu sesuaikan kredensial Anda:
```bash
cp .env.example .env
nano .env
```

Konfigurasi kunci yang wajib diisi:
```env
TELEGRAM_BOT_TOKEN="your_bot_token_from_botfather"
TELEGRAM_ADMIN_ID=999999999
OPENROUTER_API_KEY="your_openrouter_api_key"

# Port Dual-Branch
BOT_PORT=20128
WEB_PORT=20129

# Admin Dashboard Password
ADMIN_PASSWORD=uranium235aregoated

# Google SSO (OAuth 2.0 Client Credentials)
GOOGLE_CLIENT_ID="your_google_client_id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your_google_client_secret"
GOOGLE_REDIRECT_URI="http://localhost:20129/auth/google/callback"
```

### 2. Opsi A: Menjalankan Menggunakan Python Langsung
Pastikan virtual environment telah aktif:
```bash
source .venv/bin/activate
```

- **Menjalankan Seluruh Service (Bot Port 20128 & Web Port 20129)**:
  ```bash
  python main.py all
  ```
- **Menjalankan Bot Branch Saja**:
  ```bash
  python main.py bot
  ```
- **Menjalankan Web SaaS Branch Saja**:
  ```bash
  python main.py web
  ```

### 3. Opsi B: Deploy Menggunakan Docker Compose (Rekomendasi VPS)
Jalankan perintah berikut pada direktori project:
```bash
docker compose up --build -d
```
Container akan secara otomatis membuka dan memetakan:
- Port `20128:20128` (Telegram Bot & Service)
- Port `20129:20129` (Web SaaS & Admin Dashboard)

Melihat log aplikasi secara realtime:
```bash
docker compose logs -f
```

---

## Perintah Telegram Bot

### Pengguna Umum
- `/start` - Handshake awal dan status otorisasi akun.
- `/help` - Panduan lengkap penggunaan bot.
- `/uploadcv` - Mengunggah file CV (`.pdf` / `.docx`).
- `/connect_google` - Menghubungkan akun Google (Gmail API SSO) untuk pengiriman email otomatis.
- `/credentials` - Opsi alternatif konfigurasi SMTP manual.
- `/search` - Menjalankan crawling dan pencarian lowongan PKL sesuai profil CV.
- `/latest` - Melihat rekomendasi lowongan terbaru.
- `/queue` - Memeriksa draft email lamaran (Approve / Edit / Kirim).
- `/sendall` - Mengirim semua draft email yang telah disetujui beserta lampiran CV.
- `/agents` - Menampilkan status telemetri dari seluruh AI Agent.

### Administrator
- `/whitelist <username/id> [catatan]` - Menambahkan user ke whitelist langsung dari chat bot.
- `/health` - Status kesehatan sistem, database, dan koneksi LLM.
- `/metrics` - Metrik konversi dan statistik pengiriman email.

---

## Verifikasi Pengujian

Seluruh fitur telah diverifikasi dengan suite pengujian otomatis (`pytest`):
```bash
.venv/bin/pytest -v -W ignore::DeprecationWarning
```
Hasil pengujian: **37 passed, 0 failed**.
