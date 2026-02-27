# Deploy with Docker

Here's how to get Splintarr running in Docker on your homelab.

---

## Prerequisites

- **Docker** 20.10+ and **Docker Compose** v2+ (or standalone 1.29+)
- **OS**: Linux, macOS, or Windows with WSL2
- **Hardware**: 1+ CPU cores, 512 MB RAM, 1 GB disk

Verify your install:

```bash
docker --version
docker compose version
```

If you need to install Docker, follow the official guide at
[https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/).

---

## Quick Start

**1. Clone the repository**

```bash
git clone https://github.com/menottim/splintarr.git
cd splintarr
```

**2. Generate secrets**

```bash
# Linux / macOS
./scripts/generate-secrets.sh

# Windows (PowerShell)
.\scripts\generate-secrets.ps1
```

**3. Start the container**

```bash
docker compose -f docker/docker-compose.yml up -d
```

**4. Open the browser**

Go to [http://localhost:7337](http://localhost:7337) and walk through the setup
wizard. You will create an admin account and connect your first Sonarr or Radarr
instance.

**5. Check that it is healthy**

```bash
docker compose -f docker/docker-compose.yml ps
```

The `STATUS` column should show `Up ... (healthy)` after about a minute.

---

## Building from Source

If you prefer to build the image yourself instead of using the Compose build:

```bash
docker build -t splintarr:latest -f docker/Dockerfile .
```

To tag with a version:

```bash
docker build \
  --build-arg VERSION=$(cat VERSION) \
  -t splintarr:$(cat VERSION) \
  -f docker/Dockerfile .
```

---

## Environment Configuration

The Compose file ships with sensible homelab defaults. The most useful variables
to customize are:

| Variable | Default | What it does |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | Set to `production` if you add HTTPS via reverse proxy |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `SESSION_EXPIRE_HOURS` | `24` | How long a login session lasts |
| `API_RATE_LIMIT` | `100/minute` | Request rate limit per client |
| `ALLOWED_ORIGINS` | `http://localhost:7337` | CORS origins (comma-separated) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Trusted hostnames (comma-separated) |
| `ALLOW_LOCAL_INSTANCES` | `true` | Allow connecting to Sonarr/Radarr on private IPs |

Override any of these by creating a `.env` file next to the Compose file or by
editing the `environment:` block in `docker/docker-compose.yml` directly.

For the full list of every variable (security, token lifetimes, database, etc.)
see the [Configuration Reference](../reference/configuration.md).

---

## Volume Management

The container stores persistent data in three locations:

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `data/` | `/data` | SQLite database and application data |
| `logs/` | `/app/logs` | Application log files |
| `secrets/` | `/run/secrets/` | Encryption keys (mounted read-only by Docker) |

These are bind-mounted from the project root so your data lives alongside your
Compose file and is easy to back up.

### Permissions

The default Compose file works out of the box on most systems. If you run into
permission errors on Linux, make sure the data and logs directories are owned by
UID 1000:

```bash
sudo chown -R 1000:1000 data/ logs/
```

---

## Secrets Management

The `generate-secrets.sh` script (step 2 of Quick Start) creates three files
under `secrets/`:

| File | Purpose |
|------|---------|
| `db_key.txt` | 256-bit AES key for SQLite encryption |
| `secret_key.txt` | 512-bit key for signing JWT tokens |
| `pepper.txt` | 256-bit pepper added to password hashes |

The script generates cryptographically secure random values, validates them,
and sets file permissions to `600` (owner-only).

Docker Compose mounts these as
[Docker secrets](https://docs.docker.com/compose/how-tos/use-secrets/)
at `/run/secrets/`. The application reads them via the `*_FILE` environment
variables (`DATABASE_KEY_FILE`, `SECRET_KEY_FILE`, `PEPPER_FILE`). You never
need to paste secret values into your `.env` or Compose file.

If you ever need to regenerate secrets, stop the container first, re-run the
script, then start it again. You will need to re-run the setup wizard because
the old database can no longer be decrypted.

---

## Health Checks

The Compose file includes a built-in health check that pings
`http://localhost:7337/health` every 30 seconds. Docker marks the container as
`healthy` once it responds successfully.

```bash
# Quick status
docker compose -f docker/docker-compose.yml ps

# Detailed health info
docker inspect splintarr | jq '.[0].State.Health'

# Manual check
curl -f http://localhost:7337/health
```

---

## Logging

### Application logs

The app writes structured log files with automatic rotation (10 MB per file,
5 backups kept):

- `logs/all.log` -- all messages at INFO and above
- `logs/error.log` -- errors and critical issues only
- `logs/debug.log` -- everything, when `LOG_LEVEL=DEBUG`

Sensitive data (passwords, API keys, tokens) is automatically redacted.

### Docker container logs

Container stdout/stderr is captured by Docker with the same rotation settings
(10 MB, 5 files):

```bash
# Follow live output
docker compose -f docker/docker-compose.yml logs -f

# Last 100 lines
docker compose -f docker/docker-compose.yml logs --tail=100
```

Set `LOG_LEVEL=DEBUG` in your environment to get verbose output when
troubleshooting, then set it back to `INFO` when you are done.

---

## Upgrading Containers

### Using the upgrade script

```bash
./scripts/upgrade.sh <version>
```

The script backs up your data, pulls the new image, restarts the container, and
verifies health. It rolls back automatically if the new version fails to start.

### Manual upgrade

```bash
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml pull   # or rebuild with: docker compose build
docker compose -f docker/docker-compose.yml up -d
```

Database migrations run automatically on startup.

---

## Backup and Restore

Quick backup:

```bash
./scripts/backup.sh
```

Quick restore:

```bash
./scripts/restore.sh backup-20260225.tar.gz
```

For detailed procedures, scheduling, and what is included in a backup, see the
[Backup and Restore Guide](./backup-and-restore.md).

---

## Troubleshooting

A few things to check first:

- **Container won't start** -- Run `docker compose logs` and look for error
  messages. The most common cause is missing secrets (`./scripts/generate-secrets.sh`).
- **Port conflict** -- Something else is using port 7337. Check with
  `lsof -i :7337` (Linux/macOS) and either stop the other process or change the
  port mapping in the Compose file.
- **Permission denied on volumes** -- Run `sudo chown -R 1000:1000 data/ logs/`.
- **Can't reach Sonarr/Radarr** -- The container binds to localhost by default.
  If your *arr apps are on another machine, make sure the container can reach
  them. Test with
  `docker exec splintarr curl -v http://<host>:<port>`.

For a full list of known issues and solutions, see the
[Troubleshooting Guide](./troubleshoot.md).

---

## Next Steps

- [Getting Started Tutorial](../tutorials/getting-started.md) -- walkthrough of
  initial setup after the container is running
- [Configuration Reference](../reference/configuration.md) -- every environment
  variable explained
- [Advanced Deployment](./deploy-production.md) -- reverse proxies, HTTPS,
  resource tuning, and other optional hardening
