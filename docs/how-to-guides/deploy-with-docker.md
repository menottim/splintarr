# Docker Deployment Guide

**Vibe-Quality-Searcharr v0.1.0-alpha**

**⚠️ ALPHA:** This is a pre-release version that has not been hand-verified for deployment.

This guide provides comprehensive instructions for deploying Vibe-Quality-Searcharr using Docker and Docker Compose.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Building from Source](#building-from-source)
- [Environment Configuration](#environment-configuration)
- [Volume Management](#volume-management)
- [Network Configuration](#network-configuration)
- [Secrets Management](#secrets-management)
- [Health Checks](#health-checks)
- [Resource Limits](#resource-limits)
- [Logging](#logging)
- [Upgrading Containers](#upgrading-containers)
- [Backup and Restore](#backup-and-restore)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

---

## Prerequisites

### System Requirements

- **OS**: Linux, macOS, or Windows with WSL2
- **Docker**: 20.10.0 or later
- **Docker Compose**: 1.29.0 or later (or Docker Compose V2)
- **CPU**: 2+ cores recommended
- **RAM**: 512 MB minimum, 1 GB recommended
- **Disk**: 1 GB free space (database grows over time)

### Installation

**Docker:**
```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker
```

**Docker Compose:**
```bash
# Docker Compose V2 (recommended)
sudo apt-get install docker-compose-plugin

# Or standalone (older)
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

Verify installation:
```bash
docker --version
docker-compose --version
```

---

## Quick Start

### 1. Clone or Download

```bash
git clone https://github.com/yourusername/vibe-quality-searcharr.git
cd vibe-quality-searcharr
```

### 2. Generate Secrets

**Linux/macOS:**
```bash
./scripts/generate-secrets.sh
```

**Windows (PowerShell):**
```powershell
.\scripts\generate-secrets.ps1
```

This creates:
- `secrets/db_key.txt` - Database encryption key (256-bit)
- `secrets/secret_key.txt` - JWT signing key (512-bit)
- `secrets/pepper.txt` - Password hashing pepper (256-bit)

The script includes:
- ✅ Prerequisite checks (Python 3 / PowerShell 5.1+)
- ✅ Cryptographically secure random generation
- ✅ Automatic validation of generated secrets
- ✅ File permission enforcement (600 on Linux/macOS, current user only on Windows)
- ✅ Error handling and clear success/failure messages

### 3. Start the Container

```bash
docker-compose up -d
```

### 4. Access the Application

Open http://localhost:7337 in your browser and complete the setup wizard.

### 5. Post-Deployment Security Hardening

**⚠️ CRITICAL: Complete these steps before production use!**

#### A. Update Dependencies (Fix Known CVEs)

```bash
# Stop the container
docker-compose down

# Update Python dependencies to fix Starlette CVEs
# Edit docker/Dockerfile and update fastapi version:
# Change: fastapi>=0.115.0
# To: fastapi>=1.0.0

# Rebuild the image
docker-compose build --no-cache

# Restart
docker-compose up -d
```

**What this fixes:**
- CVE-2025-62727: Starlette DoS via Range header
- CVE-2025-54121: Starlette DoS via multipart

#### B. Configure Production Settings

Create or update your `.env` file:

```bash
# Production mode (REQUIRED)
ENVIRONMENT=production

# Security settings (REQUIRED)
SECURE_COOKIES=true
ALLOW_LOCAL_INSTANCES=false

# Single worker for rate limiting (REQUIRED unless using Redis)
WORKERS=1

# Strong secret keys (32+ characters each - REQUIRED)
# Generate with: openssl rand -base64 32
SECRET_KEY=your-strong-secret-key-here
PEPPER=your-strong-pepper-here
DATABASE_KEY=your-strong-database-key-here

# OR use Docker secrets (recommended):
SECRET_KEY_FILE=/run/secrets/secret_key
PEPPER_FILE=/run/secrets/pepper
DATABASE_KEY_FILE=/run/secrets/db_key
```

**Restart after configuration:**
```bash
docker-compose down
docker-compose up -d
```

#### C. Enable HTTPS/TLS (REQUIRED for production)

**Option 1: Nginx Reverse Proxy (Recommended)**

```nginx
# /etc/nginx/sites-available/vibe-quality-searcharr
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL certificates (use Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        proxy_pass http://127.0.0.1:7337;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

**Option 2: Traefik (Docker-native)**

```yaml
# Add to docker-compose.yml
services:
  traefik:
    image: traefik:v2.10
    command:
      - "--providers.docker=true"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.email=your@email.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/acme.json"
      - "--certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./acme.json:/acme.json

  vibe-quality-searcharr:
    # ... existing config ...
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.vqs.rule=Host(`your-domain.com`)"
      - "traefik.http.routers.vqs.entrypoints=websecure"
      - "traefik.http.routers.vqs.tls.certresolver=letsencrypt"
```

#### D. Verify Security Configuration

```bash
# Check that production mode is enabled
docker-compose exec vibe-quality-searcharr env | grep ENVIRONMENT
# Should output: ENVIRONMENT=production

# Check that secrets are loaded
docker-compose exec vibe-quality-searcharr env | grep -E "(SECRET_KEY|PEPPER|DATABASE_KEY)"
# Should show file paths or values (NOT empty)

# Check worker count
docker-compose exec vibe-quality-searcharr env | grep WORKERS
# Should output: WORKERS=1 (unless Redis configured)

# Test HTTPS (after reverse proxy setup)
curl -I https://your-domain.com
# Should see: Strict-Transport-Security header
```

#### E. Enable Monitoring and Logging

```bash
# View real-time logs
docker-compose logs -f vibe-quality-searcharr

# Check for security events
docker-compose logs vibe-quality-searcharr | grep -E "(failed_login|locked|unauthorized)"

# Set up log rotation (recommended)
# Edit docker-compose.yml:
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
```

### 6. View Logs

```bash
docker-compose logs -f
```

### 6. Stop the Container

```bash
docker-compose down
```

---

## Building from Source

### Standard Build

```bash
# Build the image
docker build -t vibe-quality-searcharr:latest -f docker/Dockerfile .

# Check image size
docker images vibe-quality-searcharr:latest
```

### Build with Version Tags

```bash
export VERSION=1.0.0
export BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
export VCS_REF=$(git rev-parse --short HEAD)

docker build \
  --build-arg VERSION=${VERSION} \
  --build-arg BUILD_DATE=${BUILD_DATE} \
  --build-arg VCS_REF=${VCS_REF} \
  -t vibe-quality-searcharr:${VERSION} \
  -f docker/Dockerfile .
```

### Multi-Architecture Build

```bash
# Create buildx builder
docker buildx create --name multiarch --use

# Build for multiple architectures
docker buildx build \
  --platform linux/amd64,linux/arm64,linux/arm/v7 \
  --tag vibe-quality-searcharr:latest \
  --file docker/Dockerfile \
  --push .
```

### Inspect Image

```bash
# View image details
docker inspect vibe-quality-searcharr:latest

# View image layers
docker history vibe-quality-searcharr:latest

# View image labels
docker inspect vibe-quality-searcharr:latest | jq '.[0].Config.Labels'
```

---

## Environment Configuration

### Configuration Methods

1. **Docker Compose (Recommended)**: Edit `docker/docker-compose.yml`
2. **Environment File**: Create `.env` file
3. **Command Line**: Pass with `-e` flag

### Key Environment Variables

```yaml
environment:
  # Application
  - APP_NAME=Vibe-Quality-Searcharr
  - ENVIRONMENT=production
  - LOG_LEVEL=INFO

  # Secrets (use Docker secrets)
  - DATABASE_KEY_FILE=/run/secrets/db_key
  - SECRET_KEY_FILE=/run/secrets/secret_key
  - PEPPER_FILE=/run/secrets/pepper

  # Security
  - SESSION_EXPIRE_HOURS=24
  - ACCESS_TOKEN_EXPIRE_MINUTES=15
  - REFRESH_TOKEN_EXPIRE_DAYS=30
  - API_RATE_LIMIT=100/minute

  # Network
  - ALLOWED_ORIGINS=https://yourdomain.com
  - ALLOWED_HOSTS=yourdomain.com
  - ALLOW_LOCAL_INSTANCES=false
```

See [.env.example](../.env.example) for complete reference.

### Production Configuration

Use `docker/docker-compose.production.yml`:

```bash
docker-compose -f docker/docker-compose.production.yml up -d
```

### Development Configuration

Use `docker/docker-compose.development.yml`:

```bash
docker-compose -f docker/docker-compose.development.yml up -d
```

---

## Volume Management

### Data Persistence

Vibe-Quality-Searcharr requires persistent volumes for:

1. **Database** (`/data`) - SQLite database and application data
2. **Logs** (`/data/logs`) - Application logs (optional)

### Volume Types

**Bind Mount (Development):**
```yaml
volumes:
  - ./data:/data:rw
```

**Named Volume (Production):**
```yaml
volumes:
  vqs-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /var/lib/vibe-quality-searcharr/data
```

### Volume Permissions

The container runs as UID 1000, GID 1000. Set permissions:

```bash
# Create data directory
sudo mkdir -p /var/lib/vibe-quality-searcharr/data

# Set ownership
sudo chown -R 1000:1000 /var/lib/vibe-quality-searcharr/data

# Set permissions
sudo chmod 700 /var/lib/vibe-quality-searcharr/data
```

### Backup Volumes

```bash
# Backup data volume
docker run --rm \
  -v vibe-quality-searcharr_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/data-backup-$(date +%Y%m%d).tar.gz -C /data .

# Or use the backup script
./scripts/backup.sh
```

---

## Network Configuration

### Port Binding

**Localhost Only (Recommended):**
```yaml
ports:
  - "127.0.0.1:7337:7337"
```

**All Interfaces (Behind Reverse Proxy):**
```yaml
ports:
  - "7337:7337"
```

### Custom Network

```yaml
networks:
  vqs-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/24
```

### Reverse Proxy Integration

See [Reverse Proxy Examples](#reverse-proxy-examples) below.

---

## Secrets Management

### Docker Secrets (Recommended)

**docker-compose.yml:**
```yaml
secrets:
  db_key:
    file: ./secrets/db_key.txt
  secret_key:
    file: ./secrets/secret_key.txt
  pepper:
    file: ./secrets/pepper.txt

services:
  app:
    secrets:
      - db_key
      - secret_key
      - pepper
    environment:
      - DATABASE_KEY_FILE=/run/secrets/db_key
      - SECRET_KEY_FILE=/run/secrets/secret_key
      - PEPPER_FILE=/run/secrets/pepper
```

Secrets are mounted as read-only files at `/run/secrets/`.

### Environment Variables (Development)

```yaml
environment:
  - SECRET_KEY=your-secret-key-here
  - PEPPER=your-pepper-here
  - DATABASE_KEY=your-db-key-here
```

**⚠️ Never use environment variables for production secrets!**

### External Secrets (Advanced)

Use external secret managers:

**Docker Swarm:**
```bash
echo "secret-value" | docker secret create db_key -
```

**Kubernetes:**
```bash
kubectl create secret generic vqs-secrets \
  --from-file=db_key=./secrets/db_key.txt \
  --from-file=secret_key=./secrets/secret_key.txt \
  --from-file=pepper=./secrets/pepper.txt
```

---

## Health Checks

### Container Health Check

Built into Dockerfile:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx, sys; ..."
```

### Check Health Status

```bash
# View health status
docker ps

# View health check logs
docker inspect vibe-quality-searcharr | jq '.[0].State.Health'

# Wait for healthy
docker-compose ps
```

### Manual Health Check

```bash
# Using curl
curl -f http://localhost:7337/health

# Using script
./scripts/health-check.sh

# Check from inside container
docker exec vibe-quality-searcharr curl -f http://localhost:7337/health
```

---

## Resource Limits

### CPU and Memory Limits

```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 1G
    reservations:
      cpus: '0.5'
      memory: 256M
```

### Adjust for Your Needs

| Workload | CPU | Memory |
|----------|-----|--------|
| Light (<5 instances) | 0.5-1 | 256-512 MB |
| Medium (5-15 instances) | 1-2 | 512 MB-1 GB |
| Heavy (15+ instances) | 2-4 | 1-2 GB |

### Monitor Resource Usage

```bash
# Real-time stats
docker stats vibe-quality-searcharr

# Check limits
docker inspect vibe-quality-searcharr | jq '.[0].HostConfig.Memory'
```

---

## Logging

### Log Configuration

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
    compress: "true"
```

### View Logs

```bash
# Follow logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Since timestamp
docker-compose logs --since 2024-02-24T10:00:00

# Specific service
docker-compose logs vibe-quality-searcharr
```

### External Logging

**Syslog:**
```yaml
logging:
  driver: syslog
  options:
    syslog-address: "tcp://192.168.0.42:514"
```

**Fluentd:**
```yaml
logging:
  driver: fluentd
  options:
    fluentd-address: "localhost:24224"
    tag: "vibe-quality-searcharr"
```

---

## Upgrading Containers

### Automated Upgrade

```bash
./scripts/upgrade.sh 1.0.1
```

This script:
1. Creates automatic backup
2. Pulls new image
3. Stops old container
4. Starts new container
5. Verifies health
6. Rolls back on failure

### Manual Upgrade

```bash
# Pull latest image
docker-compose pull

# Stop and remove old container
docker-compose down

# Start new container
docker-compose up -d

# Verify
docker-compose ps
docker-compose logs -f
```

### Database Migrations

Migrations run automatically on container start. To run manually:

```bash
docker-compose run --rm --entrypoint "alembic upgrade head" vibe-quality-searcharr
```

---

## Backup and Restore

### Backup

```bash
# Automated backup
./scripts/backup.sh

# Manual backup
docker-compose down
tar -czf backup-$(date +%Y%m%d).tar.gz data/ secrets/ .env
docker-compose up -d
```

### Restore

```bash
# Automated restore
./scripts/restore.sh backup-20240224.tar.gz

# Manual restore
docker-compose down
tar -xzf backup-20240224.tar.gz
docker-compose up -d
```

See [BACKUP_RESTORE.md](BACKUP_RESTORE.md) for detailed procedures.

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs

# Common issues:
# 1. Port already in use
sudo lsof -i :7337

# 2. Permission denied on volumes
ls -la data/
sudo chown -R 1000:1000 data/

# 3. Missing secrets
ls -la secrets/
./scripts/generate-secrets.sh
```

### Health Check Failing

```bash
# Check health endpoint
curl http://localhost:7337/health

# Check from inside container
docker exec vibe-quality-searcharr curl http://localhost:7337/health

# View detailed logs
docker-compose logs -f | grep -i error
```

### Performance Issues

```bash
# Check resource usage
docker stats vibe-quality-searcharr

# Increase limits in docker-compose.yml
# Check database size
docker exec vibe-quality-searcharr du -sh /data/*.db

# Optimize database
docker exec vibe-quality-searcharr sqlite3 /data/*.db "VACUUM;"
```

### Network Issues

```bash
# Test connectivity to Sonarr/Radarr from container
docker exec vibe-quality-searcharr curl -v http://your-sonarr:8989

# Check DNS resolution
docker exec vibe-quality-searcharr nslookup your-sonarr

# Check network configuration
docker network inspect vibe-quality-searcharr_default
```

---

## Advanced Configuration

### Reverse Proxy Examples

#### Nginx

```nginx
server {
    listen 80;
    server_name vqs.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name vqs.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/vqs.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/vqs.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:7337;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Traefik

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.vqs.rule=Host(`vqs.yourdomain.com`)"
  - "traefik.http.routers.vqs.entrypoints=websecure"
  - "traefik.http.routers.vqs.tls.certresolver=letsencrypt"
  - "traefik.http.services.vqs.loadbalancer.server.port=7337"
```

### SSL/TLS Setup

Use Let's Encrypt with reverse proxy or:

```bash
# Generate self-signed certificate (testing only)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ./certs/privkey.pem \
  -out ./certs/fullchain.pem
```

### Running Behind VPN

```yaml
services:
  vpn:
    image: dperson/openvpn-client
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun
    volumes:
      - ./vpn:/vpn:ro

  vibe-quality-searcharr:
    network_mode: "service:vpn"
    depends_on:
      - vpn
```

### Database on External Volume

```yaml
volumes:
  - type: bind
    source: /mnt/nas/vibe-quality-searcharr
    target: /data
```

---

## Security Best Practices

### ✅ DO

- ✅ Use Docker secrets for production
- ✅ Run container with read-only filesystem
- ✅ Bind to localhost, use reverse proxy
- ✅ Set resource limits
- ✅ Keep Docker and image updated
- ✅ Regular backups
- ✅ Use HTTPS with reverse proxy
- ✅ Monitor logs for suspicious activity

### ❌ DON'T

- ❌ Expose port 7337 directly to internet
- ❌ Store secrets in environment variables
- ❌ Run with `--privileged` flag
- ❌ Disable health checks
- ❌ Skip backups
- ❌ Use `latest` tag in production
- ❌ Commit secrets to version control

---

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Reference](https://docs.docker.com/compose/compose-file/)
- [Best Practices for Secrets](https://docs.docker.com/engine/swarm/secrets/)
- [Container Security Guide](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)

---

**Questions or Issues?**

- GitHub Issues: https://github.com/yourusername/vibe-quality-searcharr/issues
- Documentation: https://github.com/yourusername/vibe-quality-searcharr/docs/
- Troubleshooting: See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
