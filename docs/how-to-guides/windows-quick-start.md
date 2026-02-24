# Windows Quick Start Guide

**Complete step-by-step guide for Windows users new to Docker**

This guide assumes you have **no Docker experience** and will walk you through every step needed to run Vibe-Quality-Searcharr on Windows.

---

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Install Docker Desktop](#install-docker-desktop)
3. [Download the Application](#download-the-application)
4. [Automated Setup](#automated-setup)
5. [Access the Application](#access-the-application)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

**What you need:**
- Windows 10/11 (64-bit) with WSL 2 enabled
- At least 4GB of RAM available
- 10GB of free disk space
- Internet connection
- Administrator access

**Estimated time:** 30-45 minutes for first-time setup

---

## Install Docker Desktop

Docker Desktop is the application that runs containers on Windows.

### Step 1: Download Docker Desktop

1. Open your web browser
2. Go to: https://www.docker.com/products/docker-desktop/
3. Click the **"Download for Windows"** button
4. Wait for the download to complete (approximately 500MB)

### Step 2: Install Docker Desktop

1. **Locate the downloaded file** in your Downloads folder (usually `Docker Desktop Installer.exe`)
2. **Right-click** on the installer and select **"Run as administrator"**
3. **Follow the installation wizard:**
   - ✅ Check **"Use WSL 2 instead of Hyper-V"** (recommended)
   - ✅ Check **"Add shortcut to desktop"** (optional, but helpful)
   - Click **"OK"** to start installation
4. **Wait** for installation (5-10 minutes)
5. Click **"Close and restart"** when prompted
6. **Restart your computer** (very important!)

### Step 3: Start Docker Desktop

1. After restart, **open Docker Desktop** from the Start Menu or desktop shortcut
2. **Accept the license agreement** if prompted
3. Wait for Docker Desktop to start (you'll see a whale icon in your system tray)
4. When you see **"Docker Desktop is running"**, you're ready!

### Step 4: Verify Docker Installation

1. Open **PowerShell** or **Command Prompt**:
   - Press `Windows + R`
   - Type `powershell` and press Enter
2. Type this command and press Enter:
   ```powershell
   docker --version
   ```
3. You should see output like: `Docker version 24.0.x, build xxxxxxx`
4. If you see an error, Docker Desktop is not running. Go back to Step 3.

---

## Download the Application

You have two options: download a ZIP file or use Git.

### Option A: Download ZIP (Easiest for Beginners)

1. Go to: https://github.com/menottim/vibe-quality-searcharr
2. Click the green **"Code"** button
3. Click **"Download ZIP"**
4. **Extract the ZIP file:**
   - Right-click the downloaded ZIP
   - Select **"Extract All..."**
   - Choose a location (e.g., `C:\Users\YourName\vibe-quality-searcharr`)
   - Click **"Extract"**
5. **Remember this location** - you'll need it in the next steps!

### Option B: Use Git (If you have Git installed)

1. Open **PowerShell** or **Git Bash**
2. Navigate to where you want the files:
   ```powershell
   cd C:\Users\YourName
   ```
3. Clone the repository:
   ```powershell
   git clone https://github.com/menottim/vibe-quality-searcharr.git
   ```
4. Enter the directory:
   ```powershell
   cd vibe-quality-searcharr
   ```

---

## Automated Setup

**The easy way:** Run our automated setup script that does everything for you!

### Step 1: Navigate to the Project Folder

1. Open **File Explorer**
2. Navigate to where you extracted/cloned the project
3. **Right-click in the folder** (not on a file)
4. Select **"Open in Terminal"** or **"Open PowerShell window here"**
   - If you don't see this option, open PowerShell and use `cd` to navigate:
     ```powershell
     cd "C:\Users\YourName\vibe-quality-searcharr"
     ```

### Step 2: Allow PowerShell Scripts (One-Time Setup)

```powershell
# Allow scripts to run (one-time setup)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Step 3: Run the Setup Script

**Option A: Complete Automated Setup (Recommended)**

This builds and starts everything automatically:

```powershell
.\scripts\setup-windows.ps1 -AutoStart
```

**Option B: Setup Only (Manual Start)**

This prepares everything but lets you start manually:

```powershell
.\scripts\setup-windows.ps1
```

**What the setup script does:**
- ✅ Checks Docker and Docker Compose are installed
- ✅ Verifies Docker is running
- ✅ Creates the `data` directory for your database
- ✅ Creates the `secrets` directory
- ✅ Generates 3 cryptographically secure encryption keys
- ✅ Validates all keys were created correctly
- ✅ Sets secure file permissions
- ✅ (With `-AutoStart`) Builds the Docker image
- ✅ (With `-AutoStart`) Starts the application

**What you'll see:**

```
================================================================
  Vibe-Quality-Searcharr - Windows Setup
================================================================

ℹ️  This script will set up Vibe-Quality-Searcharr on your system.

Step 1: Checking Prerequisites
----------------------------------------

ℹ️  Checking for Docker...
✓ Docker found: Docker version 24.0.7, build afdd53b
ℹ️  Checking for Docker Compose...
✓ Docker Compose found: Docker Compose version v2.24.5
ℹ️  Checking if Docker is running...
✓ Docker is running

Step 2: Creating Required Directories
----------------------------------------

ℹ️  Creating data directory...
✓ Created: C:\Users\YourName\vibe-quality-searcharr\data
ℹ️  Creating secrets directory...
✓ Created: C:\Users\YourName\vibe-quality-searcharr\secrets

Step 3: Generating Encryption Keys
----------------------------------------

ℹ️  Running secret generation script...

[... secret generation output ...]

Step 4: Docker Setup
----------------------------------------

ℹ️  Building Docker image...
[... build output ...]
✓ Docker image built successfully

ℹ️  Starting application...
✓ Application started

================================================================
Setup Complete!
================================================================

Next Steps:

  1. Check the application logs:
     docker-compose logs -f

  2. Open your browser to:
     http://localhost:7337

  3. Follow the setup wizard to create your admin account
```

### Step 4: Verify It's Running

```powershell
docker-compose ps
```

You should see:
```
NAME                      STATUS          PORTS
vibe-quality-searcharr    Up 30 seconds   127.0.0.1:7337->7337/tcp
```

The `STATUS` should say "Up" (not "Exited" or "Restarting").

**⚠️ IMPORTANT: Backup Your Encryption Keys!**

The setup script created encryption keys in the `secrets/` folder. If you lose these, you cannot decrypt your data!

```powershell
# View your secret files
Get-ChildItem -Path secrets
```

You should see:
- `db_key.txt`
- `secret_key.txt`
- `pepper.txt`

**Copy these to a secure location:**
- Password manager (1Password, Bitwarden, etc.)
- Encrypted USB drive
- Secure cloud storage (encrypted)

---

## Manual Setup (Alternative)

If you prefer to run commands individually or the automated script fails:

### Generate Security Keys Manually

```powershell
# Run the key generation script
.\scripts\generate-secrets.ps1
```

### Build and Start Manually

```powershell
# Create data directory
New-Item -ItemType Directory -Force -Path .\data

# Build the Docker image
docker-compose build

# Start the container
docker-compose up -d

# Verify it's running
docker-compose ps
```

---

## Access the Application

### Step 1: Open Your Browser

1. Open your favorite web browser (Chrome, Edge, Firefox)
2. Go to: **http://localhost:7337**

### Step 2: Complete Setup Wizard

You should see a welcome screen! Follow the setup wizard:

1. **Create Admin Account:**
   - Choose a username (e.g., `admin`)
   - Create a strong password (min 12 characters, with uppercase, lowercase, number, special character)
   - Click **"Create Account"**

2. **Add Your First Instance:**
   - Choose instance type (Sonarr or Radarr)
   - Enter your Sonarr/Radarr URL (e.g., `http://192.168.1.100:8989`)
   - Enter your API key (found in Settings → General in Sonarr/Radarr)
   - Click **"Test Connection"**
   - Click **"Save"**

3. **Start Searching!**
   - Configure your search preferences
   - Create search queues
   - Let the automation begin!

---

## Troubleshooting

### Problem: "docker: command not found"

**Solution:**
1. Make sure Docker Desktop is running (check system tray for whale icon)
2. Restart PowerShell
3. If still failing, reinstall Docker Desktop

### Problem: "Cannot connect to Docker daemon"

**Solution:**
1. Open Docker Desktop from Start Menu
2. Wait for it to fully start (whale icon stops animating)
3. Try the command again

### Problem: "Port 7337 is already in use"

**Solution:**
1. Another program is using port 7337
2. Stop the other program, OR
3. Change the port in `docker-compose.yml`:
   ```yaml
   ports:
     - "127.0.0.1:8080:7337"  # Change 7337 to 8080 (or any available port)
   ```
4. Access at `http://localhost:8080` instead

### Problem: "no configuration file provided: not found"

**Solution:**
1. Make sure you're in the correct directory:
   ```powershell
   pwd  # Shows current directory
   ```
2. The directory should contain `docker-compose.yml`
3. If not, navigate to the correct directory:
   ```powershell
   cd "C:\Users\YourName\vibe-quality-searcharr"
   ```

### Problem: Container keeps restarting

**Solution:**
1. Check the logs:
   ```powershell
   docker-compose logs
   ```
2. Look for errors (usually missing secret files or configuration issues)
3. Common fixes:
   - Regenerate secret files: `.\scripts\generate-secrets.ps1`
   - Ensure data directory exists: `New-Item -ItemType Directory -Force -Path .\data`
   - Check Docker Desktop has enough memory (Settings → Resources → Increase memory to 4GB+)

### Problem: "unable to open database file" error

**Symptoms:**
```
ERROR: (sqlcipher3.dbapi2.OperationalError) unable to open database file
RuntimeError: Failed to initialize database
```

**Solution:**
1. Stop the container:
   ```powershell
   docker-compose down
   ```
2. Ensure the data directory exists:
   ```powershell
   New-Item -ItemType Directory -Force -Path .\data
   ```
3. Verify Docker has write permissions (Settings → Resources → File Sharing → Add your project directory)
4. Rebuild and restart:
   ```powershell
   docker-compose build
   docker-compose up -d
   ```
5. If still failing, try running the automated setup script again:
   ```powershell
   .\scripts\setup-windows.ps1 -AutoStart
   ```

### Problem: "WSL 2 installation is incomplete"

**Solution:**
1. Open PowerShell as Administrator
2. Run:
   ```powershell
   wsl --install
   ```
3. Restart your computer
4. Try starting Docker Desktop again

### Problem: Application is slow

**Solution:**
1. Open Docker Desktop
2. Go to Settings → Resources
3. Increase:
   - **CPUs:** At least 2
   - **Memory:** At least 4GB
4. Click **"Apply & Restart"**

---

## Stopping the Application

To stop the container:

```powershell
docker-compose down
```

To stop and remove all data (⚠️ destructive!):

```powershell
docker-compose down -v
```

---

## Updating the Application

When a new version is released:

```powershell
# Pull latest code (if using Git)
git pull

# Or download new ZIP and extract over old files

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

---

## Getting Help

**Still stuck?**

1. Check the [Troubleshooting Guide](./troubleshoot.md)
2. Search [GitHub Issues](https://github.com/menottim/vibe-quality-searcharr/issues)
3. Create a new issue with:
   - Your Windows version
   - Docker Desktop version
   - Full error message
   - Steps you've tried

**Remember:** Include logs but **NEVER** share your secret keys!

```powershell
# Get logs (safe to share)
docker-compose logs > logs.txt
```

---

## Post-Deployment: Critical Security Steps

**⚠️ IMPORTANT:** Before using the application, complete these security hardening steps!

### Step 1: Update Dependencies (Fix Known CVEs)

Some dependencies have known security vulnerabilities that are easy to fix:

```powershell
# Stop the container
docker-compose down

# The application needs updated dependencies
# Download the latest version from GitHub (it includes the fixes)
# Or if you're using Git:
git pull

# Rebuild with latest dependencies
docker-compose build --no-cache

# Restart
docker-compose up -d
```

**What this fixes:**
- CVE-2025-62727: DoS vulnerability in Starlette
- CVE-2025-54121: DoS vulnerability in Starlette

### Step 2: Verify Production Configuration

Make sure these settings are correct:

```powershell
# Navigate to your project folder
cd C:\Users\YourName\vibe-quality-searcharr

# Check your configuration
Get-Content .env
```

**Required settings for security:**

Create a `.env` file in your project folder with these settings:

```
# Production mode (REQUIRED)
ENVIRONMENT=production

# Security cookies (REQUIRED)
SECURE_COOKIES=true

# Block local instance URLs unless testing (REQUIRED)
ALLOW_LOCAL_INSTANCES=false

# Single worker mode (REQUIRED for rate limiting)
WORKERS=1

# Your secret keys are already in the secrets/ folder ✅
SECRET_KEY_FILE=/run/secrets/secret_key
PEPPER_FILE=/run/secrets/pepper
DATABASE_KEY_FILE=/run/secrets/db_key
```

**Apply the changes:**
```powershell
docker-compose down
docker-compose up -d
```

### Step 3: Enable HTTPS (Recommended)

For secure access, you should use HTTPS. The easiest way on Windows is using Cloudflare Tunnel (free):

**Option A: Cloudflare Tunnel (Easiest for Windows)**

1. Sign up for free Cloudflare account at https://dash.cloudflare.com
2. Download cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
3. Run the tunnel:
   ```powershell
   cloudflared tunnel --url http://localhost:7337
   ```
4. Follow the link to access your app securely via HTTPS

**Option B: Self-Signed Certificate (Local Network Only)**

If you only access from your local network, you can skip HTTPS for now, but understand this is **less secure**.

### Step 4: Verify Everything is Working Securely

```powershell
# Check the application is running in production mode
docker-compose exec vibe-quality-searcharr env | Select-String "ENVIRONMENT"
# Should show: ENVIRONMENT=production

# Check logs for any errors
docker-compose logs --tail 50
```

### Step 5: Set Up Regular Backups

**Your data is important!** Set up automated backups:

```powershell
# Create a backup folder
New-Item -ItemType Directory -Force -Path backups

# Manual backup command (run this weekly)
Copy-Item -Path data\* -Destination backups\backup_$(Get-Date -Format "yyyy-MM-dd")\ -Recurse
Copy-Item -Path secrets\* -Destination backups\backup_$(Get-Date -Format "yyyy-MM-dd")\secrets\ -Recurse
```

**Set up automatic backups** using Windows Task Scheduler:

1. Open **Task Scheduler** from Start Menu
2. Create Basic Task → Name it "Vibe Backup"
3. Trigger: Weekly (Sunday at 2 AM)
4. Action: Start a Program
5. Program: `powershell.exe`
6. Arguments:
   ```
   -File "C:\Users\YourName\vibe-quality-searcharr\backup.ps1"
   ```
7. Create `backup.ps1` in your project folder:
   ```powershell
   $date = Get-Date -Format "yyyy-MM-dd"
   $backup = "backups\backup_$date"
   New-Item -ItemType Directory -Force -Path $backup
   Copy-Item -Path data\* -Destination $backup\ -Recurse
   Copy-Item -Path secrets\* -Destination "$backup\secrets\" -Recurse
   Write-Host "Backup completed: $backup"
   ```

---

## Next Steps

Now that security is configured, explore these features:

- [Configure Search Strategies](../explanation/search-strategies.md) - Set up automated searches
- [Advanced Configuration](../reference/configuration.md) - Fine-tune settings
- [Security Best Practices](../explanation/security.md) - Learn more about security
- [Troubleshooting Guide](./troubleshoot.md) - Solutions to common problems

---

## Security Checklist ✅

Before considering your installation complete, verify:

- [ ] Dependencies updated (rebuilt with latest code)
- [ ] ENVIRONMENT=production in .env file
- [ ] SECURE_COOKIES=true in .env file
- [ ] WORKERS=1 in .env file
- [ ] Secret keys generated (in secrets/ folder)
- [ ] HTTPS enabled (via Cloudflare or reverse proxy)
- [ ] Backups configured (weekly recommended)
- [ ] Application accessible at http://localhost:7337 (or your domain)
- [ ] Setup wizard completed
- [ ] First admin account created with strong password (12+ characters)

**Once all boxes are checked, you're ready to use the application securely!**

---

**Congratulations!** 🎉 You've successfully installed **and secured** Vibe-Quality-Searcharr on Windows!
