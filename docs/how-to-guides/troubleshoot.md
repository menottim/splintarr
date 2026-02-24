# Troubleshooting Guide
## Vibe-Quality-Searcharr

## Common Issues and Solutions

### Installation & Setup Issues

#### Issue: "PEPPER not configured" Error

**Symptoms:**
```
RuntimeError: PEPPER not configured. Set PEPPER or PEPPER_FILE environment variable.
```

**Solutions:**
1. Generate secrets:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/pepper
```

2. Set environment variable:
```bash
export PEPPER_FILE=/path/to/secrets/pepper
# Or
export PEPPER="your-pepper-value"
```

3. For Docker:
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
1. Check database file permissions:
```bash
ls -l data/vibe-quality-searcharr.db
chmod 600 data/vibe-quality-searcharr.db
```

2. Ensure data directory exists:
```bash
mkdir -p data
```

3. Verify DATABASE_KEY is correct:
```bash
# If key is wrong, database cannot be decrypted
# Must use original key or restore from backup
```

4. Check disk space:
```bash
df -h /path/to/data
```

#### Issue: Port Already in Use

**Symptoms:**
```
OSError: [Errno 48] Address already in use
```

**Solutions:**
1. Check what's using the port:
```bash
sudo lsof -i :7337
```

2. Change port in configuration:
```bash
PORT=7338  # Use different port
```

3. Stop conflicting service:
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
1. Verify user exists:
```bash
# Check database (requires DB tool)
sqlite3 data/vibe-quality-searcharr.db "SELECT username, is_active FROM users;"
```

2. Check SECRET_KEY hasn't changed:
```bash
# JWT tokens become invalid if SECRET_KEY changes
# Users must re-login after SECRET_KEY change
```

3. Clear browser cookies:
```javascript
// In browser console
document.cookie.split(";").forEach(c => document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/"));
```

4. Reset password (requires DB access):
```python
from vibe_quality_searcharr.core.security import hash_password
# Generate new hash
new_hash = hash_password("new-password")
# Update in database
```

#### Issue: Session Expires Too Quickly

**Symptoms:**
- Frequent "Unauthorized" errors
- Must log in repeatedly

**Solutions:**
1. Increase token expiration:
```bash
ACCESS_TOKEN_EXPIRE_MINUTES=60  # Default is 15
SESSION_EXPIRE_HOURS=48  # Default is 24
```

2. Use refresh token:
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
1. Ensure cookies enabled in browser
2. Check CORS configuration:
```bash
ALLOWED_ORIGINS=https://your-domain.com
```

3. Verify SECURE_COOKIES setting:
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
1. Verify URL format:
```bash
# Correct formats:
http://localhost:8989
https://sonarr.domain.com
http://192.168.1.100:8989

# Incorrect formats:
localhost:8989  # Missing protocol
http://localhost:8989/  # Trailing slash may cause issues
```

2. Test connectivity:
```bash
curl -I http://localhost:8989/api/system/status?apikey=YOUR_API_KEY
```

3. Check API key:
```bash
# Get from Sonarr/Radarr:
# Settings → General → Security → API Key
```

4. Verify network access:
```bash
# If in Docker, ensure network connectivity
docker-compose exec vibe-quality-searcharr ping sonarr
```

5. Check ALLOW_LOCAL_INSTANCES:
```bash
# Development: Allow localhost
ALLOW_LOCAL_INSTANCES=true

# Production: Block localhost (security)
ALLOW_LOCAL_INSTANCES=false
# Use actual domain/IP instead
```

6. Check firewall:
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
1. For self-signed certificates:
```python
# Not recommended for production
import urllib3
urllib3.disable_warnings()
```

2. Add certificate to trust store:
```bash
sudo cp your-cert.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

3. Use HTTP instead of HTTPS (if internal network):
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
du -h data/vibe-quality-searcharr.db
# If >100MB, consider cleanup
```

2. Monitor resources:
```bash
# Docker
docker stats vibe-quality-searcharr

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
sqlite3 data/vibe-quality-searcharr.db "VACUUM;"
sqlite3 data/vibe-quality-searcharr.db "ANALYZE;"
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
cp backups/backup-20260224.db data/vibe-quality-searcharr.db

# Ensure correct DATABASE_KEY
export DATABASE_KEY="original-key"

# Start application
docker-compose up -d
```

2. Check database integrity:
```bash
sqlite3 data/vibe-quality-searcharr.db "PRAGMA integrity_check;"
```

3. If no backup, try recovery:
```bash
# Dump readable data
sqlite3 data/vibe-quality-searcharr.db ".dump" > dump.sql

# Create new database
mv data/vibe-quality-searcharr.db data/vibe-quality-searcharr.db.old

# Import dump (may partially work)
sqlite3 data/vibe-quality-searcharr.db < dump.sql
```

#### Issue: Database Locked

**Symptoms:**
```
sqlite3.OperationalError: database is locked
```

**Solutions:**
1. Check for multiple processes:
```bash
ps aux | grep vibe-quality-searcharr
```

2. Close connections:
```bash
# Restart application
docker-compose restart
```

3. Check for stale locks:
```bash
# Remove -wal and -shm files if safe
rm data/vibe-quality-searcharr.db-wal
rm data/vibe-quality-searcharr.db-shm
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
docker-compose logs vibe-quality-searcharr
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

#### Issue: Volume Mount Issues

**Symptoms:**
- Data not persisting
- Permission denied errors
- Empty directories

**Solutions:**
1. Check volume mounts:
```bash
docker inspect vibe-quality-searcharr | jq '.[].Mounts'
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
  vibe-quality-searcharr:
    volumes:
      - vibe-data:/data
```

---

## Debug Mode

### Enable Debug Logging

**Environment:**
```bash
LOG_LEVEL=DEBUG
DEBUG=true  # Development only
```

**Check logs:**
```bash
# Docker
docker-compose logs -f --tail=100

# Systemd
sudo journalctl -u vibe-quality-searcharr -f -n 100

# File
tail -f /var/log/vibe-quality-searcharr/app.log
```

### Interactive Debugging

**Python REPL:**
```python
# Access application shell
poetry shell
python

# Import and test
from vibe_quality_searcharr.core.security import hash_password
print(hash_password("test"))
```

**Database Access:**
```bash
# SQLCipher
sqlcipher data/vibe-quality-searcharr.db
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
sudo journalctl -u vibe-quality-searcharr | grep ERROR

# File
grep ERROR /var/log/vibe-quality-searcharr/app.log
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

- **GitHub Issues:** https://github.com/yourusername/vibe-quality-searcharr/issues
- **Discussions:** https://github.com/yourusername/vibe-quality-searcharr/discussions
- **Documentation:** /docs/

---

**Version:** 0.1.0
**Last Updated:** 2026-02-24
