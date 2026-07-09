# Deployment Guide

This document describes how to deploy the PKL Finder bot on a local server or a virtual private server (VPS) running Ubuntu.

## Docker Deployment

Deploying the bot with Docker is the recommended method. This runs the application in an isolated container and ensures it restarts automatically on system reboots.

### 1. Build and Run
Build the container and start the services in the background:

```bash
docker compose up --build -d
```

### 2. Monitoring Logs
Monitor container logs in real-time:

```bash
docker compose logs -f
```

### 3. Stop Services
Stop the container and preserve stored data and logs:

```bash
docker compose down
```

---

## Linux VPS Deployment (Ubuntu)

### 1. Install Docker and Docker Compose
Install Docker and Docker Compose on a fresh Ubuntu instance:

```bash
sudo apt update
sudo apt install -y git curl docker.io docker-compose
sudo systemctl enable --now docker
```

### 2. Clone the Repository
Clone the project repository and copy the environment template:

```bash
git clone https://github.com/your-username/pkl-finder.git
cd pkl-finder
cp .env.example .env
```

### 3. Configure the Environment
Edit the `.env` file and insert your API keys and configuration settings:

```bash
nano .env
```

### 4. Run the Application
Start the Docker containers:

```bash
sudo docker-compose up -d
```

---

## Alternative: Systemd Service (Non-Docker)

If you prefer not to use Docker, you can run the bot as a systemd service directly on your Ubuntu host.

### 1. Setup the Virtual Environment
Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create the Systemd Service File
Create a new service configuration file:

```bash
sudo nano /etc/systemd/system/pkl-finder.service
```

Add the following configuration:

```ini
[Unit]
Description=PKL Finder Telegram Bot Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/pkl-finder
EnvironmentFile=/home/ubuntu/pkl-finder/.env
ExecStart=/home/ubuntu/pkl-finder/.venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=pkl-finder

[Install]
WantedBy=multi-user.target
```

### 3. Enable and Start the Service
Reload systemd, enable the service to start on boot, and start the bot:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pkl-finder
sudo systemctl start pkl-finder
```

### 4. Monitor Systemd Logs
View service logs using `journalctl`:

```bash
journalctl -u pkl-finder -f
```

---

## Backup and Maintenance Strategy

### 1. Automated Backups
SQLite databases should be backed up regularly to prevent data loss. Create a shell script named `backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/home/ubuntu/backups"
DB_FILE="/home/ubuntu/pkl-finder/data/jobs.db"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/jobs_backup_$TIMESTAMP.db'"
find "$BACKUP_DIR" -name "jobs_backup_*.db" -mtime +14 -delete
```

Set executable permissions and schedule the script to run daily using a cron job:

```bash
chmod +x backup.sh
crontab -e
```

Add the following line to run the backup every day at midnight:

```cron
0 0 * * * /home/ubuntu/backup.sh
```

### 2. Updating the Application
To update the bot, pull the latest changes, rebuild the container, and restart services:

```bash
git pull origin main
docker compose down
docker compose up --build -d
```
