# Security Guide
## Vibe-Quality-Searcharr

## Overview

This guide covers security features, best practices, and deployment security for Vibe-Quality-Searcharr.

## Security Features

### 1. Authentication & Authorization

**Password Security:**
- Argon2id hashing (OWASP recommended)
- Global pepper (stored separately)
- Per-user salt (automatic)
- Parameters: 3 iterations, 128 MiB memory, 8 threads

**Session Management:**
- JWT with HS256 (HMAC-SHA256)
- Access token: 15-minute expiration
- Refresh token: 30-day expiration
- Secure logout (session invalidation)

**2FA Support (Partial):**
- TOTP (Google Authenticator compatible)
- Backup codes
- QR code generation

### 2. Data Protection

**Encryption at Rest:**
- Database: SQLCipher (AES-256-CFB, 256k iterations)
- API Keys: Fernet (AES-128-CBC + HMAC)
- Secrets: Environment variables or Docker secrets

**Encryption in Transit:**
- HTTPS/TLS (recommended for production)
- HSTS header (production mode)
- Secure cookie flags

### 3. API Security

**Rate Limiting:**
- Global: 100 requests/minute (configurable)
- Login: Stricter limits to prevent brute force
- Headers: X-RateLimit-* for clients

**CORS:**
- Configurable allowed origins
- Credentials support controlled
- Preflight request handling

**Security Headers:**
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'
Referrer-Policy: strict-origin-when-cross-origin
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000 (production)
```

### 4. Input Validation

**Protection Against:**
- SQL Injection (SQLAlchemy ORM)
- XSS (Content-Type headers, CSP)
- Command Injection (no shell execution)
- SSRF (URL validation, configurable local access)

**Validation:**
- Pydantic schemas for all inputs
- Type safety via Python type hints
- URL scheme validation (http/https only)

### 5. Logging & Monitoring

**Security Events Logged:**
- Failed login attempts
- Successful authentication
- Authorization failures
- Configuration changes
- API errors

**Structured Logging:**
- JSON format (SIEM-compatible)
- Configurable log levels
- PII filtering

---

## Best Practices for Deployment

### 1. Secrets Management

**Environment Variables (Development):**
```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
export PEPPER="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export DATABASE_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

**Docker Secrets (Production - Recommended):**
```bash
# Generate secrets
python -c "import secrets; print(secrets.token_urlsafe(64))" | docker secret create secret_key -
python -c "import secrets; print(secrets.token_urlsafe(32))" | docker secret create pepper -
python -c "import secrets; print(secrets.token_urlsafe(32))" | docker secret create db_key -

# Reference in docker-compose.yml
secrets:
  - secret_key
  - pepper
  - db_key
```

**Files (Alternative):**
```bash
# Create secrets directory
mkdir -p secrets && chmod 700 secrets

# Generate secrets to files
python -c "import secrets; print(secrets.token_urlsafe(64))" > secrets/secret_key
python -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/pepper
python -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/db_key

# Set permissions
chmod 600 secrets/*

# Reference in .env
SECRET_KEY_FILE=/path/to/secrets/secret_key
PEPPER_FILE=/path/to/secrets/pepper
DATABASE_KEY_FILE=/path/to/secrets/db_key
```

### 2. Database Security

**Encryption:**
- Always enable database encryption (SQLCipher)
- Use strong encryption key (32+ bytes)
- Store DATABASE_KEY separately from database file

**Backups:**
```bash
# Backup database (encrypted)
cp data/vibe-quality-searcharr.db backups/backup-$(date +%Y%m%d).db

# Backup DATABASE_KEY separately (critical for restore)
# Store in password manager or encrypted vault
```

**Permissions:**
```bash
# Set appropriate file permissions
chmod 600 data/vibe-quality-searcharr.db
chown appuser:appuser data/vibe-quality-searcharr.db
```

### 3. Network Security

**Reverse Proxy (Recommended):**

**nginx Example:**
```nginx
server {
    listen 443 ssl http2;
    server_name searcharr.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://localhost:7337;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Traefik Example:**
```yaml
http:
  routers:
    vibe-quality-searcharr:
      rule: "Host(`searcharr.yourdomain.com`)"
      service: vibe-quality-searcharr
      tls:
        certResolver: letsencrypt
  services:
    vibe-quality-searcharr:
      loadBalancer:
        servers:
          - url: "http://localhost:7337"
```

**Firewall:**
```bash
# Only expose via reverse proxy, block direct access
sudo ufw deny 7337
sudo ufw allow 443/tcp  # HTTPS only
```

### 4. Production Configuration

**Environment Settings:**
```bash
# Production mode
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO

# Security settings
SECURE_COOKIES=true  # Requires HTTPS
SESSION_EXPIRE_HOURS=24
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30

# Disable local instance access
ALLOW_LOCAL_INSTANCES=false

# Restrict CORS
ALLOWED_ORIGINS=https://searcharr.yourdomain.com

# Restrict hosts
ALLOWED_HOSTS=searcharr.yourdomain.com
```

**Checklist:**
- [ ] HTTPS/TLS enabled
- [ ] Strong SECRET_KEY (64+ chars)
- [ ] Unique PEPPER (32+ chars)
- [ ] Strong DATABASE_KEY (32+ chars)
- [ ] SECURE_COOKIES=true
- [ ] ALLOW_LOCAL_INSTANCES=false
- [ ] Firewall configured
- [ ] Reverse proxy with TLS
- [ ] Regular backups enabled
- [ ] Monitoring configured

---

## Security Hardening

### Container Security

**Dockerfile Best Practices:**
```dockerfile
# Use specific version, not latest
FROM python:3.13-slim-bookworm

# Run as non-root user
RUN useradd -m -u 1000 appuser
USER appuser

# Read-only root filesystem
VOLUME /data
VOLUME /run/secrets

# Health check
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:7337/api/health || exit 1
```

**Docker Compose Security:**
```yaml
services:
  vibe-quality-searcharr:
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp
    volumes:
      - ./data:/data:rw
      - ./secrets:/run/secrets:ro  # Read-only secrets
```

### Application Security

**Rate Limiting:**
```bash
# Adjust rate limits for your use case
API_RATE_LIMIT=100/minute  # General API
LOGIN_RATE_LIMIT=5/minute  # Login attempts
```

**Session Security:**
```bash
# Shorter sessions for sensitive environments
SESSION_EXPIRE_HOURS=8
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

**Logging:**
```bash
# Enhanced logging for security monitoring
LOG_LEVEL=INFO  # Or DEBUG for troubleshooting
STRUCTURED_LOGGING=true
LOG_PII=false  # Never log sensitive data
```

---

## Backup and Recovery

### Backup Procedures

**What to Backup:**
1. Database file (`data/vibe-quality-searcharr.db`)
2. Encryption keys (SECRET_KEY, PEPPER, DATABASE_KEY)
3. Configuration files (.env, docker-compose.yml)

**Backup Script:**
```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backups/vibe-quality-searcharr"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Backup database
cp data/vibe-quality-searcharr.db "$BACKUP_DIR/db-$DATE.db"

# Backup configuration (without secrets)
cp .env.example "$BACKUP_DIR/config-$DATE.env"

# Encrypt backup (optional but recommended)
gpg --encrypt --recipient your@email.com "$BACKUP_DIR/db-$DATE.db"

# Keep last 30 days of backups
find "$BACKUP_DIR" -name "db-*.db" -mtime +30 -delete

echo "Backup completed: $BACKUP_DIR/db-$DATE.db"
```

**Automated Backups:**
```bash
# Add to crontab for daily backups
0 2 * * * /path/to/backup.sh >> /var/log/vibe-backup.log 2>&1
```

### Recovery Procedures

**Restore from Backup:**
```bash
# Stop application
docker-compose down

# Restore database
cp /backups/vibe-quality-searcharr/db-20260224_020000.db data/vibe-quality-searcharr.db

# Restore encryption keys (critical!)
export DATABASE_KEY="<your-original-database-key>"
export SECRET_KEY="<your-original-secret-key>"
export PEPPER="<your-original-pepper>"

# Start application
docker-compose up -d

# Verify
curl http://localhost:7337/api/health
```

**Important Notes:**
- DATABASE_KEY must match the key used to encrypt the database
- Changing DATABASE_KEY without re-encrypting will cause data loss
- Store keys securely (password manager, encrypted vault)

---

## Incident Response

### Security Incident Checklist

**1. Detection:**
- [ ] Monitor logs for suspicious activity
- [ ] Check failed login attempts
- [ ] Review authorization failures
- [ ] Analyze traffic patterns

**2. Containment:**
- [ ] Disable affected accounts
- [ ] Block suspicious IPs (firewall)
- [ ] Isolate compromised instances
- [ ] Enable additional logging

**3. Investigation:**
- [ ] Review audit logs
- [ ] Identify attack vector
- [ ] Assess data exposure
- [ ] Document findings

**4. Recovery:**
- [ ] Patch vulnerabilities
- [ ] Rotate compromised secrets
- [ ] Restore from clean backup
- [ ] Reset affected passwords

**5. Post-Incident:**
- [ ] Update security measures
- [ ] Document lessons learned
- [ ] Enhance monitoring
- [ ] Update incident response plan

### Log Analysis

**Check Failed Logins:**
```bash
# Using structured logs
docker-compose logs | jq '. | select(.event == "authentication_failed")'
```

**Check Authorization Failures:**
```bash
docker-compose logs | jq '. | select(.event == "authorization_failed")'
```

**Monitor Rate Limiting:**
```bash
docker-compose logs | grep "429 Too Many Requests"
```

---

## Security Update Procedures

### Regular Maintenance

**Monthly Tasks:**
- [ ] Update dependencies (check for security patches)
- [ ] Review logs for anomalies
- [ ] Verify backups working
- [ ] Test recovery procedures

**Quarterly Tasks:**
- [ ] Full security audit
- [ ] Penetration testing
- [ ] Review and rotate secrets
- [ ] Update documentation

**Yearly Tasks:**
- [ ] Major version upgrades
- [ ] Security architecture review
- [ ] Third-party security audit
- [ ] Disaster recovery drill

### Updating Dependencies

```bash
# Check for security updates
poetry update --only security

# Run security scans
poetry run safety check
poetry run bandit -r src/

# Run tests
poetry run pytest

# Update in production
docker-compose pull
docker-compose up -d
```

---

## Compliance Considerations

### GDPR Compliance

**User Data:**
- Minimal data collection (username, email, IP for audit)
- Encrypted storage
- User data export (coming soon)
- Right to deletion

**Implementation:**
```python
# User data export endpoint (future)
GET /api/auth/export-data

# User deletion endpoint (future)
DELETE /api/auth/account
```

### SOC 2 Considerations

**Access Controls:**
- Multi-factor authentication (partial)
- Role-based access control
- Audit logging

**Data Protection:**
- Encryption at rest and in transit
- Secure key management
- Regular backups

**Monitoring:**
- Structured logging
- Security event tracking
- Anomaly detection (external tools)

---

## Security Contacts

**Report Security Vulnerabilities:**
- Email: security@yourdomain.com
- PGP Key: [Key Fingerprint]
- GitHub Security Advisories: https://github.com/yourusername/vibe-quality-searcharr/security

**Response Time:**
- Critical: 24 hours
- High: 72 hours
- Medium: 1 week
- Low: 2 weeks

---

**Version:** 0.1.0
**Last Updated:** 2026-02-24
**Next Review:** 2026-05-24
