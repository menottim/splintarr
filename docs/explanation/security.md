# Security Guide

## Overview

Splintarr is a homelab application designed to run on your local network. This guide documents the security measures implemented in the codebase and practical steps for keeping your deployment secure.

This is not an enterprise application. There is no SSO, no compliance framework, and no security team on call. The goal is defense-in-depth appropriate for a self-hosted tool that stores API keys for your Sonarr and Radarr instances.

---

## 1. Authentication

**Password Hashing (Argon2id + Pepper):**

Passwords are hashed using Argon2id (winner of the Password Hashing Competition) with a global pepper stored separately from the database. The pepper is mixed via HMAC-SHA256 in constant time to prevent timing attacks.

Parameters: 3 iterations, 128 MiB memory, 8 threads, 256-bit hash, 128-bit salt per user.

If the database file is stolen, the attacker still needs the pepper (stored in a separate secrets file) to attempt any offline cracking.

Additional password rules:
- 12-128 character length enforcement
- 100+ common password blocklist (per NIST SP 800-63B)
- Must contain uppercase, lowercase, digit, and special character
- Case-preserved storage (never normalized)

**JWT Sessions (HS256):**

- Access tokens: 15-minute expiry, signed with HS256 using a hardcoded algorithm whitelist (prevents algorithm confusion attacks)
- Refresh tokens: 30-day expiry, stored in the database for revocation
- Token rotation: old refresh tokens are revoked when new ones are issued
- Logout: access tokens are blacklisted in memory; refresh tokens are revoked in the database
- Reserved JWT claims (`sub`, `exp`, `iat`, `jti`, `type`) cannot be overridden

**Account Lockout (Exponential Backoff):**

After 5 consecutive failed login attempts, the account is temporarily locked with escalating durations:

| Failed Attempts | Lockout Duration |
|-----------------|------------------|
| 5-9             | 1 minute         |
| 10-14           | 5 minutes        |
| 15-19           | 15 minutes       |
| 20+             | 30 minutes (cap) |

Lockout resets on successful login. A dummy Argon2 verification runs on unknown usernames to equalize response timing and prevent username enumeration.

---

## 2. Data Protection

**Database Encryption (SQLCipher):**

The SQLite database is encrypted at rest using SQLCipher with AES-256-CFB and 256,000 KDF iterations. The encryption key (`DATABASE_KEY`) is stored in a separate secrets file, never in the database itself.

**Field-Level Encryption (Fernet):**

Sonarr and Radarr API keys are individually encrypted in the database using Fernet (AES-128-CBC + HMAC-SHA256). The Fernet key is derived from the application `SECRET_KEY` using HKDF with an application-specific salt. Even if the database encryption is somehow bypassed, API keys remain individually encrypted.

**Docker Secrets:**

In production Docker deployments, secrets are read from files mounted at `/run/secrets/` rather than passed as environment variables. Environment variables are visible in `docker inspect` output and process listings; file-based secrets are not.

---

## 3. API Security

**Rate Limiting:**

All endpoints are rate-limited using SlowAPI (backed by in-memory storage):

| Endpoint Category | Limit |
|-------------------|-------|
| Global default    | 100/minute |
| Login, register, password change | 3-10/minute |
| Data read (instances, history) | 30-60/minute |
| Data write/delete | 5-20/minute |

Rate limit headers (`X-RateLimit-*`) are included in responses.

**Content Security Policy (Nonce-Based):**

Each HTTP response includes a CSP header with a unique per-request nonce for inline scripts. This prevents XSS even if an attacker can inject HTML, because injected scripts will not have the correct nonce. The nonce is generated using `secrets.token_urlsafe(16)`.

CSP directives:
```
default-src 'self';
script-src 'self' 'nonce-<per-request>';
style-src 'self' 'unsafe-inline';
img-src 'self' data: https:;
frame-ancestors 'none';
base-uri 'self';
form-action 'self'
```

**SSRF Protection:**

When users add Sonarr/Radarr instance URLs, the application resolves the hostname to an IP address and checks it against a blocklist of private networks (RFC 1918), loopback, link-local, cloud metadata endpoints (169.254.x.x), and other reserved ranges. This prevents an attacker from using the application to probe your internal network.

In development mode, `ALLOW_LOCAL_INSTANCES=true` permits localhost URLs.

**Cookie Security:**

In production mode, cookies are set with `SameSite=Strict` and `Secure` flags. HSTS headers are sent when `SECURE_COOKIES=true`.

**Additional Headers:**
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Strict-Transport-Security: max-age=31536000; includeSubDomains (production only)
```

---

## 4. Input Validation

**Pydantic Schemas:**

All API inputs are validated through Pydantic models with strict type checking. URLs are validated for scheme (http/https only) and hostname. Usernames are restricted to alphanumeric characters and underscores.

**SQL Injection Prevention:**

All database queries use SQLAlchemy ORM with parameterized queries. No raw SQL strings are constructed from user input.

**XSS Prevention:**

Jinja2 templates auto-escape all output by default. Inline scripts use CSP nonces, so even if auto-escaping were bypassed, injected scripts would be blocked by the browser. No shell commands are executed from user input.

---

## 5. Logging

**Structured Logging (structlog):**

All log output uses structlog with contextual fields (user ID, IP address, endpoint, timestamps). In production, logs are rendered as JSON for machine parsing. In development, logs use a human-readable console format.

**Log Files and Rotation:**

| Log File   | Contents              | Rotation   | Backups |
|------------|-----------------------|------------|---------|
| all.log    | INFO+ (or DEBUG)      | 10 MB      | 5       |
| error.log  | ERROR and CRITICAL    | 10 MB      | 5       |
| debug.log  | Everything (debug mode only) | 10 MB | 5       |

Rotated files are named with datetime stamps (e.g., `all-2026-02-24_143052.log`). Total disk usage is capped at approximately 150 MB across all log types.

**Sensitive Data Filtering:**

A structlog processor automatically censors sensitive fields in all log output, including DEBUG level. Fields matching `password`, `secret`, `token`, `api_key`, `pepper`, `db_key`, and similar patterns are masked. API keys show only the first 4 characters. Database encryption keys are never logged.

**Security Events:**

The following events are logged with structured context:
- Failed and successful login attempts (with IP address)
- Account lockouts
- Token creation, revocation, and rotation
- SSRF-blocked URLs
- Rate limit violations
- Authorization failures

---

## 6. Deployment Security

**Docker Container Hardening:**

The production Docker Compose file (`docker/docker-compose.production.yml`) applies these restrictions:

```yaml
services:
  splintarr:
    user: "1000:1000"           # Non-root user
    read_only: true             # Read-only root filesystem
    cap_drop:
      - ALL                     # Drop all Linux capabilities
    security_opt:
      - no-new-privileges:true  # Prevent privilege escalation
    tmpfs:
      - /tmp                    # Writable temp directory
    volumes:
      - vqs-data:/data:rw       # Only /data is writable
```

The container binds to `127.0.0.1:7337` by default, so it is only accessible via localhost. Use a reverse proxy to expose it to your network.

In production mode, the Swagger/ReDoc API documentation endpoints are disabled. The health check endpoint returns only a status field, with no internal details like cipher version or connection pool state.

---

## 7. Secrets Management

Three secrets are required:

| Secret        | Purpose                        | Size     |
|---------------|--------------------------------|----------|
| `SECRET_KEY`  | JWT signing and Fernet key derivation | 64 bytes (512-bit) |
| `PEPPER`      | Password hashing pepper        | 32 bytes (256-bit) |
| `DATABASE_KEY`| SQLCipher database encryption  | 32 bytes (256-bit) |

**Generating Secrets:**

```bash
./scripts/generate-secrets.sh
```

This creates `secrets/db_key.txt`, `secrets/secret_key.txt`, and `secrets/pepper.txt` with restrictive file permissions (`chmod 600`). The script validates each secret for minimum length and randomness.

**Backup Your Keys:**

If you lose these secret files, you cannot decrypt your database. There is no recovery mechanism. Store copies in a password manager (Bitwarden, 1Password, KeePassXC) or on an encrypted USB drive.

The `generate-secrets.sh` script will warn you before overwriting existing secrets.

---

## 8. Network Security

Splintarr does not handle TLS itself. For HTTPS, place it behind a reverse proxy.

**Caddy Example (recommended for homelabs):**

```
splintarr.home.lan {
    reverse_proxy localhost:7337
    tls internal
}
```

Caddy automatically provisions and renews TLS certificates. With `tls internal`, it generates a self-signed CA for local use. If you have a domain, replace `tls internal` with your domain and Caddy will use Let's Encrypt automatically.

**Firewall (optional):**

If the Docker container is bound to `127.0.0.1:7337` (the default), it is already inaccessible from other machines. The reverse proxy handles external access. If you change the bind address to `0.0.0.0`, restrict access with a firewall:

```bash
sudo ufw deny 7337
sudo ufw allow 443/tcp
```

---

## 9. Password Reset

If you forget your password or lock yourself out, use the CLI tool from the host machine (or `docker exec` into the container):

```bash
python -m splintarr.cli reset-password
```

This prompts for a username and new password, validates the password against the same strength rules as registration, updates the hash, and unlocks the account if it was locked.

---

## 10. Backup and Recovery

Database backups and key management are covered in detail in the [Backup and Restore Guide](../how-to-guides/backup-and-restore.md).

The short version:
1. Back up `data/splintarr.db` (the encrypted database file)
2. Back up `secrets/` (the three key files)
3. The `DATABASE_KEY` must match the key used to encrypt the database -- using the wrong key means permanent data loss
4. Test your restore procedure at least once

---

## Security Audit History

| Date | Report | Findings | Status |
|------|--------|----------|--------|
| 2026-02-24 | [Initial Security Audit](../other/security-audit.md) | Automated SAST + dependency scanning | Complete |
| 2026-02-24 | [Penetration Test](../other/security-penetration-test-report.md) | 15 vulnerabilities (3 critical) | All fixed |
| 2026-02-24 | [Post-Fix Assessment](../other/security-assessment-post-fix.md) | Verification of all pen test fixes | Complete |
| 2026-02-25 | [API & Docker Audit](../other/security-audit-api-docker-2026-02-25.md) | 20 vulnerabilities (3 critical) | All fixed |
| 2026-02-25 | [Red Team Assessment](../other/red-team-adversarial-assessment-2026-02-25.md) | 15 vulnerabilities (3 critical) | All fixed |

---

**Version:** 0.1.0
**Last Updated:** 2026-02-25
