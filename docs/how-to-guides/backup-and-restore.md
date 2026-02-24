# Backup and Restore Guide

**Vibe-Quality-Searcharr v1.0.0**

This guide provides comprehensive procedures for backing up and restoring your Vibe-Quality-Searcharr installation.

---

## Table of Contents

- [What to Backup](#what-to-backup)
- [Backup Methods](#backup-methods)
- [Automated Backups](#automated-backups)
- [Manual Backups](#manual-backups)
- [Restore Procedures](#restore-procedures)
- [Disaster Recovery](#disaster-recovery)
- [Migration Between Hosts](#migration-between-hosts)
- [Backup Testing](#backup-testing)
- [Retention Policies](#retention-policies)
- [Troubleshooting](#troubleshooting)

---

## What to Backup

### Critical Data (MUST Backup)

1. **Database** - `data/vibe-quality-searcharr.db`
   - User accounts and passwords
   - Sonarr/Radarr instance configurations
   - Search queues and schedules
   - Search history

2. **Secrets** - `secrets/` directory
   - `db_key.txt` - Database encryption key
   - `secret_key.txt` - JWT signing key
   - `pepper.txt` - Password hashing pepper

3. **Configuration** - `.env` file (if used)
   - Environment-specific settings

### Optional Data

4. **Logs** - `data/logs/` (optional)
   - Useful for debugging
   - Can be excluded to save space

5. **Temporary Files** - Can be regenerated
   - SQLite WAL files (`.db-wal`, `.db-shm`)
   - Cache files

---

## Backup Methods

### 1. Automated Script (Recommended)

```bash
./scripts/backup.sh
```

**Features:**
- Creates timestamped archive
- Includes metadata (version, date, hostname)
- Calculates SHA256 checksum
- Automatic cleanup (keeps 7 days)
- Secure permissions

**Output:**
```
backups/vibe-quality-searcharr-backup-20240224-143022.tar.gz
backups/vibe-quality-searcharr-backup-20240224-143022.tar.gz.sha256
```

### 2. Docker Volume Backup

```bash
docker run --rm \
  -v vibe-quality-searcharr_data:/data:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/data-backup-$(date +%Y%m%d).tar.gz -C /data .
```

### 3. Manual Backup

```bash
# Stop application first
docker-compose down

# Create backup
tar -czf backup-$(date +%Y%m%d-%H%M%S).tar.gz \
  data/ \
  secrets/ \
  .env \
  docker/docker-compose.yml

# Restart application
docker-compose up -d
```

### 4. Database-Only Backup

```bash
# SQLite backup (hot backup)
sqlite3 data/vibe-quality-searcharr.db ".backup data/backup-$(date +%Y%m%d).db"

# Or using Docker
docker exec vibe-quality-searcharr \
  sqlite3 /data/vibe-quality-searcharr.db \
  ".backup /data/backup-$(date +%Y%m%d).db"
```

---

## Automated Backups

### Cron Job (Linux)

Create a cron job for daily backups:

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /path/to/vibe-quality-searcharr/scripts/backup.sh /var/backups/vibe-quality-searcharr >> /var/log/vqs-backup.log 2>&1
```

### Systemd Timer (Linux)

Create `/etc/systemd/system/vqs-backup.timer`:

```ini
[Unit]
Description=Vibe-Quality-Searcharr Daily Backup
Requires=vqs-backup.service

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
```

Create `/etc/systemd/system/vqs-backup.service`:

```ini
[Unit]
Description=Vibe-Quality-Searcharr Backup Service

[Service]
Type=oneshot
User=root
ExecStart=/path/to/vibe-quality-searcharr/scripts/backup.sh /var/backups/vibe-quality-searcharr
StandardOutput=journal
StandardError=journal
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable vqs-backup.timer
sudo systemctl start vqs-backup.timer

# Check status
sudo systemctl status vqs-backup.timer
sudo systemctl list-timers | grep vqs
```

### Docker-Based Backup Container

Create a backup container that runs periodically:

```yaml
services:
  backup:
    image: alpine
    volumes:
      - ../data:/source/data:ro
      - ../secrets:/source/secrets:ro
      - /var/backups/vqs:/backup
    environment:
      - BACKUP_SCHEDULE=0 2 * * *
    command: |
      sh -c '
      while true; do
        echo "Starting backup at $(date)"
        tar czf /backup/vqs-backup-$(date +%Y%m%d-%H%M%S).tar.gz -C /source .
        echo "Backup completed"
        sleep 86400
      done
      '
```

### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Trigger: Daily at 2:00 AM
4. Action: Start a program
5. Program: `C:\path\to\backup.bat`

Create `backup.bat`:
```batch
@echo off
cd C:\path\to\vibe-quality-searcharr
docker-compose down
tar -czf backup-%date:~-4,4%%date:~-10,2%%date:~-7,2%.tar.gz data secrets .env
docker-compose up -d
```

---

## Manual Backups

### Before Upgrades

```bash
# Create pre-upgrade backup
./scripts/backup.sh

# Or manual
BACKUP_NAME="pre-upgrade-$(cat VERSION)-$(date +%Y%m%d)"
tar -czf backups/${BACKUP_NAME}.tar.gz data/ secrets/ .env
```

### Before Configuration Changes

```bash
# Quick backup
cp data/vibe-quality-searcharr.db data/vibe-quality-searcharr.db.backup
cp .env .env.backup
```

### Export for Migration

```bash
# Full export including Docker config
tar -czf vqs-export-$(date +%Y%m%d).tar.gz \
  data/ \
  secrets/ \
  .env \
  docker/ \
  scripts/ \
  docs/
```

---

## Restore Procedures

### Automated Restore

```bash
./scripts/restore.sh backups/vibe-quality-searcharr-backup-20240224-143022.tar.gz
```

**Process:**
1. Verifies backup integrity (checksum)
2. Confirms restore operation
3. Stops application
4. Creates safety backup of current state
5. Extracts backup
6. Restores data, secrets, and config
7. Starts application
8. Verifies health

### Manual Restore

```bash
# Stop application
docker-compose down

# Backup current state (safety)
mv data data.old
mv secrets secrets.old

# Extract backup
tar -xzf backups/vibe-quality-searcharr-backup-20240224-143022.tar.gz
mv vibe-quality-searcharr-backup-20240224-143022/* .
rmdir vibe-quality-searcharr-backup-20240224-143022

# Set permissions
chmod 700 data secrets
chmod 600 secrets/*.txt
chmod 600 data/*.db

# Start application
docker-compose up -d

# Verify
curl http://localhost:7337/health
```

### Database-Only Restore

```bash
# Stop application
docker-compose down

# Backup current database
mv data/vibe-quality-searcharr.db data/vibe-quality-searcharr.db.old

# Restore from backup
cp backups/backup-20240224.db data/vibe-quality-searcharr.db
chmod 600 data/vibe-quality-searcharr.db

# Start application
docker-compose up -d
```

### Partial Restore

**Restore only secrets:**
```bash
docker-compose down
tar -xzf backup.tar.gz */secrets --strip-components=2
chmod 700 secrets && chmod 600 secrets/*.txt
docker-compose up -d
```

**Restore only database:**
```bash
docker-compose down
tar -xzf backup.tar.gz */data/vibe-quality-searcharr.db --strip-components=2
chmod 600 data/vibe-quality-searcharr.db
docker-compose up -d
```

---

## Disaster Recovery

### Complete System Loss

**Prerequisites:**
- Recent backup available
- Backup stored on different system/location
- Fresh Docker installation

**Recovery Steps:**

1. **Install Docker and Docker Compose**
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   ```

2. **Get Application Code**
   ```bash
   git clone https://github.com/yourusername/vibe-quality-searcharr.git
   cd vibe-quality-searcharr
   ```

3. **Restore from Backup**
   ```bash
   ./scripts/restore.sh /path/to/backup.tar.gz
   ```

4. **Verify and Test**
   ```bash
   docker-compose ps
   curl http://localhost:7337/health
   ```

### Corrupted Database

**Symptoms:**
- Application fails to start
- Database errors in logs
- "database disk image is malformed"

**Recovery:**

1. **Stop application**
   ```bash
   docker-compose down
   ```

2. **Attempt repair**
   ```bash
   # Backup corrupted database
   cp data/vibe-quality-searcharr.db data/vibe-quality-searcharr.db.corrupted

   # Attempt recovery
   sqlite3 data/vibe-quality-searcharr.db ".recover" | sqlite3 data/vibe-quality-searcharr.db.recovered

   # If successful, replace
   mv data/vibe-quality-searcharr.db.recovered data/vibe-quality-searcharr.db
   ```

3. **If repair fails, restore from backup**
   ```bash
   ./scripts/restore.sh backups/latest-backup.tar.gz
   ```

### Lost Secrets

**⚠️ CRITICAL: Without secrets, data cannot be decrypted!**

If secrets are lost and no backup exists:
1. Database is **permanently** inaccessible (encrypted)
2. User passwords cannot be verified
3. API keys cannot be decrypted
4. **Complete reinstall required**

**Prevention:**
- Store secrets in password manager (1Password, Bitwarden, etc.)
- Print secrets and store in safe
- Store backup off-site
- Use `scripts/backup.sh` regularly

---

## Migration Between Hosts

### Same Architecture (e.g., Linux to Linux)

1. **On old host:**
   ```bash
   ./scripts/backup.sh
   ```

2. **Transfer backup to new host:**
   ```bash
   scp backups/vibe-quality-searcharr-backup-*.tar.gz newhost:/tmp/
   ```

3. **On new host:**
   ```bash
   git clone https://github.com/yourusername/vibe-quality-searcharr.git
   cd vibe-quality-searcharr
   ./scripts/restore.sh /tmp/vibe-quality-searcharr-backup-*.tar.gz
   ```

### Different Architecture (e.g., x86 to ARM)

Same process as above, but rebuild Docker image on new host:

```bash
docker-compose build
docker-compose up -d
```

### Docker to Bare Metal

1. **Export data from Docker:**
   ```bash
   docker cp vibe-quality-searcharr:/data ./data
   docker cp vibe-quality-searcharr:/app/secrets ./secrets
   ```

2. **On bare metal:**
   ```bash
   poetry install
   cp -r data /path/to/installation/
   cp -r secrets /path/to/installation/
   cp .env /path/to/installation/
   poetry run alembic upgrade head
   poetry run uvicorn src.vibe_quality_searcharr.main:app --host 0.0.0.0 --port 7337
   ```

### Bare Metal to Docker

1. **Stop bare metal service:**
   ```bash
   sudo systemctl stop vibe-quality-searcharr
   ```

2. **Backup data:**
   ```bash
   tar -czf vqs-data.tar.gz /path/to/data /path/to/secrets /path/to/.env
   ```

3. **Set up Docker:**
   ```bash
   git clone https://github.com/yourusername/vibe-quality-searcharr.git
   cd vibe-quality-searcharr
   tar -xzf ../vqs-data.tar.gz
   docker-compose up -d
   ```

---

## Backup Testing

### Verify Backup Integrity

```bash
# Verify checksum
sha256sum -c backups/vibe-quality-searcharr-backup-*.tar.gz.sha256

# Test extraction
tar -tzf backups/vibe-quality-searcharr-backup-*.tar.gz | head -20

# Verify database
docker run --rm -v $(pwd)/backups:/backup alpine sh -c '
  tar -xzf /backup/vibe-quality-searcharr-backup-*.tar.gz -C /tmp
  apk add sqlite
  sqlite3 /tmp/*/data/*.db "PRAGMA integrity_check;"
'
```

### Test Restore Process

**Create test environment:**

```bash
# Create test directory
mkdir -p test-restore
cd test-restore

# Clone application
git clone https://github.com/yourusername/vibe-quality-searcharr.git
cd vibe-quality-searcharr

# Restore backup
./scripts/restore.sh /path/to/backup.tar.gz

# Test with different port
sed -i 's/7337/7338/g' docker/docker-compose.yml
docker-compose up -d

# Verify
curl http://localhost:7338/health

# Cleanup
docker-compose down
cd ../../
rm -rf test-restore
```

### Automated Backup Testing

Create test script `/scripts/test-backup.sh`:

```bash
#!/bin/bash
# Test backup integrity

BACKUP_FILE="${1}"
TEMP_DIR=$(mktemp -d)

echo "Testing backup: ${BACKUP_FILE}"

# Verify checksum
if [ -f "${BACKUP_FILE}.sha256" ]; then
    sha256sum -c "${BACKUP_FILE}.sha256" || exit 1
    echo "✓ Checksum valid"
fi

# Extract to temp
tar -xzf "${BACKUP_FILE}" -C "${TEMP_DIR}"
echo "✓ Extraction successful"

# Find database
DB_FILE=$(find "${TEMP_DIR}" -name "*.db" -type f | head -1)

if [ -n "${DB_FILE}" ]; then
    # Check database integrity
    sqlite3 "${DB_FILE}" "PRAGMA integrity_check;" | grep -q "ok"
    if [ $? -eq 0 ]; then
        echo "✓ Database integrity OK"
    else
        echo "✗ Database integrity check failed"
        exit 1
    fi
fi

# Cleanup
rm -rf "${TEMP_DIR}"

echo "✓ Backup test passed"
```

---

## Retention Policies

### Recommended Retention

- **Hourly**: Keep for 24 hours (24 backups)
- **Daily**: Keep for 7 days (7 backups)
- **Weekly**: Keep for 4 weeks (4 backups)
- **Monthly**: Keep for 12 months (12 backups)

### Implement with Script

```bash
#!/bin/bash
# Backup rotation script

BACKUP_DIR="/var/backups/vibe-quality-searcharr"

# Remove backups older than 7 days
find "${BACKUP_DIR}" -name "*.tar.gz" -type f -mtime +7 -delete

# Keep only last 10 backups
ls -t "${BACKUP_DIR}"/*.tar.gz | tail -n +11 | xargs rm -f
```

### Disk Space Management

```bash
# Check backup space usage
du -sh backups/

# Compress old backups with higher compression
find backups/ -name "*.tar.gz" -mtime +30 -exec gzip -9 {} \;

# Archive to cold storage (AWS S3, etc.)
aws s3 sync backups/ s3://my-bucket/vqs-backups/ --storage-class GLACIER
```

---

## Troubleshooting

### Backup Fails

**Permission denied:**
```bash
sudo chown -R $(whoami) backups/
chmod 755 scripts/backup.sh
```

**Disk space:**
```bash
df -h .
# Free up space or change backup location
./scripts/backup.sh /path/to/larger/disk
```

**Database locked:**
```bash
# Stop application first
docker-compose down
./scripts/backup.sh
docker-compose up -d
```

### Restore Fails

**Checksum mismatch:**
```bash
# Backup may be corrupted, try older backup
./scripts/restore.sh backups/older-backup.tar.gz
```

**Permission errors after restore:**
```bash
sudo chown -R 1000:1000 data/
sudo chmod 700 data/
sudo chmod 600 data/*.db
```

**Application won't start after restore:**
```bash
# Check logs
docker-compose logs

# Verify database
sqlite3 data/vibe-quality-searcharr.db "PRAGMA integrity_check;"

# Try restoring from older backup
```

---

## Best Practices

### ✅ DO

- ✅ Backup before every upgrade
- ✅ Test restore process regularly
- ✅ Store backups on different disk/system
- ✅ Keep multiple backup generations
- ✅ Verify backup integrity
- ✅ Document backup procedures
- ✅ Automate backups with cron/systemd
- ✅ Monitor backup success/failure
- ✅ Encrypt backups if stored off-site

### ❌ DON'T

- ❌ Store only one backup copy
- ❌ Keep backups on same disk as data
- ❌ Skip testing restore process
- ❌ Delete old backups immediately
- ❌ Forget to backup secrets
- ❌ Store backups without encryption (if sensitive)

---

## Additional Resources

- [SQLite Backup Documentation](https://www.sqlite.org/backup.html)
- [Docker Volume Backup Guide](https://docs.docker.com/storage/volumes/#backup-restore-or-migrate-data-volumes)
- [Disaster Recovery Planning](https://www.ready.gov/business/implementation/IT)

---

**Need Help?**

- GitHub Issues: https://github.com/yourusername/vibe-quality-searcharr/issues
- Documentation: https://github.com/yourusername/vibe-quality-searcharr/docs/
