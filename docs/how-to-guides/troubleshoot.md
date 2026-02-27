# Troubleshooting Guide
## Splintarr

## Common Issues and Solutions

### Installation & Setup Issues

#### Issue: "PEPPER not configured" Error

**Symptoms:**
```
RuntimeError: PEPPER not configured. Set PEPPER or PEPPER_FILE environment variable.
```

**Solutions:**

Generate secrets:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/pepper
```

Set environment variable:
```bash
export PEPPER_FILE=/path/to/secrets/pepper
# Or
export PEPPER="your-pepper-value"
```

For Docker:
```yaml
environment:
  - PEPPER_FILE=/run/secrets/pepper
volumes:
  - ./secrets:/run/secrets:ro
```

#### Issue: Database Connection Failed

**Symptoms:**
```
sqlalchemy.exc.OperationalError: unable to open database file
```

**Solutions:**

Check database file permissions:
```bash
ls -l data/splintarr.db
chmod 600 data/splintarr.db
```

Ensure data directory exists:
```bash
mkdir -p data
```

Verify DATABASE_KEY is correct:
```bash
# If key is wrong, database cannot be decrypted
# Must use original key or restore from backup
```

Check disk space:
```bash
df -h /path/to/data
```

#### Issue: "file is encrypted or is not a database"

**Symptoms:**
```
sqlcipher3.dbapi2.DatabaseError: file is encrypted or is not a database
```

This error occurs during startup when trying to initialize the database.

**Cause:**

The database file exists but was encrypted with **different encryption keys** than what you're currently using. This commonly happens when:
- You regenerated secrets (db_key.txt) but kept the old database
- You're using a database backup from different keys
- You copied a database from another installation

**Solution:**

**Option 1: Delete old database (fresh start)**
```powershell
# Windows
docker-compose down
Remove-Item -Force .\data\splintarr.db*
docker-compose up -d
```

```bash
# Linux/macOS
docker-compose down
rm -f ./data/splintarr.db*
docker-compose up -d
```

**Option 2: Restore original keys**

If you need the existing database, you must use the **original encryption keys** it was created with:
- Restore the original `secrets/db_key.txt`
- Restart the application

**Option 3: Migrate to new keys (advanced)**

There's no automatic migration. You would need to:
1. Start application with old keys
2. Export all data via API
3. Stop application, delete database
4. Start with new keys
5. Import data via API

**Prevention:**

When regenerating encryption keys, always delete the old database or back it up with its keys together.

#### Issue: Port Already in Use

**Symptoms:**
```
OSError: [Errno 48] Address already in use
```

**Solutions:**

Check what's using the port:
```bash
sudo lsof -i :7337
```

Change port in configuration:
```bash
PORT=7338  # Use different port
```

Stop conflicting service:
```bash
docker stop $(docker ps -q -f "publish=7337")
```

---

### Authentication Issues

#### Issue: Cannot Log In

**Symptoms:**
- Login fails with correct credentials
- "Invalid username or password" error

**Solutions:**

Verify user exists:
```bash
# Check database (requires DB tool)
sqlite3 data/splintarr.db "SELECT username, is_active FROM users;"
```

Check SECRET_KEY hasn't changed:
```bash
# JWT tokens become invalid if SECRET_KEY changes
# Users must re-login after SECRET_KEY change
```

Clear browser cookies:
```javascript
// In browser console
document.cookie.split(";").forEach(c => document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/"));
```

Reset password (requires DB access):
```python
from splintarr.core.security import hash_password
# Generate new hash
new_hash = hash_password("new-password")
# Update in database
```

#### Issue: Session Expires Too Quickly

**Symptoms:**
- Frequent "Unauthorized" errors
- Must log in repeatedly

**Solutions:**

Increase token expiration:
```bash
ACCESS_TOKEN_EXPIRE_MINUTES=60  # Default is 15
SESSION_EXPIRE_HOURS=48  # Default is 24
```

Use refresh token:
```bash
# Implement token refresh in client
POST /api/auth/refresh
{
  "refresh_token": "your-refresh-token"
}
```

#### Issue: CSRF Token Errors

**Symptoms:**
```
403 Forbidden: CSRF token missing or invalid
```

**Solutions:**

- Ensure cookies enabled in browser
- Check CORS configuration:
  ```bash
  ALLOWED_ORIGINS=https://your-domain.com
  ```
- Verify SECURE_COOKIES setting:
  ```bash
  # Use false for HTTP, true for HTTPS
  SECURE_COOKIES=false  # Development
  SECURE_COOKIES=true   # Production with HTTPS
  ```

---

### Connection Issues

#### Issue: Cannot Connect to Sonarr/Radarr

**Symptoms:**
- "Connection failed" when testing instance
- Timeouts when executing searches

**Solutions:**

Verify URL format:
```bash
# Correct formats:
http://localhost:8989
https://sonarr.domain.com
http://192.168.1.100:8989

# Incorrect formats:
localhost:8989  # Missing protocol
http://localhost:8989/  # Trailing slash may cause issues
```

Test connectivity:
```bash
curl -I http://localhost:8989/api/system/status?apikey=YOUR_API_KEY
```

Check API key:
```bash
# Get from Sonarr/Radarr:
# Settings → General → Security → API Key
```

Verify network access:
```bash
# If in Docker, ensure network connectivity
docker-compose exec splintarr ping sonarr
```

Check ALLOW_LOCAL_INSTANCES:
```bash
# Development: Allow localhost
ALLOW_LOCAL_INSTANCES=true

# Production: Block localhost (security)
ALLOW_LOCAL_INSTANCES=false
# Use actual domain/IP instead
```

Check firewall:
```bash
# Ensure Sonarr/Radarr ports accessible
sudo ufw allow from <docker-subnet> to any port 8989
```

#### Issue: SSL Certificate Errors

**Symptoms:**
```
SSLError: certificate verify failed
```

**Solutions:**

For self-signed certificates:
```python
# Not recommended for production
import urllib3
urllib3.disable_warnings()
```

Add certificate to trust store:
```bash
sudo cp your-cert.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

Use HTTP instead of HTTPS (if internal network):
```bash
http://sonarr.local:8989  # Instead of https://
```

---

### Search Queue Issues

#### Issue: Queue Not Executing

**Symptoms:**
- Queue status stuck on "idle"
- No search history entries
- Schedule not triggering

**Solutions:**
1. Verify queue is active:
```bash
# Check is_active = true
GET /api/search-queues/{id}
```

2. Check schedule syntax (cron):
```bash
# Valid cron expressions:
"0 2 * * *"     # Daily at 2 AM
"*/30 * * * *"  # Every 30 minutes
"0 */6 * * *"   # Every 6 hours

# Test cron expression:
# https://crontab.guru/
```

3. Manual execution:
```bash
POST /api/search-queues/{id}/start
```

4. Check scheduler status:
```bash
# View application logs
docker-compose logs -f | grep scheduler
```

5. Verify instance is accessible:
```bash
# Test instance connection first
GET /api/instances/{id}/test
```

#### Issue: Search Finds No Results

**Symptoms:**
- Searches complete but find nothing
- "0 items found" in history

**Solutions:**
1. Check Sonarr/Radarr has missing content:
```bash
# Verify in Sonarr/Radarr UI:
# Queue → Wanted → Missing
```

2. Verify indexers configured:
```bash
# In Sonarr/Radarr:
# Settings → Indexers
# Ensure at least one indexer enabled
```

3. Check indexer health:
```bash
# In Sonarr/Radarr logs:
# Look for indexer errors
```

4. Verify strategy settings:
```bash
# Missing strategy: Requires unmonitored content
# Cutoff strategy: Requires quality profile with cutoff
# Recent strategy: Requires recently aired/added content
```

5. Check quality profiles:
```bash
# Sonarr/Radarr: Settings → Profiles
# Ensure cutoff is set appropriately
```

#### Issue: Too Many Rate Limit Errors

**Symptoms:**
```
429 Too Many Requests
```

**Solutions:**
1. Reduce max items per run:
```json
{
  "max_items_per_run": 10  // Reduce from higher value
}
```

2. Increase time between runs:
```bash
# Change from:
"*/15 * * * *"  # Every 15 minutes
# To:
"0 * * * *"     # Every hour
```

3. Check application rate limits:
```bash
API_RATE_LIMIT=200/minute  # Increase if too low
```

4. Check Sonarr/Radarr rate limits:
```bash
# Sonarr/Radarr: Settings → General → Rate Limiting
```

5. Stagger multiple queues:
```bash
# Queue 1: 0 2 * * *  (2 AM)
# Queue 2: 0 4 * * *  (4 AM)
# Queue 3: 0 6 * * *  (6 AM)
```

---

### Performance Issues

#### Issue: Slow Performance

**Symptoms:**
- API requests take long time
- Searches timeout
- High CPU/memory usage

**Solutions:**
1. Check database size:
```bash
du -h data/splintarr.db
# If >100MB, consider cleanup
```

2. Monitor resources:
```bash
# Docker
docker stats splintarr

# System
top -p $(pgrep -f uvicorn)
```

3. Reduce concurrent searches:
```bash
# Limit active queues
# Disable unnecessary queues
```

4. Increase resources (Docker):
```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 1G
```

5. Enable database optimization:
```bash
sqlite3 data/splintarr.db "VACUUM;"
sqlite3 data/splintarr.db "ANALYZE;"
```

6. Check network latency:
```bash
ping sonarr-host
```

#### Issue: High Memory Usage

**Symptoms:**
- OOM (Out of Memory) errors
- Container restarts
- System slowdown

**Solutions:**
1. Reduce Argon2 memory cost:
```bash
# In code or config:
ARGON2_MEMORY_COST=65536  # Reduce from 131072 (128MB)
```

2. Limit workers:
```bash
WORKERS=2  # Reduce from higher value
```

3. Enable swap (if needed):
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

4. Increase Docker memory limit:
```yaml
deploy:
  resources:
    limits:
      memory: 2G  # Increase from 1G
```

---

### Data Issues

#### Issue: Lost/Corrupted Database

**Symptoms:**
- "Database malformed" error
- Cannot access data
- Application won't start

**Solutions:**
1. Restore from backup:
```bash
# Stop application
docker-compose down

# Restore backup
cp backups/backup-20260224.db data/splintarr.db

# Ensure correct DATABASE_KEY
export DATABASE_KEY="original-key"

# Start application
docker-compose up -d
```

2. Check database integrity:
```bash
sqlite3 data/splintarr.db "PRAGMA integrity_check;"
```

3. If no backup, try recovery:
```bash
# Dump readable data
sqlite3 data/splintarr.db ".dump" > dump.sql

# Create new database
mv data/splintarr.db data/splintarr.db.old

# Import dump (may partially work)
sqlite3 data/splintarr.db < dump.sql
```

#### Issue: Database Locked

**Symptoms:**
```
sqlite3.OperationalError: database is locked
```

**Solutions:**
1. Check for multiple processes:
```bash
ps aux | grep splintarr
```

2. Close connections:
```bash
# Restart application
docker-compose restart
```

3. Check for stale locks:
```bash
# Remove -wal and -shm files if safe
rm data/splintarr.db-wal
rm data/splintarr.db-shm
```

---

### Docker Issues

#### Issue: Container Won't Start

**Symptoms:**
- Container exits immediately
- "Exited (1)" status

**Solutions:**
1. Check logs:
```bash
docker-compose logs splintarr
```

2. Check configuration:
```bash
docker-compose config
```

3. Verify volumes exist:
```bash
ls -la data/
ls -la secrets/
```

4. Check permissions:
```bash
# Ensure volumes are writable
chmod -R 755 data/
```

5. Validate secrets files:
```bash
# Ensure secret files contain data
cat secrets/secret_key
cat secrets/pepper
cat secrets/db_key
```

#### Issue: Docker Build Fails with "parent snapshot does not exist"

**Symptoms:**
```
failed to prepare extraction snapshot "extract-..." parent snapshot ... does not exist: not found
```

**Cause:**

Docker Desktop's build cache has become corrupted. This is a known Docker Desktop bug unrelated to the application.

**Solutions:**

Prune the build cache and retry:
```bash
# Linux/macOS
docker builder prune --all --force

# Windows (PowerShell)
docker builder prune --all --force
```

If that doesn't help, do a full cleanup:
```bash
docker system prune --all --force
```

Then re-run the build or setup script.

#### Issue: Volume Mount Issues

**Symptoms:**
- Data not persisting
- Permission denied errors
- Empty directories

**Solutions:**
1. Check volume mounts:
```bash
docker inspect splintarr | jq '.[].Mounts'
```

2. Fix permissions:
```bash
# Host
sudo chown -R 1000:1000 data/
sudo chmod -R 755 data/

# Container user ID should match
```

3. Use named volumes:
```yaml
volumes:
  vibe-data:
services:
  splintarr:
    volumes:
      - vibe-data:/data
```

---

## Logging System

### Understanding the Logging System

Splintarr includes a comprehensive logging system with multiple log files and automatic rotation:

**Log Files:**
- `logs/all.log` - All log messages (INFO level and above)
- `logs/error.log` - Error messages only (ERROR and CRITICAL)
- `logs/debug.log` - Debug messages (when DEBUG mode enabled)

**Log Rotation:**
- Maximum file size: 10 MB
- Backup count: 5 files
- Total disk usage per log type: ~50 MB

**Log Location:**
- Docker: `./logs/` directory (mapped volume)
- Manual install: `./logs/` in application directory

### Configure Logging Level

**Environment Variables:**
```bash
# Set log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO  # Default: reasonable verbosity

# Enable debug mode for troubleshooting (most verbose)
LOG_LEVEL=DEBUG

# Production: only errors and critical issues
LOG_LEVEL=ERROR
```

**Docker Compose:**
```yaml
environment:
  - LOG_LEVEL=DEBUG
```

**Restart to apply:**
```bash
docker-compose down
docker-compose up -d
```

### View Logs

**Docker:**
```bash
# Follow all logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Specific log file
docker exec splintarr cat /data/logs/all.log
docker exec splintarr cat /data/logs/error.log
docker exec splintarr tail -f /data/logs/debug.log
```

**Direct file access:**
```bash
# From host (if volume mapped)
tail -f ./logs/all.log
tail -f ./logs/error.log

# View errors only
tail -f ./logs/error.log

# View all with timestamps
tail -f ./logs/all.log | grep ERROR
```

**Systemd:**
```bash
sudo journalctl -u splintarr -f -n 100
```

### Debug Mode

**Enable Debug Logging:**
```bash
# Maximum verbosity - shows all operations
LOG_LEVEL=DEBUG
DEBUG=true  # Development only
```

**What DEBUG mode logs:**
- Database queries and connection details
- HTTP requests/responses (URLs, headers, status codes)
- Authentication attempts and session creation
- Search queue processing details
- Scheduler job execution
- Configuration loading and validation
- Internal function calls and data transformations

**Sensitive Data Protection:**
Even in DEBUG mode, sensitive data is automatically filtered:
- Passwords (replaced with `***REDACTED***`)
- API keys (partially masked)
- Secret keys (never logged)
- Database encryption keys (never logged)
- JWT tokens (partially masked)

### Troubleshooting with Logs

**Issue: Application won't start**
```bash
# Check startup errors
docker-compose logs --tail=50 | grep ERROR

# Look for:
# - Database connection issues
# - Missing secret files
# - Configuration validation errors
# - Port binding conflicts
```

**Issue: Searches not running**
```bash
# Enable debug logging
LOG_LEVEL=DEBUG

# Check scheduler logs
docker-compose logs -f | grep -i "scheduler\|search"

# Look for:
# - Job registration
# - Cron trigger execution
# - Search queue processing
# - API call failures
```

**Issue: Authentication problems**
```bash
# Check auth-related logs
docker-compose logs | grep -i "auth\|login\|token"

# Look for:
# - Failed login attempts
# - Token validation errors
# - Session creation issues
# - Rate limiting triggers
```

**Issue: Performance problems**
```bash
# Enable debug to see timing
LOG_LEVEL=DEBUG

# Monitor logs for:
# - Slow database queries
# - HTTP request timeouts
# - Large batch operations
# - Memory warnings
```

### Log Analysis

**Find all errors:**
```bash
# Docker logs
docker-compose logs | grep ERROR

# Log files
grep ERROR logs/all.log
cat logs/error.log  # Errors only
```

**Find specific issue:**
```bash
# Database issues
grep -i "database\|sqlite" logs/all.log

# API connection issues
grep -i "connection\|timeout\|refused" logs/all.log

# Authentication issues
grep -i "auth\|login\|password" logs/all.log
```

**Log rotation information:**
```bash
# Check log file sizes
ls -lh logs/

# View rotated logs
ls logs/*.log.*

# Logs are automatically rotated when they reach 10MB
# Up to 5 backup files are kept per log type
```

### Common Log Messages

**Normal operation:**
```
INFO - Application starting
INFO - Database connection established
INFO - Scheduler initialized
INFO - Search queue registered: <queue_name>
INFO - Search completed: 10 items processed
```

**Expected warnings:**
```
WARNING - No items found for search
WARNING - Rate limit approaching
WARNING - Configuration drift detected
```

**Issues to investigate:**
```
ERROR - Database connection failed
ERROR - Unable to connect to Sonarr/Radarr
ERROR - Search execution failed
CRITICAL - Unhandled exception
```

### Interactive Debugging

**Python REPL:**
```python
# Access application shell
poetry shell
python

# Import and test
from splintarr.core.security import hash_password
print(hash_password("test"))
```

**Database Access:**
```bash
# SQLCipher
sqlcipher data/splintarr.db
# Enter key when prompted
PRAGMA key = 'your-database-key';

# Check tables
.tables

# Query data
SELECT * FROM users;
SELECT * FROM instances;
SELECT * FROM search_queues;
```

---

## Log Analysis

### Find Errors

```bash
# Docker
docker-compose logs | grep ERROR

# Journalctl
sudo journalctl -u splintarr | grep ERROR

# File
grep ERROR /var/log/splintarr/app.log
```

### Find Failed Authentications

```bash
docker-compose logs | grep "authentication_failed"
```

### Find Rate Limit Events

```bash
docker-compose logs | grep "429"
```

### Structured Log Parsing

```bash
# If using JSON logging
docker-compose logs | jq '. | select(.level == "ERROR")'
```

---

## Getting Help

### Information to Provide

When requesting help, include:

1. **Version Information:**
```bash
curl http://localhost:7337/api/health
```

2. **Environment:**
- OS and version
- Docker/Compose version (if applicable)
- Python version (manual install)

3. **Configuration:**
```bash
# Redact secrets!
cat .env | grep -v KEY | grep -v PEPPER
```

4. **Logs:**
```bash
docker-compose logs --tail=100
```

5. **Error Message:**
- Full error text
- Stack trace (if available)

### Support Channels

- **GitHub Issues:** https://github.com/menottim/splintarr/issues
- **Discussions:** https://github.com/menottim/splintarr/discussions
- **Documentation:** /docs/

---

**Version:** 0.1.0
**Last Updated:** 2026-02-24
