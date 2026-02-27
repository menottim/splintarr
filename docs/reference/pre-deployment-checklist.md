# Pre-Deployment Checklist

A simple checklist for deploying Splintarr on a homelab.

---

## Prerequisites

- [ ] Docker installed and running
- [ ] Project files downloaded (git clone or release archive)

---

## Step 1: Run the Setup Script

The setup script handles secret generation, data directory creation, image
building, and container startup.

**Windows (PowerShell):**
```powershell
.\setup-windows.ps1
```

**Linux / macOS:**
```bash
./setup.sh
```

When the script finishes, the application will be running at
`http://localhost:7337`.

---

## Step 2: Complete the Setup Wizard

Open `http://localhost:7337` in a browser. The wizard walks through:

- [ ] Create an admin account (use a strong password, 12+ characters)
- [ ] Add your first Sonarr or Radarr instance
- [ ] Verify the instance connects successfully

---

## Step 3: Back Up Encryption Keys

The setup script generated three files in the `secrets/` directory:

- `db_key.txt` -- encrypts the database
- `secret_key.txt` -- signs session cookies
- `pepper.txt` -- strengthens password hashes

**If you lose these files, you cannot decrypt your database.**

- [ ] Copy the `secrets/` directory to a secure location (password manager,
      encrypted USB drive, etc.)

---

## Step 4 (Optional): Set Up Automated Backups

**Linux / macOS (cron):**
```bash
# Run weekly on Sunday at 2 AM
crontab -e
0 2 * * 0 /path/to/splintarr/scripts/backup.sh
```

**Windows (Task Scheduler):**

See the Windows Quick Start guide for Task Scheduler instructions.

Test the backup manually once:
```bash
./scripts/backup.sh
ls -lh backups/
```

---

## Step 5 (Optional): Configure a Reverse Proxy for HTTPS

Not required for local-only access. Recommended if the application is exposed
beyond your local network.

Options include:

- **Nginx + Let's Encrypt** -- standard reverse proxy setup
- **Traefik** -- Docker-native reverse proxy with automatic certificates
- **Cloudflare Tunnel** -- no port forwarding needed, free HTTPS

---

## Quick Verification

After completing the steps above, confirm everything is working:

```bash
# Container is running
docker ps | grep splintarr

# Application responds
curl -s -o /dev/null -w "%{http_code}" http://localhost:7337
# Expected: 200 or 303 (redirect to login)
```

- [ ] Can log in with the admin account
- [ ] Added instance shows a connected status
- [ ] A test search queue runs without errors

---

## Troubleshooting

- **Container won't start:** check `docker compose logs` for errors.
- **Cannot connect to Sonarr/Radarr:** verify the URL and API key in the
  instance settings. If running in Docker, use the host IP (not `localhost`).
- **Lost encryption keys:** there is no recovery path. Restore keys from your
  backup or start fresh with a new database.

For more help, see the [Troubleshooting Guide](../how-to-guides/troubleshoot.md)
or open an issue on GitHub.
