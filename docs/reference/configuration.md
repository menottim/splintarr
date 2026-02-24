# Configuration Reference

Complete reference for all configuration options in Vibe-Quality-Searcharr.

## Environment Variables

Configuration is managed through environment variables, either directly or via `.env` file.

### Application Settings

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_NAME` | string | `Vibe-Quality-Searcharr` | Application name displayed in UI and logs |
| `ENVIRONMENT` | enum | `production` | Environment mode: `development`, `staging`, `production` |
| `DEBUG` | boolean | `false` | Enable debug mode (never use in production) |
| `LOG_LEVEL` | enum | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

### Security Configuration

#### Secret Keys

**Method 1: Direct variables** (simpler, less secure)

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `SECRET_KEY` | string | Yes | JWT signing key (min 64 characters) |
| `PEPPER` | string | Yes | Password hashing pepper (min 32 characters) |
| `DATABASE_KEY` | string | Yes | Database encryption key (min 32 characters) |

**Method 2: Docker secrets** (recommended for production)

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `SECRET_KEY_FILE` | path | Yes | Path to secret key file (e.g., `/run/secrets/secret_key`) |
| `PEPPER_FILE` | path | Yes | Path to pepper file (e.g., `/run/secrets/pepper`) |
| `DATABASE_KEY_FILE` | path | Yes | Path to database key file (e.g., `/run/secrets/db_key`) |

**Note:** Use either direct variables OR `_FILE` variants, not both. Docker secrets take precedence.

### Database Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DATABASE_URL` | string | See below | SQLite database URL with SQLCipher |

**Default DATABASE_URL:**
```
sqlite+pysqlcipher:///:memory:@/data/vibe-quality-searcharr.db?cipher=aes-256-cfb&kdf_iter=256000
```

**Format:**
```
sqlite+pysqlcipher:///:memory:@<path>?cipher=<cipher>&kdf_iter=<iterations>
```

### Server Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `HOST` | string | `0.0.0.0` | Server bind address (`0.0.0.0` for all interfaces, `127.0.0.1` for localhost) |
| `PORT` | integer | `7337` | Server port |
| `RELOAD` | boolean | `false` | Auto-reload on code changes (development only) |
| `WORKERS` | integer | `4` | Number of worker processes (recommended: `(2 × CPU cores) + 1`) |

### Session & Token Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SESSION_EXPIRE_HOURS` | integer | `24` | Session expiration in hours |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | integer | `15` | Access token lifetime (recommended: 15-60) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | integer | `30` | Refresh token lifetime (recommended: 7-30) |
| `MAX_REFRESH_TOKENS` | integer | `5` | Maximum refresh tokens per user |
| `ACCOUNT_LOCKOUT_MINUTES` | integer | `15` | Account lockout duration after failed logins |
| `MAX_LOGIN_ATTEMPTS` | integer | `5` | Failed login attempts before lockout |

### Rate Limiting

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `API_RATE_LIMIT` | string | `100/minute` | API rate limit (format: `<number>/<period>`) |
| `AUTH_RATE_LIMIT` | string | `10/minute` | Authentication endpoint rate limit |
| `RATE_LIMIT_STORAGE` | enum | `memory` | Storage backend: `memory`, `redis` |
| `REDIS_URL` | string | - | Redis URL (if using redis storage) |

**Rate limit periods:** `second`, `minute`, `hour`, `day`

**Examples:**
- `100/minute` - 100 requests per minute
- `1000/hour` - 1000 requests per hour
- `10000/day` - 10,000 requests per day

### Network Security

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ALLOW_LOCAL_INSTANCES` | boolean | `false` | Allow connections to local Sonarr/Radarr instances |
| `ALLOWED_ORIGINS` | string | - | CORS allowed origins (comma-separated) |
| `ALLOWED_HOSTS` | string | - | Trusted hosts (comma-separated) |
| `HTTPS_REDIRECT` | boolean | `false` | Enable HTTPS redirect |
| `HSTS_MAX_AGE` | integer | `31536000` | Strict Transport Security max age (seconds) |
| `CSP_POLICY` | string | See below | Content Security Policy header |

**Default CSP_POLICY:**
```
default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'
```

### Search Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MAX_ITEMS_PER_BATCH` | integer | `50` | Maximum items per search batch |
| `SEARCH_COOLDOWN_HOURS` | integer | `24` | Search cooldown period (prevents duplicate searches) |
| `DEFAULT_SEARCH_STRATEGY` | enum | `missing` | Default strategy: `missing`, `cutoff_unmet`, `recent`, `custom` |
| `MAX_CONCURRENT_SEARCHES` | integer | `3` | Maximum concurrent searches per instance |

### Scheduler Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SCHEDULER_TIMEZONE` | string | `UTC` | Scheduler timezone (IANA format, e.g., `America/New_York`) |
| `MISFIRE_GRACE_TIME` | integer | `300` | Grace time for missed jobs (seconds) |
| `COALESCE_JOBS` | boolean | `true` | Run missed jobs only once if multiple were missed |

### Logging Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `LOG_FORMAT` | enum | `json` | Log format: `json` (production), `text` (development) |
| `LOG_OUTPUT` | enum | `console` | Log output: `console`, `file` |
| `LOG_FILE` | path | `/data/logs/vibe-quality-searcharr.log` | Log file path (if `LOG_OUTPUT=file`) |
| `LOG_MAX_SIZE` | integer | `10` | Maximum log file size (MB) |
| `LOG_BACKUP_COUNT` | integer | `5` | Number of log files to keep |
| `LOG_SANITIZE` | boolean | `true` | Sanitize sensitive data in logs |

### HTTP Client Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `HTTP_TIMEOUT` | integer | `30` | HTTP request timeout (seconds) |
| `HTTP_MAX_RETRIES` | integer | `3` | Maximum retries for failed requests |
| `HTTP_POOL_SIZE` | integer | `10` | Connection pool size |
| `HTTP_USER_AGENT` | string | `Vibe-Quality-Searcharr/1.0.0` | User agent for outgoing requests |

### Database Performance

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SQLITE_WAL_MODE` | boolean | `true` | Enable SQLite WAL mode (better concurrent access) |
| `SQLITE_CACHE_SIZE` | integer | `20000` | SQLite cache size (KB) |
| `SQLITE_BUSY_TIMEOUT` | integer | `5000` | Lock wait timeout (milliseconds) |

### Feature Flags

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENABLE_2FA` | boolean | `true` | Enable two-factor authentication (TOTP) |
| `ENABLE_DRIFT_DETECTION` | boolean | `true` | Enable configuration drift detection |
| `ENABLE_SEARCH_HISTORY` | boolean | `true` | Enable search history tracking |
| `ENABLE_METRICS` | boolean | `false` | Enable metrics collection |
| `METRICS_ENDPOINT` | string | `/metrics` | Metrics endpoint path (if enabled) |

### Development Settings

**⚠️ Never use in production!**

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENABLE_DOCS` | boolean | `false` | Enable API documentation at `/docs` |
| `ENABLE_TEST_ENDPOINTS` | boolean | `false` | Enable test-only endpoints |
| `DISABLE_CSRF` | boolean | `false` | Disable CSRF protection (dangerous!) |
| `DISABLE_RATE_LIMIT` | boolean | `false` | Disable rate limiting (dangerous!) |
| `DISABLE_AUTH` | boolean | `false` | Disable authentication (dangerous!) |

### Monitoring & Observability

Optional integrations for production monitoring:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SENTRY_DSN` | string | - | Sentry DSN for error tracking |
| `SENTRY_ENVIRONMENT` | string | `production` | Sentry environment name |
| `SENTRY_TRACES_SAMPLE_RATE` | float | `0.1` | Sentry traces sample rate (0.0-1.0) |
| `PROMETHEUS_ENABLED` | boolean | `false` | Enable Prometheus metrics |
| `PROMETHEUS_PORT` | integer | `9090` | Prometheus metrics port |

### Backup Configuration

Used by backup scripts:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `BACKUP_DIR` | path | `/var/backups/vibe-quality-searcharr` | Automatic backup location |
| `BACKUP_RETENTION_DAYS` | integer | `7` | Number of days to keep backups |
| `BACKUP_COMPRESSION` | integer | `6` | Compression level (1-9) |

### Docker-Specific

Set in `docker-compose.yml`:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PUID` | integer | `1000` | Container user ID |
| `PGID` | integer | `1000` | Container group ID |
| `TZ` | string | `UTC` | Container timezone |

## Configuration Files

### .env File

Primary configuration file (not committed to version control):

```bash
# Copy template
cp .env.example .env

# Edit with your settings
nano .env
```

### Docker Secrets

For production deployments:

```bash
# Generate secrets
./scripts/generate-secrets.sh

# Secrets stored in ./secrets/
secrets/
├── secret_key
├── pepper
└── db_key
```

**docker-compose.yml:**
```yaml
secrets:
  secret_key:
    file: ./secrets/secret_key
  pepper:
    file: ./secrets/pepper
  db_key:
    file: ./secrets/db_key

services:
  app:
    secrets:
      - secret_key
      - pepper
      - db_key
    environment:
      - SECRET_KEY_FILE=/run/secrets/secret_key
      - PEPPER_FILE=/run/secrets/pepper
      - DATABASE_KEY_FILE=/run/secrets/db_key
```

## Recommended Configurations

### Development

```bash
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG
LOG_FORMAT=text
ALLOW_LOCAL_INSTANCES=true
ENABLE_DOCS=true
RELOAD=true
```

### Production

```bash
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
LOG_FORMAT=json
ALLOW_LOCAL_INSTANCES=false
ENABLE_DOCS=false
HTTPS_REDIRECT=true
LOG_SANITIZE=true
ENABLE_2FA=true
```

### High-Traffic Production

```bash
WORKERS=8
API_RATE_LIMIT=200/minute
SQLITE_CACHE_SIZE=50000
HTTP_POOL_SIZE=20
MAX_CONCURRENT_SEARCHES=5
RATE_LIMIT_STORAGE=redis
REDIS_URL=redis://redis:6379/0
```

## Validation

Configuration is validated on startup. Common errors:

- **Missing required variables:** `SECRET_KEY`, `PEPPER`, `DATABASE_KEY`
- **Invalid types:** Non-boolean for boolean fields, non-integer for integer fields
- **Invalid enums:** Unrecognized values for `ENVIRONMENT`, `LOG_LEVEL`, etc.
- **Conflicting settings:** Both direct secrets and `_FILE` variants set

Check application logs for validation errors.

## Security Best Practices

1. **Never commit `.env` to version control**
2. **Use Docker secrets in production**
3. **Generate strong random secrets** (min 32 characters)
4. **Disable debug mode in production** (`DEBUG=false`)
5. **Enable HTTPS in production** (`HTTPS_REDIRECT=true`)
6. **Restrict CORS origins** (never use `*` in production)
7. **Enable 2FA** (`ENABLE_2FA=true`)
8. **Sanitize logs** (`LOG_SANITIZE=true`)
9. **Use strong rate limits** on authentication endpoints
10. **Regular secret rotation** (especially if compromised)

## See Also

- [Deploy with Docker](../how-to-guides/deploy-with-docker.md) - Docker deployment guide
- [Security](../explanation/security.md) - Security architecture and best practices
- [Troubleshooting](../how-to-guides/troubleshoot.md) - Common configuration issues
