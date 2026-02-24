# Windows Quick Start Guide

**Complete step-by-step guide for Windows users new to Docker**

This guide assumes you have **no Docker experience** and will walk you through every step needed to run Vibe-Quality-Searcharr on Windows.

---

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Install Docker Desktop](#install-docker-desktop)
3. [Download the Application](#download-the-application)
4. [Generate Security Keys](#generate-security-keys)
5. [Start the Application](#start-the-application)
6. [Access the Application](#access-the-application)
7. [Troubleshooting](#troubleshooting)

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

## Generate Security Keys

**Important:** These keys encrypt your data. Never share them!

### Step 1: Navigate to the Project Folder

1. Open **File Explorer**
2. Navigate to where you extracted/cloned the project
3. **Right-click in the folder** (not on a file)
4. Select **"Open in Terminal"** or **"Open PowerShell window here"**
   - If you don't see this option, open PowerShell and use `cd` to navigate:
     ```powershell
     cd "C:\Users\YourName\vibe-quality-searcharr"
     ```

### Step 2: Create the Secrets Folder

Type these commands one at a time, pressing Enter after each:

```powershell
# Create secrets directory
New-Item -ItemType Directory -Force -Path secrets

# Verify it was created
Test-Path secrets
```

You should see `True` after the last command.

### Step 3: Generate Random Keys

**Copy and paste this entire block into PowerShell** (it generates 3 random keys):

```powershell
# Generate database encryption key (32 random bytes, base64-encoded)
$dbKey = -join ((48..57) + (65..90) + (97..122) + (33,35,36,37,38,42,45,46,61,63,64,95) | Get-Random -Count 64 | ForEach-Object {[char]$_})
$dbKey | Out-File -FilePath "secrets\db_key.txt" -NoNewline -Encoding ASCII

# Generate JWT secret key (32 random bytes, base64-encoded)
$secretKey = -join ((48..57) + (65..90) + (97..122) + (33,35,36,37,38,42,45,46,61,63,64,95) | Get-Random -Count 64 | ForEach-Object {[char]$_})
$secretKey | Out-File -FilePath "secrets\secret_key.txt" -NoNewline -Encoding ASCII

# Generate password pepper (32 random bytes, base64-encoded)
$pepper = -join ((48..57) + (65..90) + (97..122) + (33,35,36,37,38,42,45,46,61,63,64,95) | Get-Random -Count 64 | ForEach-Object {[char]$_})
$pepper | Out-File -FilePath "secrets\pepper.txt" -NoNewline -Encoding ASCII

Write-Host "✅ Security keys generated successfully!" -ForegroundColor Green
Write-Host "⚠️  IMPORTANT: Never commit the 'secrets' folder to Git!" -ForegroundColor Yellow
```

### Step 4: Verify Key Files Were Created

```powershell
Get-ChildItem -Path secrets
```

You should see three files:
- `db_key.txt`
- `secret_key.txt`
- `pepper.txt`

**⚠️ BACKUP THESE FILES SECURELY!** If you lose them, you cannot decrypt your data.

---

## Start the Application

### Step 1: Build the Docker Image

This downloads dependencies and builds the application (takes 5-15 minutes the first time):

```powershell
docker-compose build
```

**What you'll see:**
- Many lines of text scrolling by
- "Building vibe-quality-searcharr"
- Download progress bars
- "Successfully built" at the end

**If you see errors about "no configuration file":**
- Make sure you're in the correct directory (use `pwd` to check)
- The directory should contain `docker-compose.yml`

### Step 2: Start the Container

```powershell
docker-compose up -d
```

**Explanation of flags:**
- `up` = Start the containers
- `-d` = Detached mode (runs in background)

**What you'll see:**
```
Creating network "vibe-quality-searcharr_default" ... done
Creating vibe-quality-searcharr ... done
```

### Step 3: Verify It's Running

```powershell
docker-compose ps
```

You should see:
```
NAME                      STATUS          PORTS
vibe-quality-searcharr    Up 30 seconds   127.0.0.1:7337->7337/tcp
```

The `STATUS` should say "Up" (not "Exited" or "Restarting").

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
   - Regenerate secret files (see Step 3 above)
   - Check Docker Desktop has enough memory (Settings → Resources → Increase memory to 4GB+)

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

## Next Steps

- [Configure Search Strategies](../explanation/search-strategies.md)
- [Set Up Backup & Restore](./backup-and-restore.md)
- [Security Best Practices](../explanation/security.md)
- [Advanced Configuration](../reference/configuration.md)

---

**Congratulations!** 🎉 You've successfully installed Vibe-Quality-Searcharr on Windows!
