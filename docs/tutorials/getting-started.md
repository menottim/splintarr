# Getting Started Guide

**Vibe-Quality-Searcharr v1.0.0**

Welcome! This guide will help you get Vibe-Quality-Searcharr up and running in 5 minutes.

---

## What is Vibe-Quality-Searcharr?

Vibe-Quality-Searcharr automates systematic backlog searching for your Sonarr and Radarr instances. It intelligently schedules searches to maximize coverage while respecting API rate limits.

**Key Benefits:**
- 🔍 Automatically searches for missing episodes/movies
- ⚡ Upgrades content that doesn't meet quality profiles
- 📊 Tracks search history to avoid duplicates
- 🎯 Respects indexer API limits
- 🔒 Secure by design (OWASP Top 10 compliant)

---

## Quick Start (5 Minutes)

### Step 1: Install Docker

**Already have Docker?** Skip to Step 2.

```bash
# Linux (Ubuntu/Debian)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker-compose --version
```

For other operating systems, see [Docker Installation](https://docs.docker.com/get-docker/).

### Step 2: Download Vibe-Quality-Searcharr

```bash
# Clone repository
git clone https://github.com/yourusername/vibe-quality-searcharr.git
cd vibe-quality-searcharr

# Or download and extract
wget https://github.com/yourusername/vibe-quality-searcharr/archive/v1.0.0.tar.gz
tar -xzf v1.0.0.tar.gz
cd vibe-quality-searcharr-1.0.0
```

### Step 3: Generate Security Secrets

```bash
./scripts/generate-secrets.sh
```

This creates cryptographically secure keys in the `secrets/` directory.

### Step 4: Start the Application

```bash
docker-compose up -d
```

Wait ~30 seconds for the application to start.

### Step 5: Access the Setup Wizard

Open your browser to: **http://localhost:7337/setup**

The setup wizard will guide you through:
1. Creating your admin account
2. Adding your first Sonarr/Radarr instance
3. Creating your first search queue

**That's it!** Vibe-Quality-Searcharr is now running and searching for you.

---

## First-Time Setup Wizard

### Welcome Screen

![Setup Wizard - Welcome](../assets/setup-wizard-welcome.png)

Click "Get Started" to begin.

### 1. Create Admin Account

**Create your administrator account:**

- **Username**: Choose a username (3-50 characters)
- **Password**: Strong password required
  - Minimum 12 characters
  - Mix of uppercase, lowercase, numbers, symbols
  - Example: `MySecure#Pass2024!`
- **Confirm Password**: Re-enter to confirm

**Security tip:** Use a password manager to generate and store a strong password.

Click "Create Account" to continue.

### 2. Add Sonarr or Radarr Instance

**Connect your first instance:**

| Field | Description | Example |
|-------|-------------|---------|
| **Name** | Friendly name for this instance | "Main Sonarr" |
| **Type** | Select Sonarr or Radarr | Sonarr |
| **URL** | Full URL to instance | http://192.168.1.100:8989 |
| **API Key** | From instance settings | abc123def456... |

**Finding your API key:**

**Sonarr:**
1. Open Sonarr web interface
2. Settings → General → Security → API Key
3. Copy the key

**Radarr:**
1. Open Radarr web interface
2. Settings → General → Security → API Key
3. Copy the key

Click "Test Connection" to verify, then "Add Instance".

### 3. Create Your First Search Queue

**Set up automated searching:**

| Field | Description | Recommendation |
|-------|-------------|----------------|
| **Name** | Queue name | "Daily Missing Search" |
| **Instance** | Select from dropdown | (instance you just added) |
| **Strategy** | What to search for | Missing |
| **Schedule** | When to run | Daily at 2:00 AM |
| **Items per batch** | How many to search | 50 |

**Search Strategies:**

- **Missing**: Search for all missing episodes/movies
- **Cutoff Unmet**: Search for upgrades (better quality)
- **Recent**: Search recent additions only
- **Custom**: Advanced filtering options

Click "Create Queue" and then "Complete Setup".

### 4. Setup Complete!

You'll be redirected to the dashboard where you can monitor your searches.

---

## Dashboard Overview

### Main Dashboard

The dashboard shows:

1. **Instance Status** - Health of each Sonarr/Radarr instance
2. **Active Search Queues** - Currently running searches
3. **Recent Searches** - Last 24 hours of search activity
4. **Statistics** - Total searches, success rate, items found

### Navigation

- **Dashboard** - Overview and statistics
- **Instances** - Manage Sonarr/Radarr connections
- **Search Queues** - Create and manage search automation
- **Search History** - View all searches and results
- **Settings** - Change account settings, 2FA

---

## Adding More Instances

### From Dashboard

1. Click "Instances" in navigation
2. Click "Add Instance" button
3. Fill in details (name, type, URL, API key)
4. Click "Test Connection"
5. Click "Save"

**You can add multiple instances:**
- Multiple Sonarr instances (e.g., TV4K, TV1080p)
- Multiple Radarr instances (e.g., Movies4K, Movies1080p)
- Mix of both

Each instance can have its own search queue with different strategies and schedules.

---

## Creating Search Queues

### Search Queue Options

**Name:** Descriptive name (e.g., "Weekly 4K Upgrades")

**Instance:** Select which Sonarr/Radarr instance

**Strategy:**
- **Missing** - Search all content marked as missing
- **Cutoff Unmet** - Search content below quality cutoff
- **Recent** - Only search recently added content
- **Custom** - Advanced: filter by tags, quality, etc.

**Schedule:**
- **Cron Expression** - For advanced scheduling
  - Daily at 2 AM: `0 2 * * *`
  - Every 6 hours: `0 */6 * * *`
  - Weekdays at noon: `0 12 * * 1-5`
- **Or use presets** - Daily, weekly, etc.

**Items per Batch:**
- How many items to search in one run
- Higher = faster, more API load
- Recommended: 20-50

**Enabled:**
- Check to start immediately
- Uncheck to create but not start

### Example Queues

**Daily Missing Search:**
```
Name: Daily Missing
Strategy: Missing
Schedule: 0 2 * * * (2 AM daily)
Batch Size: 50
```

**Weekly Quality Upgrade:**
```
Name: Weekend Upgrades
Strategy: Cutoff Unmet
Schedule: 0 2 * * 6 (Saturday 2 AM)
Batch Size: 30
```

**Continuous Recent:**
```
Name: Recent Additions
Strategy: Recent (last 30 days)
Schedule: 0 */6 * * * (Every 6 hours)
Batch Size: 20
```

---

## Understanding Search History

### What Gets Tracked

Every search operation is logged with:
- Date and time
- Instance name
- Search strategy used
- Item searched (episode/movie)
- Result (success/failure)
- Downloads found

### Cooldown Period

**24-hour cooldown:** Once an item is searched, it won't be searched again for 24 hours.

**Why?** Prevents overwhelming your indexers with duplicate searches.

**Override:** You can manually trigger immediate search from instance management.

### Viewing History

1. Go to "Search History"
2. Filter by:
   - Date range
   - Instance
   - Success/failure
   - Search strategy

---

## Enable Two-Factor Authentication (Recommended)

### Setup 2FA

1. Go to "Settings" → "Security"
2. Click "Enable 2FA"
3. Scan QR code with authenticator app:
   - Google Authenticator
   - Authy
   - 1Password
   - Bitwarden
4. Enter 6-digit code to verify
5. **Save backup codes** in secure location

### Using 2FA

After setup, you'll be prompted for a 6-digit code after entering your password.

**Lost device?** Use backup codes to regain access.

---

## Configuration Tips

### For Best Performance

1. **Stagger search schedules** across instances
   - Instance 1: 2 AM
   - Instance 2: 3 AM
   - Instance 3: 4 AM

2. **Adjust batch sizes** based on your indexers
   - More indexers = higher batch size
   - Fewer indexers = lower batch size

3. **Use different strategies** for different needs
   - Missing: Daily
   - Cutoff Unmet: Weekly
   - Recent: Every 6 hours

### Resource Management

**Memory usage:**
- Light usage (<5 instances): 256-512 MB
- Medium usage (5-15 instances): 512 MB-1 GB
- Heavy usage (15+ instances): 1-2 GB

Adjust in `docker-compose.yml` if needed.

---

## Common Tasks

### Change Password

1. Settings → Account → Change Password
2. Enter current password
3. Enter new password (twice)
4. Click "Update Password"

### Test Instance Connection

1. Instances → Select instance
2. Click "Test Connection"
3. View response time and status
4. Check "Configuration Drift" for changes

### Pause Search Queue

1. Search Queues → Select queue
2. Click "Pause"
3. Resume when ready with "Resume" button

### View Logs

```bash
# View all logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Search for errors
docker-compose logs | grep -i error
```

---

## Troubleshooting Quick Fixes

### Can't Connect to Instance

**Check:**
1. URL is correct (include http:// or https://)
2. Port is included (e.g., :8989)
3. API key is correct
4. Instance is running and accessible
5. Firewall allows connection

**Test from Docker container:**
```bash
docker exec vibe-quality-searcharr curl -v http://your-sonarr:8989/api/v3/system/status?apikey=YOUR_KEY
```

### Searches Not Running

**Check:**
1. Queue is enabled (green toggle)
2. Schedule is correct
3. Instance is connected
4. Check Search History for errors

### Forgot Password

**Reset via Docker:**
```bash
# Access container
docker exec -it vibe-quality-searcharr sh

# Reset password (future feature)
# For now, restore from backup or recreate
```

### Application Won't Start

```bash
# Check logs
docker-compose logs

# Common fixes:
# 1. Port conflict
sudo lsof -i :7337

# 2. Permission issues
sudo chown -R 1000:1000 data/

# 3. Secrets missing
./scripts/generate-secrets.sh
```

---

## Next Steps

### Learn More

- **[User Guide](USER_GUIDE.md)** - Complete feature reference
- **[API Documentation](API_DOCUMENTATION.md)** - REST API reference
- **[Security Guide](SECURITY_GUIDE.md)** - Security best practices
- **[Troubleshooting](TROUBLESHOOTING.md)** - Detailed problem solving

### Advanced Topics

- **[Docker Deployment](DOCKER_DEPLOYMENT.md)** - Production deployment
- **[Backup & Restore](BACKUP_RESTORE.md)** - Data protection
- **[Upgrade Guide](UPGRADE_GUIDE.md)** - Keeping up-to-date

### Get Help

- **GitHub Issues:** Report bugs or request features
- **Discussions:** Ask questions, share tips
- **Documentation:** Complete guides in `/docs`

---

## Security Reminder

**⚠️ This is AI-generated code**

While implementing security best practices, this codebase:
- Has NOT been professionally audited
- May contain subtle security flaws
- Should be treated as educational/experimental

**For production use:**
- Deploy in isolated environment
- Use strong, unique passwords
- Enable 2FA
- Regular backups
- Keep updated
- Monitor logs

See [SECURITY_GUIDE.md](SECURITY_GUIDE.md) for detailed security recommendations.

---

## FAQ

**Q: How many instances can I add?**
A: Unlimited. Tested with 20+.

**Q: Does this affect my indexers?**
A: Yes - respects rate limits but uses API quota.

**Q: Can I run without Docker?**
A: Yes, see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md).

**Q: Does this work with Radarr v4/v5?**
A: Currently supports Radarr v3 API.

**Q: Can I exclude certain series/movies?**
A: Yes, use tags in Sonarr/Radarr and Custom strategy.

**Q: Is this safe to run 24/7?**
A: Yes, designed for continuous operation.

**Q: How do I update?**
A: See [UPGRADE_GUIDE.md](UPGRADE_GUIDE.md).

---

**Welcome to Vibe-Quality-Searcharr!**

Happy automated searching! 🎉
