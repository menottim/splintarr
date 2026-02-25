# Advanced Deployment

If you want to do more than the basic Docker setup, here are some optional
enhancements for your homelab. None of these are required -- the standard
`docker-compose up -d` workflow from the
[Docker Deployment Guide](./deploy-with-docker.md) is perfectly fine for most
users.

This guide covers running on dedicated Linux hardware, adding HTTPS on your
local network, managing database migrations, and a few performance tweaks.

---

## Running on a Linux Server

### Supported Platforms

Vibe-Quality-Searcharr runs well on common homelab hardware:

- Raspberry Pi 4/5 (arm64) with 2 GB+ RAM
- Synology, QNAP, or TrueNAS with Docker support
- Proxmox / VMware VMs running Debian or Ubuntu
- Any x86_64 or arm64 Linux box

### System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 1 core | 2 cores |
| RAM | 512 MB | 1 GB |
| Disk | 500 MB | 2 GB |
| OS | Any Linux with Docker | Debian 12 / Ubuntu 22.04+ |

### Running as a systemd Service (Without Docker)

If you prefer to run directly on the host instead of in a container, you can
use a systemd unit. This is useful on minimal installs where you do not want
Docker overhead.

**Install dependencies and clone:**
```bash
sudo apt update
sudo apt install python3.13 python3.13-venv python3-pip sqlcipher libsqlcipher-dev
curl -sSL https://install.python-poetry.org | python3 -
git clone https://github.com/menottim/vibe-quality-searcharr.git /opt/vibe-quality-searcharr
cd /opt/vibe-quality-searcharr
poetry install --no-dev
```

**Generate secrets and create a service user:**
```bash
mkdir -p /opt/vibe-quality-searcharr/secrets && chmod 700 /opt/vibe-quality-searcharr/secrets
python3 -c "import secrets; print(secrets.token_urlsafe(64))" > /opt/vibe-quality-searcharr/secrets/secret_key
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > /opt/vibe-quality-searcharr/secrets/pepper
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > /opt/vibe-quality-searcharr/secrets/db_key
chmod 600 /opt/vibe-quality-searcharr/secrets/*
sudo useradd --system --no-create-home --shell /usr/sbin/nologin appuser
sudo chown -R appuser:appuser /opt/vibe-quality-searcharr
```

**Create the systemd unit** at `/etc/systemd/system/vibe-quality-searcharr.service`:
```ini
[Unit]
Description=Vibe-Quality-Searcharr
After=network.target

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/vibe-quality-searcharr
Environment="SECRET_KEY_FILE=/opt/vibe-quality-searcharr/secrets/secret_key"
Environment="PEPPER_FILE=/opt/vibe-quality-searcharr/secrets/pepper"
Environment="DATABASE_KEY_FILE=/opt/vibe-quality-searcharr/secrets/db_key"
Environment="ENVIRONMENT=production"
ExecStart=/opt/vibe-quality-searcharr/.venv/bin/uvicorn vibe_quality_searcharr.main:app --host 0.0.0.0 --port 7337
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vibe-quality-searcharr
sudo systemctl status vibe-quality-searcharr
```

---

## Optional: Reverse Proxy for HTTPS

You do **not** need HTTPS to use Vibe-Quality-Searcharr on your local network.
However, if you want encrypted connections (for example, to avoid browser
warnings or to protect API keys in transit on an untrusted VLAN), a reverse
proxy is the simplest way to add TLS.

### Option 1: Caddy (Simplest)

Caddy is popular in homelab setups because it handles TLS certificates
automatically with almost no configuration. If you use a local domain like
`searcharr.home.lan`, Caddy generates a self-signed certificate automatically.
If you point a real domain at your LAN IP, Caddy obtains a Let's Encrypt
certificate for you.

Install Caddy following the [official instructions](https://caddyserver.com/docs/install),
then create `/etc/caddy/Caddyfile`:

```
searcharr.home.lan {
    reverse_proxy localhost:7337
}
```

That is the entire configuration. Restart Caddy after editing:
```bash
sudo systemctl restart caddy
```

If you use a `.lan` or `.local` domain, your browser will warn about the
self-signed certificate. You can trust Caddy's root CA on your devices by
running `caddy trust` on the Caddy host.

### Option 2: nginx

If you already run nginx on your homelab, add a site configuration:

```nginx
# /etc/nginx/sites-available/vibe-quality-searcharr
server {
    listen 80;
    server_name searcharr.home.lan;
    return 301 https://$server_name$request_uri;
}
server {
    listen 443 ssl http2;
    server_name searcharr.home.lan;
    ssl_certificate     /etc/nginx/ssl/searcharr.crt;
    ssl_certificate_key /etc/nginx/ssl/searcharr.key;
    location / {
        proxy_pass http://127.0.0.1:7337;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and reload:
```bash
sudo ln -s /etc/nginx/sites-available/vibe-quality-searcharr /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Generate a self-signed certificate if you do not have a real domain:
```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/searcharr.key \
  -out /etc/nginx/ssl/searcharr.crt \
  -subj "/CN=searcharr.home.lan"
```

### Note on SECURE_COOKIES

When you access the app over HTTPS (through any reverse proxy), set
`SECURE_COOKIES=true` in your environment so session cookies are sent only over
encrypted connections. If you access the app over plain HTTP, leave it as
`false` (the default).

---

## Database Migrations with Alembic

Vibe-Quality-Searcharr uses Alembic for database schema migrations. When
running via Docker, migrations are applied automatically on container start. If
you run directly on the host, or need to manage migrations manually, use the
commands below.

**Common commands (from the project root):**
```bash
poetry run alembic current           # check current schema version
poetry run alembic upgrade head      # apply all pending migrations
poetry run alembic downgrade -1      # roll back one migration
poetry run alembic history           # view migration history
```

**Running migrations inside Docker:**
```bash
docker compose exec vibe-quality-searcharr alembic upgrade head
```

**Always back up your database before applying migrations:**
```bash
cp data/vibe-quality-searcharr.db "data/backup-$(date +%Y%m%d-%H%M%S).db"
```

---

## Performance Tuning

Vibe-Quality-Searcharr is a lightweight, single-user (or few-user) application.
It runs a single Uvicorn worker by design. There is no need for multi-worker
deployment. A few small tweaks can help on constrained hardware.

### Store the Database on Fast Storage

SQLite performance degrades significantly on high-latency storage (USB drives,
SD cards, network mounts). If your host has both an SD card and an SSD (common
on Raspberry Pi), mount the data volume on the SSD:
```yaml
volumes:
  - /mnt/ssd/vibe-quality-searcharr/data:/data
```

### Docker Resource Limits

On shared homelab hosts, cap the container so it does not starve other services:
```yaml
deploy:
  resources:
    limits:
      cpus: '1'
      memory: 512M
    reservations:
      cpus: '0.25'
      memory: 128M
```

### Reduce Log I/O

Setting `LOG_LEVEL=WARNING` instead of `INFO` reduces disk writes on low-power
devices. Only do this once you are confident the application is running
correctly.

---

## Monitoring

### Health Check

The application exposes a health endpoint:
```bash
curl http://localhost:7337/api/health
```

A healthy response:
```json
{"status": "healthy", "version": "0.1.0", "database": "connected"}
```

### Uptime Monitoring (Optional)

If you run Uptime Kuma, Healthchecks.io, or similar, point an HTTP monitor at
`http://<server-ip>:7337/api/health` with a 60-second interval.

### Viewing Logs

**Docker:**
```bash
docker compose logs -f vibe-quality-searcharr
```

**systemd:**
```bash
sudo journalctl -u vibe-quality-searcharr -f
```

**Application log files** (if the logs directory is mapped):
```bash
tail -f logs/all.log
tail -f logs/error.log
```

---

## Quick Troubleshooting

For detailed troubleshooting, see [troubleshoot.md](./troubleshoot.md). Here
are common issues specific to advanced deployments.

**Service will not start (systemd):**
```bash
sudo journalctl -u vibe-quality-searcharr -n 50 --no-pager
ls -la /opt/vibe-quality-searcharr/secrets/
ls -la /opt/vibe-quality-searcharr/data/
```

**Reverse proxy returns 502 Bad Gateway:**
- Confirm the app is running: `curl http://127.0.0.1:7337/api/health`
- Check that the proxy target matches the port the app is listening on.
- If using Docker, make sure the container port is published (`-p 7337:7337`).

**Database locked errors on NAS:**
SQLite does not work well over network filesystems (NFS, SMB/CIFS). Always
store the database on local or directly-attached storage.

---
*Version 0.1.0 -- Last updated 2026-02-25*
