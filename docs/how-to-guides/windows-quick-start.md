# Windows Quick Start Guide

---

## Quick Start

For experienced users who already have Docker Desktop installed and running:

```powershell
# 1. Clone or download the repository
git clone https://github.com/menottim/splintarr.git
cd splintarr

# 2. Allow PowerShell scripts (one-time)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 3. Run automated setup (generates keys, builds, starts)
.\scripts\setup-windows.ps1 -AutoStart

# 4. Open http://localhost:7337 and complete the setup wizard
```

The setup script generates encryption keys, builds the Docker image, and starts the container. When it finishes, open your browser to `http://localhost:7337` to create your admin account and connect your first Sonarr/Radarr instance.

**Password reset (if locked out):**
```powershell
docker-compose exec splintarr python -m splintarr.cli reset-password
```

---

## Detailed Setup

This section walks through every step for users who have never used Docker before.

**Estimated time:** 30-45 minutes for first-time setup.

### Prerequisites

- Windows 10 or 11 (64-bit) with WSL 2 enabled
- At least 4GB of RAM available
- 10GB of free disk space
- Internet connection
- Administrator access

### Install Docker Desktop

Docker Desktop is the application that runs containers on Windows.

**1. Download Docker Desktop**

Go to https://www.docker.com/products/docker-desktop/ and click "Download for Windows." The download is approximately 500MB.

**2. Install Docker Desktop**

- Locate the downloaded `Docker Desktop Installer.exe` in your Downloads folder
- Right-click and select "Run as administrator"
- Check "Use WSL 2 instead of Hyper-V" (recommended)
- Click "OK" and wait 5-10 minutes for installation
- Click "Close and restart" when prompted
- Restart your computer

**3. Start Docker Desktop**

- After restart, open Docker Desktop from the Start Menu
- Accept the license agreement if prompted
- Wait for the whale icon in the system tray to stop animating
- When you see "Docker Desktop is running", you're ready

**4. Verify installation**

Open PowerShell (press `Windows + R`, type `powershell`, press Enter):

```powershell
docker --version
```

You should see output like `Docker version 24.0.x, build xxxxxxx`. If you see an error, Docker Desktop is not running -- go back to step 3.

### Download the Application

**Option A: Download ZIP (easiest)**

1. Go to https://github.com/menottim/splintarr
2. Click the green "Code" button, then "Download ZIP"
3. Right-click the ZIP, select "Extract All...", choose a location (e.g., `C:\Users\YourName\splintarr`)

**Option B: Use Git**

```powershell
cd C:\Users\YourName
git clone https://github.com/menottim/splintarr.git
cd splintarr
```

### Run the Setup Script

**1. Open PowerShell in the project folder**

Navigate to where you extracted/cloned the project, right-click in the folder, and select "Open in Terminal" or "Open PowerShell window here." Alternatively:

```powershell
cd "C:\Users\YourName\splintarr"
```

**2. Allow PowerShell scripts (one-time)**

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**3. Run the setup**

```powershell
.\scripts\setup-windows.ps1 -AutoStart
```

This script will:
- Check that Docker and Docker Compose are installed and running
- Create the `data` and `secrets` directories
- Generate 3 cryptographically secure encryption keys
- Fix shell script line endings for Docker compatibility
- Build the Docker image
- Start the application

If you prefer to build and start manually, omit the `-AutoStart` flag.

**4. Verify it's running**

```powershell
docker-compose ps
```

The STATUS column should say "Up." If it says "Exited" or "Restarting," check the [Troubleshooting](#troubleshooting) section below.

### Back Up Your Encryption Keys

The setup script created encryption keys in the `secrets/` folder. If you lose these, you cannot decrypt your data.

```powershell
Get-ChildItem -Path secrets
```

You should see `db_key.txt`, `secret_key.txt`, and `pepper.txt`. Copy these to a secure location (password manager, encrypted USB drive, etc.).

### Access the Application

1. Open your browser to **http://localhost:7337**
2. Follow the setup wizard:
   - Create an admin account (username + strong password with 12+ characters, uppercase, lowercase, digit, special character)
   - Add your first Sonarr or Radarr instance (enter the URL and API key from Settings > General in Sonarr/Radarr)
   - Click "Test Connection" to verify, then save
3. Configure search queues and start automating

---

## Troubleshooting

### "docker: command not found"

1. Make sure Docker Desktop is running (check system tray for the whale icon)
2. Restart PowerShell
3. If still failing, reinstall Docker Desktop

### "Cannot connect to Docker daemon"

1. Open Docker Desktop from the Start Menu
2. Wait for it to fully start (whale icon stops animating)
3. Try the command again

### "Port 7337 is already in use"

Another program is using port 7337. Either stop that program, or change the port in `docker-compose.yml`:

```yaml
ports:
  - "127.0.0.1:8080:7337"  # Change 7337 to any available port
```

Then access the application at `http://localhost:8080`.

### "no configuration file provided: not found"

Make sure you're in the correct directory. Run `pwd` to check, then navigate to the project folder:

```powershell
cd "C:\Users\YourName\splintarr"
```

The directory must contain `docker-compose.yml`.

### Container keeps restarting

Check the logs for error details:

```powershell
docker-compose logs --tail=100
```

Common fixes:
- Regenerate secret files: `.\scripts\generate-secrets.ps1`
- Ensure data directory exists: `New-Item -ItemType Directory -Force -Path .\data`
- Ensure logs directory exists: `New-Item -ItemType Directory -Force -Path .\logs`
- Increase Docker Desktop memory: Settings > Resources > set to 4GB+

### "unable to open database file"

This usually means the data directory doesn't exist or Docker can't write to it:

1. Stop the container: `docker-compose down`
2. Create the data directory: `New-Item -ItemType Directory -Force -Path .\data`
3. Verify Docker has file sharing access: Docker Desktop > Settings > Resources > File Sharing > add your project directory
4. Rebuild and restart: `docker-compose build && docker-compose up -d`

### Docker build fails with "parent snapshot does not exist"

Docker Desktop's build cache has become corrupted. Clear it and rebuild:

```powershell
docker builder prune --all --force
docker-compose build --no-cache
docker-compose up -d
```

If that doesn't resolve it, do a full cleanup:

```powershell
docker system prune --all --force
docker-compose build
docker-compose up -d
```

### "WSL 2 installation is incomplete"

Open PowerShell as Administrator and run:

```powershell
wsl --install
```

Restart your computer, then start Docker Desktop again.

### Application is slow

Open Docker Desktop > Settings > Resources and increase:
- CPUs: at least 2
- Memory: at least 4GB

Click "Apply & Restart."

### Enable debug logging

Edit your `.env` file (or `docker-compose.yml` environment section) to set `LOG_LEVEL=DEBUG`, then restart:

```powershell
docker-compose down && docker-compose up -d
docker-compose logs -f
```

Log files are located at `logs/all.log`, `logs/error.log`, and `logs/debug.log`. They rotate automatically at 10MB (5 backups kept).

---

## Stopping and Updating

**Stop the application:**

```powershell
docker-compose down
```

**Stop and remove all data (destructive):**

```powershell
docker-compose down -v
```

**Update to a new version:**

```powershell
git pull                              # or download new ZIP
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

---

## Backups

Set up weekly backups using Windows Task Scheduler:

1. Create a `backup.ps1` file in your project folder:
   ```powershell
   $date = Get-Date -Format "yyyy-MM-dd"
   $backup = "backups\backup_$date"
   New-Item -ItemType Directory -Force -Path $backup
   Copy-Item -Path data\* -Destination $backup\ -Recurse
   Copy-Item -Path secrets\* -Destination "$backup\secrets\" -Recurse
   Write-Host "Backup completed: $backup"
   ```
2. Open Task Scheduler from the Start Menu
3. Create Basic Task > name it "Vibe Backup"
4. Trigger: Weekly (e.g., Sunday at 2 AM)
5. Action: Start a Program
6. Program: `powershell.exe`
7. Arguments: `-File "C:\Users\YourName\splintarr\backup.ps1"`

---

## Windows Security Notice

On Windows, this application runs with elevated privileges (root) inside the Docker container. This is necessary because Windows and Linux handle file permissions differently -- when Docker mounts a Windows directory into a Linux container, the permission system doesn't translate properly. Running as root inside the container is the standard workaround.

**What this means in practice:**
- The container is sandboxed and isolated from your Windows installation by Docker's container isolation layer
- On Linux deployments, the application runs as a non-root user automatically
- If the container itself were compromised, an attacker would have root privileges within that container (but not on your Windows host)
- This is a common trade-off for Docker on Windows in home and development environments

For a homelab deployment, this is an acceptable trade-off. If you want to eliminate the root container risk entirely, deploy on a Linux system where the application runs as a non-root user with a read-only filesystem.

---

## Getting Help

1. Check the [full Troubleshooting Guide](./troubleshoot.md) for more solutions
2. Search [GitHub Issues](https://github.com/menottim/splintarr/issues)
3. Create a new issue with your Windows version, Docker Desktop version, full error message, and steps tried

Include logs but **never share your secret keys:**

```powershell
docker-compose logs > logs.txt
```

---

## Next Steps

- [Search Strategies](../explanation/search-strategies.md) - configure automated searches
- [Configuration Reference](../reference/configuration.md) - all available settings
- [Security Guide](../explanation/security.md) - security features and best practices
