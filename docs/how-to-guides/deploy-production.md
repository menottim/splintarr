# Deployment Guide
## Vibe-Quality-Searcharr

## System Requirements

### Minimum Requirements
- **CPU:** 1 core
- **RAM:** 512 MB
- **Disk:** 500 MB + storage for database
- **OS:** Linux, macOS, Windows (Docker recommended)
- **Python:** 3.13+ (manual installation only)

### Recommended Requirements
- **CPU:** 2+ cores
- **RAM:** 1 GB
- **Disk:** 2 GB + storage
- **OS:** Linux (Ubuntu 22.04 LTS or Debian 12)
- **Network:** Stable connection to Sonarr/Radarr instances

---

## Installation Methods

### Method 1: Docker (Recommended)

**Single Command:**
```bash
docker run -d \
  --name vibe-quality-searcharr \
  -p 7337:7337 \
  -v $(pwd)/data:/data \
  -v $(pwd)/secrets:/run/secrets:ro \
  -e SECRET_KEY_FILE=/run/secrets/secret_key \
  -e PEPPER_FILE=/run/secrets/pepper \
  -e DATABASE_KEY_FILE=/run/secrets/db_key \
  -e ENVIRONMENT=production \
  --restart unless-stopped \
  vibe-quality-searcharr:latest
```

### Method 2: Docker Compose (Recommended for Production)

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  vibe-quality-searcharr:
    image: vibe-quality-searcharr:latest
    container_name: vibe-quality-searcharr
    restart: unless-stopped
    ports:
      - "7337:7337"
    volumes:
      - ./data:/data
      - ./secrets:/run/secrets:ro
    environment:
      ENVIRONMENT: production
      LOG_LEVEL: INFO
      SECRET_KEY_FILE: /run/secrets/secret_key
      PEPPER_FILE: /run/secrets/pepper
      DATABASE_KEY_FILE: /run/secrets/db_key
      SECURE_COOKIES: "true"
      ALLOW_LOCAL_INSTANCES: "false"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7337/api/health"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 10s
```

**Deploy:**
```bash
# Generate secrets
mkdir -p secrets && chmod 700 secrets
python3 -c "import secrets; print(secrets.token_urlsafe(64))" > secrets/secret_key
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/pepper
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/db_key
chmod 600 secrets/*

# Create data directory
mkdir -p data && chmod 755 data

# Start services
docker-compose up -d

# View logs
docker-compose logs -f
```

### Method 3: Manual Installation

**Prerequisites:**
```bash
# Install Python 3.13+
sudo apt update
sudo apt install python3.13 python3.13-venv python3-pip

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -
```

**Installation:**
```bash
# Clone repository
git clone https://github.com/yourusername/vibe-quality-searcharr.git
cd vibe-quality-searcharr

# Install dependencies
poetry install --no-dev

# Generate secrets
mkdir -p secrets && chmod 700 secrets
python3 -c "import secrets; print(secrets.token_urlsafe(64))" > secrets/secret_key
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/pepper
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/db_key
chmod 600 secrets/*

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Initialize database
poetry run alembic upgrade head

# Run application
poetry run uvicorn vibe_quality_searcharr.main:app \
  --host 0.0.0.0 \
  --port 7337 \
  --workers 2
```

**Systemd Service (Optional):**
```ini
# /etc/systemd/system/vibe-quality-searcharr.service
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
ExecStart=/opt/vibe-quality-searcharr/.venv/bin/uvicorn vibe_quality_searcharr.main:app --host 0.0.0.0 --port 7337
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable vibe-quality-searcharr
sudo systemctl start vibe-quality-searcharr
```

---

## Environment Configuration

### Required Environment Variables

```bash
# Secrets (use _FILE suffix for file-based secrets)
SECRET_KEY=<64-char-random-string>  # or SECRET_KEY_FILE
PEPPER=<32-char-random-string>  # or PEPPER_FILE
DATABASE_KEY=<32-char-random-string>  # or DATABASE_KEY_FILE

# Application
ENVIRONMENT=production  # production, development
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR

# Database
DATABASE_URL=sqlite+pysqlcipher:///:memory:@/data/vibe-quality-searcharr.db?cipher=aes-256-cfb&kdf_iter=256000

# Server
HOST=0.0.0.0
PORT=7337

# Security
SECURE_COOKIES=true  # Requires HTTPS
SESSION_EXPIRE_HOURS=24
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30
ALLOW_LOCAL_INSTANCES=false  # Set true only in dev

# Rate Limiting
API_RATE_LIMIT=100/minute

# CORS
ALLOWED_ORIGINS=https://yourdomain.com

# Trusted Hosts
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
```

### Environment File Example

**.env:**
```bash
# Production Configuration
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO

# Secrets (file-based - recommended)
SECRET_KEY_FILE=/run/secrets/secret_key
PEPPER_FILE=/run/secrets/pepper
DATABASE_KEY_FILE=/run/secrets/db_key

# Database
DATABASE_URL=sqlite+pysqlcipher:///:memory:@/data/vibe-quality-searcharr.db?cipher=aes-256-cfb&kdf_iter=256000

# Server
HOST=0.0.0.0
PORT=7337
WORKERS=2

# Security
SECURE_COOKIES=true
SESSION_EXPIRE_HOURS=24
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30
ALLOW_LOCAL_INSTANCES=false

# Rate Limiting
API_RATE_LIMIT=100/minute

# CORS
ALLOWED_ORIGINS=https://searcharr.yourdomain.com

# Trusted Hosts
ALLOWED_HOSTS=searcharr.yourdomain.com
```

---

## Reverse Proxy Setup

### nginx

**Configuration:**
```nginx
# /etc/nginx/sites-available/vibe-quality-searcharr
upstream vibe_backend {
    server localhost:7337;
}

server {
    listen 80;
    server_name searcharr.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name searcharr.yourdomain.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/searcharr.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/searcharr.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Logging
    access_log /var/log/nginx/vibe-access.log;
    error_log /var/log/nginx/vibe-error.log;

    # Proxy Configuration
    location / {
        proxy_pass http://vibe_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;

        # WebSocket Support (if needed in future)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Rate Limiting (additional layer)
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req zone=api_limit burst=20 nodelay;
}
```

**Enable Configuration:**
```bash
sudo ln -s /etc/nginx/sites-available/vibe-quality-searcharr /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**SSL Certificate (Let's Encrypt):**
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d searcharr.yourdomain.com
```

### Traefik

**docker-compose.yml with Traefik:**
```yaml
version: '3.8'

services:
  traefik:
    image: traefik:v2.10
    container_name: traefik
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik.yml:/traefik.yml:ro
      - ./acme.json:/acme.json
    labels:
      - "traefik.enable=true"

  vibe-quality-searcharr:
    image: vibe-quality-searcharr:latest
    container_name: vibe-quality-searcharr
    restart: unless-stopped
    volumes:
      - ./data:/data
      - ./secrets:/run/secrets:ro
    environment:
      SECRET_KEY_FILE: /run/secrets/secret_key
      PEPPER_FILE: /run/secrets/pepper
      DATABASE_KEY_FILE: /run/secrets/db_key
      ENVIRONMENT: production
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.vibe.rule=Host(`searcharr.yourdomain.com`)"
      - "traefik.http.routers.vibe.entrypoints=websecure"
      - "traefik.http.routers.vibe.tls.certresolver=letsencrypt"
      - "traefik.http.services.vibe.loadbalancer.server.port=7337"
      # Rate Limiting
      - "traefik.http.middlewares.vibe-ratelimit.ratelimit.average=100"
      - "traefik.http.middlewares.vibe-ratelimit.ratelimit.burst=50"
      - "traefik.http.routers.vibe.middlewares=vibe-ratelimit"
```

**traefik.yml:**
```yaml
api:
  dashboard: true

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

providers:
  docker:
    exposedByDefault: false

certificatesResolvers:
  letsencrypt:
    acme:
      email: your@email.com
      storage: /acme.json
      httpChallenge:
        entryPoint: web
```

---

## Database Setup

### SQLCipher Installation (Manual Deployment)

```bash
# Ubuntu/Debian
sudo apt install sqlcipher libsqlcipher-dev

# macOS
brew install sqlcipher

# Verify
sqlcipher --version
```

### Database Initialization

**Automatic (First Run):**
Application automatically creates database on first run.

**Manual (Using Alembic):**
```bash
# Create initial database
poetry run alembic upgrade head

# Verify
poetry run alembic current
```

### Database Migrations

```bash
# Check current version
poetry run alembic current

# Upgrade to latest
poetry run alembic upgrade head

# Downgrade one version
poetry run alembic downgrade -1

# Show migration history
poetry run alembic history
```

---

## Performance Tuning

### Application Tuning

**Workers:**
```bash
# CPU-bound: 2 x num_cores + 1
# I/O-bound: 2-4 per core
WORKERS=4  # For 2-core system
```

**Database:**
```bash
# Increase KDF iterations for better security (slower)
DATABASE_URL=sqlite+pysqlcipher:///:memory:@/data/vibe-quality-searcharr.db?cipher=aes-256-cfb&kdf_iter=500000
```

**Rate Limiting:**
```bash
# Adjust based on your traffic
API_RATE_LIMIT=200/minute  # Higher for busy servers
```

### System Tuning

**File Descriptors:**
```bash
# /etc/security/limits.conf
appuser soft nofile 65536
appuser hard nofile 65536
```

**Kernel Parameters:**
```bash
# /etc/sysctl.conf
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
```

---

## Monitoring and Logging

### Health Checks

**Endpoint:**
```bash
curl http://localhost:7337/api/health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "database": "connected",
  "uptime": 3600
}
```

**Docker Health Check:**
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:7337/api/health"]
  interval: 30s
  timeout: 3s
  retries: 3
  start_period: 10s
```

### Logging Configuration

**Structured Logging:**
```bash
LOG_LEVEL=INFO
STRUCTURED_LOGGING=true
LOG_FORMAT=json
```

**Log Aggregation (ELK Stack):**
```yaml
# filebeat.yml
filebeat.inputs:
  - type: container
    paths:
      - '/var/lib/docker/containers/*/*.log'
    processors:
      - add_docker_metadata:
          host: "unix:///var/run/docker.sock"

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
```

**Log Rotation (Manual):**
```bash
# /etc/logrotate.d/vibe-quality-searcharr
/var/log/vibe-quality-searcharr/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 appuser appuser
    sharedscripts
    postrotate
        systemctl reload vibe-quality-searcharr > /dev/null 2>&1 || true
    endscript
}
```

### Monitoring Tools

**Prometheus Metrics (Future):**
```yaml
# Coming in future release
metrics:
  enabled: true
  endpoint: /metrics
  port: 9090
```

**Uptime Monitoring:**
```bash
# UptimeRobot, Healthchecks.io, etc.
curl https://hc-ping.com/your-uuid -fsS --retry 3 > /dev/null
```

---

## Upgrade Procedures

### Docker Upgrade

```bash
# Pull latest image
docker-compose pull

# Backup database
cp data/vibe-quality-searcharr.db backups/backup-$(date +%Y%m%d).db

# Upgrade
docker-compose up -d

# Check logs
docker-compose logs -f

# Verify health
curl http://localhost:7337/api/health
```

### Manual Upgrade

```bash
# Backup database
cp data/vibe-quality-searcharr.db backups/backup-$(date +%Y%m%d).db

# Pull latest code
git pull origin main

# Update dependencies
poetry install --no-dev

# Run migrations
poetry run alembic upgrade head

# Restart service
sudo systemctl restart vibe-quality-searcharr

# Verify
curl http://localhost:7337/api/health
```

---

## Troubleshooting Deployment

See TROUBLESHOOTING.md for detailed troubleshooting guide.

**Quick Checks:**
```bash
# Check if service is running
docker-compose ps  # Docker
sudo systemctl status vibe-quality-searcharr  # Systemd

# Check logs
docker-compose logs --tail=50  # Docker
sudo journalctl -u vibe-quality-searcharr -n 50  # Systemd

# Check health
curl http://localhost:7337/api/health

# Check database
ls -lh data/vibe-quality-searcharr.db

# Check permissions
ls -l secrets/
ls -l data/
```

---

**Version:** 0.1.0
**Last Updated:** 2026-02-24
