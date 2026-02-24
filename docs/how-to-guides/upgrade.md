# Upgrade Guide

**Vibe-Quality-Searcharr**

This guide provides instructions for upgrading Vibe-Quality-Searcharr to newer versions.

---

## Table of Contents

- [Before You Upgrade](#before-you-upgrade)
- [Upgrade Methods](#upgrade-methods)
- [Version-Specific Instructions](#version-specific-instructions)
- [Database Migrations](#database-migrations)
- [Configuration Changes](#configuration-changes)
- [Rollback Procedures](#rollback-procedures)
- [Troubleshooting](#troubleshooting)

---

## Before You Upgrade

### Pre-Upgrade Checklist

- [ ] **Read release notes** for target version
- [ ] **Backup your data** (automatic with upgrade script)
- [ ] **Check breaking changes** (see below)
- [ ] **Verify system requirements**
- [ ] **Plan maintenance window** (5-10 minutes typical)
- [ ] **Test in development first** (if possible)

### System Requirements

| Version | Docker | Python | Minimum RAM |
|---------|--------|--------|-------------|
| 1.0.0   | 20.10+ | 3.13+  | 512 MB      |

### Backup Before Upgrade

**Automatic (Recommended):**
```bash
./scripts/upgrade.sh 1.0.0
```
The upgrade script automatically creates a backup before upgrading.

**Manual:**
```bash
./scripts/backup.sh
```

---

## Upgrade Methods

### Method 1: Automated Upgrade Script (Recommended)

The upgrade script handles everything automatically with rollback on failure.

```bash
# Upgrade to specific version
./scripts/upgrade.sh 1.0.0

# Upgrade to latest
./scripts/upgrade.sh latest
```

**Process:**
1. Creates automatic backup
2. Builds/pulls new image
3. Runs database migrations
4. Stops old container
5. Starts new container
6. Verifies health
7. Rolls back on failure

### Method 2: Docker Compose

```bash
# Pull new image
docker-compose pull

# Stop current version
docker-compose down

# Start new version
docker-compose up -d

# Verify
docker-compose logs -f
curl http://localhost:7337/health
```

### Method 3: Manual Docker Commands

```bash
# Pull new image
docker pull vibe-quality-searcharr:1.0.0

# Stop and remove old container
docker stop vibe-quality-searcharr
docker rm vibe-quality-searcharr

# Start new container
docker run -d \
  --name vibe-quality-searcharr \
  -p 127.0.0.1:7337:7337 \
  -v $(pwd)/data:/data \
  --secret db_key \
  --secret secret_key \
  --secret pepper \
  vibe-quality-searcharr:1.0.0
```

---

## Version-Specific Instructions

### Upgrading to v1.0.0

**From:** v0.x.x (Development versions)

**Breaking Changes:** None

**New Features:**
- Complete web dashboard
- Setup wizard for first-run configuration
- Enhanced security features
- Production-ready Docker configuration
- Comprehensive documentation

**Steps:**
```bash
# Standard upgrade
./scripts/upgrade.sh 1.0.0
```

**Post-Upgrade:**
- No configuration changes required
- All existing data compatible
- Secrets remain unchanged

### Upgrading to v1.1.0 (Future)

**From:** v1.0.x

**Breaking Changes:** TBD

**New Features:** TBD

**Steps:** TBD

---

## Database Migrations

### Automatic Migrations

Database migrations run automatically when the container starts.

**Check migration status:**
```bash
docker-compose exec vibe-quality-searcharr alembic current
```

**View migration history:**
```bash
docker-compose exec vibe-quality-searcharr alembic history
```

### Manual Migrations

If automatic migration fails, run manually:

```bash
# Check current version
docker-compose exec vibe-quality-searcharr alembic current

# Upgrade to latest
docker-compose exec vibe-quality-searcharr alembic upgrade head

# Or specific version
docker-compose exec vibe-quality-searcharr alembic upgrade <revision>
```

### Migration Failures

**Symptom:** Container starts but database errors in logs

**Solution:**

1. **Stop container**
   ```bash
   docker-compose down
   ```

2. **Restore from backup**
   ```bash
   ./scripts/restore.sh backups/pre-upgrade-*.tar.gz
   ```

3. **Try upgrade again**
   ```bash
   ./scripts/upgrade.sh 1.0.0
   ```

4. **If still fails, open GitHub issue**

---

## Configuration Changes

### v1.0.0 Configuration Changes

No breaking configuration changes in v1.0.0.

**New optional settings:**
```bash
# Enhanced logging
LOG_FORMAT=json
LOG_SANITIZE=true

# Feature flags
ENABLE_2FA=true
ENABLE_DRIFT_DETECTION=true
ENABLE_METRICS=false

# Backup configuration
BACKUP_DIR=/var/backups/vibe-quality-searcharr
BACKUP_RETENTION_DAYS=7
```

**Add to `.env` or `docker-compose.yml` if desired.**

### Deprecated Settings

None in v1.0.0.

### Removed Settings

None in v1.0.0.

---

## Rollback Procedures

### Automatic Rollback

The upgrade script automatically rolls back on failure.

### Manual Rollback

If upgrade completed but you need to rollback:

```bash
# Restore from pre-upgrade backup
./scripts/restore.sh backups/pre-upgrade-<version>-<date>.tar.gz
```

### Downgrade to Previous Version

```bash
# Stop current version
docker-compose down

# Pull old version
docker pull vibe-quality-searcharr:0.9.0

# Update docker-compose.yml
# Change image: vibe-quality-searcharr:1.0.0
# To:     image: vibe-quality-searcharr:0.9.0

# Start old version
docker-compose up -d
```

**⚠️ Warning:** Database migrations may not be reversible. Always restore from backup when downgrading.

### Database Rollback

```bash
# Downgrade database to specific revision
docker-compose exec vibe-quality-searcharr alembic downgrade <revision>

# Or downgrade one step
docker-compose exec vibe-quality-searcharr alembic downgrade -1
```

---

## Troubleshooting

### Upgrade Fails - Container Won't Start

**Check logs:**
```bash
docker-compose logs
```

**Common issues:**

1. **Database migration failed**
   - Restore from backup
   - Check database integrity
   - Open GitHub issue with logs

2. **Permission errors**
   ```bash
   sudo chown -R 1000:1000 data/
   sudo chmod 700 data/
   ```

3. **Port conflict**
   ```bash
   sudo lsof -i :7337
   # Kill conflicting process or change port
   ```

### Health Check Failing After Upgrade

```bash
# Check health endpoint
curl http://localhost:7337/health

# Check from inside container
docker exec vibe-quality-searcharr curl http://localhost:7337/health

# View detailed logs
docker-compose logs -f | grep -i error
```

### Data Lost After Upgrade

**This should never happen if using upgrade script!**

If data appears lost:

1. **Check container is using correct volume:**
   ```bash
   docker inspect vibe-quality-searcharr | grep -A 10 Mounts
   ```

2. **Check database file exists:**
   ```bash
   ls -la data/*.db
   ```

3. **Restore from backup:**
   ```bash
   ./scripts/restore.sh backups/pre-upgrade-*.tar.gz
   ```

### Instances Not Working After Upgrade

1. **Test connection to Sonarr/Radarr:**
   ```bash
   docker exec vibe-quality-searcharr curl -v http://your-sonarr:8989/api/v3/system/status
   ```

2. **Check API keys still valid:**
   - Log into Vibe-Quality-Searcharr
   - Go to Instances
   - Test each instance

3. **Re-add instances if necessary:**
   - API keys should still be valid
   - May need to re-test connections

---

## Zero-Downtime Upgrade (Future)

For high-availability deployments (future versions):

1. **Blue-Green Deployment**
   - Run new version alongside old
   - Test new version
   - Switch traffic
   - Shut down old version

2. **Rolling Upgrade**
   - Update load balancer config
   - Upgrade instances one by one
   - Verify each before proceeding

**Not implemented in v1.0.0** (single-instance application).

---

## Post-Upgrade Verification

### Verification Checklist

- [ ] Container is running: `docker-compose ps`
- [ ] Health check passing: `curl http://localhost:7337/health`
- [ ] Can log in to web interface
- [ ] Instances visible and configured
- [ ] Search queues visible
- [ ] Search history accessible
- [ ] Logs show no errors: `docker-compose logs | grep -i error`

### Test Functionality

1. **Authentication:**
   - Log in with existing credentials
   - 2FA works (if enabled)

2. **Instances:**
   - View list of instances
   - Test connection to each
   - API keys decrypted correctly

3. **Search Queues:**
   - View existing queues
   - Create new queue
   - Start/pause queue
   - View search history

4. **Settings:**
   - Configuration preserved
   - All settings accessible

---

## Best Practices

### ✅ DO

- ✅ Always backup before upgrading
- ✅ Read release notes carefully
- ✅ Test in development first (if possible)
- ✅ Use automated upgrade script
- ✅ Verify functionality after upgrade
- ✅ Keep backups for at least 30 days
- ✅ Schedule upgrades during low-usage periods

### ❌ DON'T

- ❌ Skip backups
- ❌ Upgrade without reading release notes
- ❌ Skip version numbers (e.g., 1.0 → 1.3)
- ❌ Delete pre-upgrade backup immediately
- ❌ Force upgrade if health check fails
- ❌ Ignore database migration errors

---

## Release Channels

### Stable (Recommended)

- Fully tested releases
- Production-ready
- Tagged versions (e.g., v1.0.0)
- Updated monthly

```bash
docker pull vibe-quality-searcharr:1.0.0
```

### Latest

- Most recent stable release
- Updated with each release
- Good for auto-updates

```bash
docker pull vibe-quality-searcharr:latest
```

### Development (Not Recommended for Production)

- Bleeding edge features
- May be unstable
- For testing only

```bash
docker pull vibe-quality-searcharr:dev
```

---

## Staying Updated

### Check for Updates

```bash
# Check current version
docker inspect vibe-quality-searcharr | jq '.[0].Config.Labels."org.opencontainers.image.version"'

# Check latest available
curl -s https://api.github.com/repos/yourusername/vibe-quality-searcharr/releases/latest | jq -r .tag_name
```

### Subscribe to Updates

- **GitHub Releases:** Watch repository for releases
- **RSS Feed:** Subscribe to releases RSS feed
- **Email Notifications:** Enable in GitHub settings

---

## Emergency Procedures

### Critical Security Update

If a critical security vulnerability is announced:

1. **Update immediately** (even outside maintenance window)
2. **Use automated upgrade script** for fastest deployment
3. **Verify security fix** applied (check logs/version)
4. **Review access logs** for exploitation attempts

```bash
# Emergency upgrade
./scripts/upgrade.sh latest
```

### Database Corruption After Upgrade

1. **Stop application immediately**
   ```bash
   docker-compose down
   ```

2. **Restore from most recent backup**
   ```bash
   ./scripts/restore.sh backups/pre-upgrade-*.tar.gz
   ```

3. **Report issue on GitHub** with logs

---

## Additional Resources

- [Release Notes](https://github.com/yourusername/vibe-quality-searcharr/releases)
- [Changelog](../CHANGELOG.md)
- [Backup Guide](BACKUP_RESTORE.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Docker Deployment](DOCKER_DEPLOYMENT.md)

---

**Need Help?**

- GitHub Issues: https://github.com/yourusername/vibe-quality-searcharr/issues
- Documentation: https://github.com/yourusername/vibe-quality-searcharr/docs/
- Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
