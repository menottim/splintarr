# Pre-Deployment Security Checklist

**Before deploying Vibe-Quality-Searcharr to production, complete all items on this checklist.**

---

## 🔴 CRITICAL - Must Complete Before Use

### 1. Update Dependencies (Fix Known CVEs)

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**
```bash
# Stop container
docker-compose down

# Ensure you have the latest code
git pull  # or download latest release

# Rebuild with latest dependencies
docker-compose build --no-cache

# Restart
docker-compose up -d
```

**What This Fixes:**
- CVE-2025-62727: Starlette DoS via Range header
- CVE-2025-54121: Starlette DoS via multipart

**Verification:**
```bash
docker-compose exec vibe-quality-searcharr pip show starlette | grep Version
# Should show: Version: 0.49.1 or higher
```

---

### 2. Generate Strong Secret Keys

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**

**Linux/macOS:**
```bash
./scripts/generate-secrets.sh
```

**Windows (PowerShell):**
```powershell
.\scripts\generate-secrets.ps1
```

**What the script does:**
- ✅ Verifies prerequisites (Python 3 / PowerShell 5.1+)
- ✅ Generates cryptographically secure random keys
- ✅ Validates each key for proper length and randomness
- ✅ Sets restrictive file permissions
- ✅ Provides clear success/error messages

**Verification:**
```bash
# Check files exist and contain data
ls -lh secrets/
# All 3 files should be ~64 bytes each
```

**⚠️ BACKUP THESE FILES SECURELY!** Store copies in:
- Password manager (1Password, Bitwarden, etc.)
- Encrypted USB drive
- Secure cloud storage (encrypted)

**If you lose these files, you cannot decrypt your database!**

---

### 3. Configure Production Environment

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**

Create `.env` file in project root:

```bash
# Production Settings (REQUIRED)
ENVIRONMENT=production

# Security Settings (REQUIRED)
SECURE_COOKIES=true
ALLOW_LOCAL_INSTANCES=false

# Worker Configuration (REQUIRED)
WORKERS=1

# Secrets (REQUIRED - using Docker secrets)
SECRET_KEY_FILE=/run/secrets/secret_key
PEPPER_FILE=/run/secrets/pepper
DATABASE_KEY_FILE=/run/secrets/db_key

# Optional: Customize these if needed
# HOST=0.0.0.0
# PORT=7337
# LOG_LEVEL=INFO
```

**Verification:**
```bash
# After restart, check environment
docker-compose exec vibe-quality-searcharr env | grep -E "(ENVIRONMENT|SECURE_COOKIES|WORKERS)"
```

Should show:
- `ENVIRONMENT=production`
- `SECURE_COOKIES=true`
- `WORKERS=1`

---

### 4. Enable HTTPS/TLS

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**⚠️ DO NOT skip this step for production deployments!**

**Choose One Option:**

#### Option A: Nginx Reverse Proxy (Recommended)

1. Install nginx: `sudo apt-get install nginx certbot python3-certbot-nginx`
2. Get SSL certificate: `sudo certbot --nginx -d your-domain.com`
3. Configure nginx (see [deploy-with-docker.md](docs/how-to-guides/deploy-with-docker.md#c-enable-httpstls-required-for-production))
4. Test HTTPS: `curl -I https://your-domain.com`

#### Option B: Traefik (Docker-native)

1. Add Traefik service to docker-compose.yml
2. Configure Let's Encrypt (see docs)
3. Add labels to vibe-quality-searcharr service
4. Restart: `docker-compose up -d`

#### Option C: Cloudflare Tunnel (Easy for Windows)

1. Sign up: https://dash.cloudflare.com
2. Download cloudflared
3. Run: `cloudflared tunnel --url http://localhost:7337`
4. Access via provided HTTPS URL

**Verification:**
```bash
curl -I https://your-domain.com | grep -E "(HTTP|Strict-Transport-Security)"
```

Should see:
- `HTTP/2 200` or `HTTP/1.1 200`
- `Strict-Transport-Security: max-age=31536000`

---

## 🟠 HIGH PRIORITY - Complete Within First Week

### 5. Set Up Automated Backups

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**

**Linux/macOS (Cron):**
```bash
# Add to crontab (run weekly on Sunday at 2 AM)
crontab -e

# Add this line:
0 2 * * 0 /path/to/vibe-quality-searcharr/scripts/backup.sh
```

**Windows (Task Scheduler):**
- See [Windows Quick Start Guide - Step 5](docs/how-to-guides/windows-quick-start.md#step-5-set-up-regular-backups)

**Verification:**
```bash
# Test backup script
./scripts/backup.sh

# Check backup exists
ls -lh backups/
```

---

### 6. Configure Monitoring & Logging

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**

```yaml
# Add to docker-compose.yml logging section:
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
```

**Set up log monitoring:**
```bash
# View logs in real-time
docker-compose logs -f vibe-quality-searcharr

# Check for security events
docker-compose logs vibe-quality-searcharr | grep -E "(failed_login|locked|unauthorized)"

# Set up alerts (optional but recommended)
# Use tools like: Prometheus, Grafana, or simple email alerts
```

---

### 7. Test Security Configuration

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**

Run these tests to verify your security setup:

```bash
# 1. Check production mode
docker-compose exec vibe-quality-searcharr env | grep ENVIRONMENT
# Expected: ENVIRONMENT=production

# 2. Check secure cookies enabled
docker-compose exec vibe-quality-searcharr env | grep SECURE_COOKIES
# Expected: SECURE_COOKIES=true

# 3. Check secrets are loaded
docker-compose exec vibe-quality-searcharr env | grep -E "(SECRET_KEY_FILE|PEPPER_FILE|DATABASE_KEY_FILE)"
# Expected: All 3 variables should show /run/secrets/... paths

# 4. Check worker count
docker-compose exec vibe-quality-searcharr env | grep WORKERS
# Expected: WORKERS=1

# 5. Test HTTPS (if configured)
curl -I https://your-domain.com
# Expected: HTTP 200 + Strict-Transport-Security header

# 6. Test rate limiting (should see 429 after 5 attempts)
for i in {1..6}; do curl -X POST https://your-domain.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"wrong"}'; done
# Expected: First 5 attempts return 401, 6th returns 429 (rate limited)
```

---

## 🟡 MEDIUM PRIORITY - Complete Within First Month

### 8. Review Security Documentation

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**

Read these documents:
- [ ] [Security Explanation](docs/explanation/security.md)
- [ ] [Comprehensive Security Assessment](COMPREHENSIVE_SECURITY_ASSESSMENT_POST_FIX.md)
- [ ] [Security Fixes Completed](SECURITY_FIXES_COMPLETED.md)

**Understand:**
- What security features are implemented
- What the limitations are (homelab vs. production)
- What additional hardening you may need

---

### 9. Create Incident Response Plan

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**

Document what to do if:
1. **Suspected breach:**
   - Stop container: `docker-compose down`
   - Preserve logs: `docker-compose logs > incident-$(date +%Y%m%d).log`
   - Rotate all secrets (regenerate keys)
   - Restore from backup if needed

2. **Data loss:**
   - Restore from latest backup
   - Verify data integrity
   - Check backup automation is working

3. **Service unavailable:**
   - Check logs: `docker-compose logs --tail 100`
   - Restart: `docker-compose restart`
   - Check disk space: `df -h`
   - Check memory: `free -h`

---

### 10. Schedule Security Reviews

**Status:** [ ] Not Started | [ ] In Progress | [ ] ✅ Complete

**Action Required:**

Set calendar reminders for:

- **Weekly:** Check logs for failed login attempts
- **Monthly:** Update dependencies (`docker-compose build --no-cache`)
- **Quarterly:** Review user accounts (remove inactive)
- **Quarterly:** Test backup restoration
- **Annually:** Full security audit (if budget allows)

---

## 🔵 NICE TO HAVE - Complete As Needed

### 11. Additional Hardening (Optional)

- [ ] Set up WAF (Web Application Firewall)
- [ ] Configure fail2ban for additional rate limiting
- [ ] Set up intrusion detection (OSSEC, Wazuh)
- [ ] Implement Redis for multi-worker rate limiting
- [ ] Add MFA/2FA (when implemented)
- [ ] Set up VPN access only (if highly sensitive)

---

## Final Verification Checklist

Before considering deployment complete:

- [ ] ✅ All CRITICAL items completed
- [ ] ✅ All HIGH PRIORITY items completed or scheduled
- [ ] ✅ Application accessible via HTTPS
- [ ] ✅ Admin account created with strong password (12+ characters)
- [ ] ✅ First instance added and tested
- [ ] ✅ Search queue created and running
- [ ] ✅ Backups tested (can restore successfully)
- [ ] ✅ Monitoring configured and working
- [ ] ✅ Incident response plan documented
- [ ] ✅ Team members trained (if multi-user)

---

## Deployment Status

**Date Started:** _______________

**Date Completed:** _______________

**Deployed By:** _______________

**Reviewed By:** _______________

**Deployment Environment:**
- [ ] Homelab (personal use)
- [ ] Small team (<5 users)
- [ ] Production (requires additional security audit)

**Risk Assessment:**
- [ ] **LOW RISK** - All checklist items complete, homelab use
- [ ] **MEDIUM RISK** - Most items complete, some pending
- [ ] **HIGH RISK** - Critical items incomplete (DO NOT DEPLOY)

---

## Need Help?

- **Documentation:** [docs/](docs/)
- **Troubleshooting:** [docs/how-to-guides/troubleshoot.md](docs/how-to-guides/troubleshoot.md)
- **GitHub Issues:** https://github.com/menottim/vibe-quality-searcharr/issues
- **Security Questions:** See [SECURITY.md](SECURITY.md) for reporting process

---

**Remember:** This is an educational project developed with AI assistance. While all known security vulnerabilities have been addressed, professional security auditing is recommended before any production use beyond personal homelabs.
