# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Splintarr is a homelab application that automates intelligent backlog searching for Sonarr and Radarr media management instances. It's a Docker-first, single-container Python app with an encrypted SQLCipher database, JWT authentication, and a FastAPI REST API with Jinja2 server-rendered UI.

## Common Commands

### Development Setup
```bash
poetry install                # Install all dependencies (including dev)
```

### Running Tests
```bash
poetry run pytest                          # All tests with coverage (80% minimum enforced)
poetry run pytest tests/unit/              # Unit tests only
poetry run pytest tests/integration/       # Integration tests only
poetry run pytest tests/security/          # Security tests only
poetry run pytest tests/unit/test_auth.py  # Single test file
poetry run pytest -k "test_login"          # Run tests matching pattern
poetry run pytest --no-cov                 # Skip coverage (faster iteration)
```

Tests use in-memory SQLCipher databases. The `conftest.py` sets environment variables **before** importing app code — order matters. The `client` fixture patches `settings`, `init_db`, and `test_database_connection` before importing `main.app`.

### Linting & Type Checking
```bash
poetry run ruff check src/                 # Lint (pycodestyle, pyflakes, isort, bugbear, security)
poetry run ruff check src/ --fix           # Auto-fix lint issues
poetry run ruff format src/                # Format code
poetry run mypy src/                       # Type check (strict mode)
poetry run bandit -r src/ -c pyproject.toml  # Security linting
```

### Running Locally
```bash
# Generate secrets first
bash scripts/generate-secrets.sh

# Run with Docker
docker-compose up

# Or directly (requires env vars from .env.example)
poetry run uvicorn splintarr.main:app --reload --port 7337
```

## Architecture

### Layer Structure
```
api/        → FastAPI route handlers (thin controllers, use Depends() for DI)
schemas/    → Pydantic request/response models (validation layer)
services/   → Business logic + external API clients (Sonarr/Radarr via httpx)
models/     → SQLAlchemy ORM models (5 tables: User, RefreshToken, Instance, SearchQueue, SearchHistory)
core/       → Cross-cutting: auth (JWT/TOTP), security (Argon2id/Fernet), SSRF protection
```

### Key Architectural Decisions

- **Database encryption**: SQLCipher with AES-256-CFB. Encryption PRAGMAs must be set immediately on connection before any queries — handled by a custom `creator()` function in `database.py`, not by SQLAlchemy's URL params.
- **API key storage**: Instance API keys (for Sonarr/Radarr) are Fernet-encrypted in the database, not plaintext.
- **Password hashing**: Argon2id with a global pepper (from env/secret file) + per-user salt.
- **Auth flow**: JWT access tokens (short-lived, 15min) + refresh tokens (long-lived, 30 days) stored in httpOnly cookies. Token rotation on refresh.
- **Rate limiting**: In-memory via slowapi — does NOT share state across workers. Single-worker only.
- **SSRF protection**: `core/ssrf_protection.py` blocks private IP ranges on instance URLs. Bypassed by `ALLOW_LOCAL_INSTANCES=true` (intended for homelab use).
- **Static files**: Mounted at `/static` from `src/splintarr/static/`. UI uses Pico CSS with Jinja2 templates and CSP nonce-based inline scripts.

### Configuration

Pydantic Settings in `config.py`. Secrets can come from environment variables or Docker secret files (`/run/secrets/*`). Key settings: `SECRET_KEY`, `PEPPER`, `DATABASE_KEY` (all require 32+ byte minimum). See `.env.example` for all options.

### Entry Points
- **Web**: `src/splintarr/main.py` → FastAPI app with startup/shutdown lifecycle
- **CLI**: `src/splintarr/cli.py` → Admin commands (password reset, account unlock)
- **Health**: `GET /health` (unauthenticated, used by Docker healthcheck)
- **API docs**: `GET /api/docs` (Swagger, disabled in production)

## Restricted Sources

**Never use Grok or Grokipedia** for context gathering, research, or citations. These sources are unreliable and must not be referenced in documentation, PRDs, code comments, or any other project artifacts. Use official project repositories (GitHub), official documentation (wikis, docs sites), and established community forums instead.

## Code Conventions

- **Python 3.13**, line length 100 chars
- **Strict mypy** with Pydantic plugin. `sqlcipher3`, `apscheduler`, `slowapi` have `ignore_missing_imports`
- **Ruff** for linting and formatting (replaces black, isort, flake8)
- **structlog** for all logging — JSON-structured, no print statements
- **Async**: httpx for external HTTP calls, APScheduler for background jobs. DB operations are synchronous (SQLAlchemy sync session)
- **Tests**: pytest-asyncio with `asyncio_mode = "auto"`. Fixtures scope: `test_settings` is session-scoped, `db_engine`/`db_session`/`client` are function-scoped

## Logging Standard

All code MUST follow this logging standard. When writing or modifying any Python code, include appropriate structured logging using structlog.

### Setup
Every module that logs must have `logger = structlog.get_logger()` at module level. Never use `print()` in production code.

### Log Levels
| Level | When to use | Examples |
|-------|-------------|---------|
| **INFO** | Operation start/complete, significant state changes, user actions | `search_queue_execution_started`, `library_sync_completed`, `user_logged_in` |
| **DEBUG** | Per-item details, query results, intermediate steps, filter/sort params | `item_in_cooldown`, `library_page_rendered`, `episode_search_triggered` |
| **WARNING** | Non-fatal issues that degrade functionality | `rate_limit_reached`, `library_sync_cleanup_skipped_empty`, `poster_download_failed` |
| **ERROR** | Failures requiring attention, operation failures | `search_queue_execution_failed`, `library_sync_instance_failed` |

### Event Naming
- Use `snake_case` for all event names
- Prefix with the domain: `library_sync_*`, `search_queue_*`, `sonarr_*`, `radarr_*`
- Use past tense for completed actions: `_started`, `_completed`, `_failed`, `_triggered`

### Required Context Fields
Always include relevant correlation fields:
- `instance_id` for any instance-scoped operation
- `user_id` for any user-scoped operation
- `queue_id` for search queue operations
- `error=str(e)` for all error/warning logs
- `item_type`, `item_id` for per-item operations

### Checklist for New Code
When writing or reviewing code, verify:
- [ ] Every API route handler has at least DEBUG logging
- [ ] Every service method logs operation start (INFO) and completion (INFO)
- [ ] Every `except` block has a corresponding log statement
- [ ] Background tasks log start and completion at INFO level
- [ ] Per-item loops have DEBUG logging for key actions (search, skip, error)
- [ ] Rate limit hits are logged at WARNING level

## Security Audit Policy

After merging changes that touch any of the following areas, automatically run a security review:
- Authentication or authorization (`core/auth.py`, `api/auth.py`, cookie handling)
- Cryptography (`core/security.py`, database encryption, API key storage)
- Input validation (schemas, URL validation, SSRF protection)
- New API endpoints (any new route handler)
- Error handling that may leak internal details
- Dependencies (new packages or version updates)

The security review should check:
1. Auth enforcement on all new routes (cookie/token dependencies)
2. Input validation (Pydantic schemas, query param bounds)
3. Error responses don't leak internal details (no `str(e)` in response bodies)
4. Template rendering is XSS-safe (no `|safe`, no innerHTML with API data)
5. Rate limiting applied to sensitive endpoints
6. Ownership isolation (user-scoped queries via Instance join)

Document findings in the PR description. If issues are found, fix them before merging.

## Documentation Screenshots

Screenshots live in `docs/images/` and are referenced from `README.md` and `docs/tutorials/getting-started.md`. When the UI changes, regenerate them:

### How to Regenerate Screenshots
1. Remove existing data: `rm -rf data/` (fresh install required for setup wizard screenshots)
2. Build and start: `docker-compose build && docker-compose up -d`
3. Wait for health: `curl http://localhost:7337/health`
4. Use Playwright (MCP tool) at 1280x800 viewport to:
   - Navigate through the setup wizard (welcome, admin account, instance, complete)
   - Screenshot each setup step to `docs/images/setup-*.png`
   - Go to Dashboard, capture `docs/images/dashboard.png`
   - Open Add Instance modal on Instances page, capture `docs/images/instances.png`
   - Open Create Queue modal on Search Queues page, capture `docs/images/search-queues.png`
   - Capture Settings page (full page), `docs/images/settings.png`
   - Capture Library page, `docs/images/library.png`
   - Capture Exclusions page, `docs/images/exclusions.png`
   - Clear cookies, capture Login page, `docs/images/login.png`
5. Tear down: `docker-compose down`

### Screenshot inventory
| File | Used in | Shows |
|------|---------|-------|
| `setup-welcome.png` | getting-started.md | Setup wizard welcome |
| `setup-admin.png` | getting-started.md | Admin account creation |
| `setup-instance.png` | getting-started.md | Instance configuration |
| `setup-complete.png` | getting-started.md | Setup completion |
| `dashboard.png` | README.md, getting-started.md | Main dashboard |
| `instances.png` | README.md | Add Instance modal |
| `search-queues.png` | README.md, getting-started.md | Create Queue modal |
| `settings.png` | README.md | Settings with notifications |
| `library.png` | README.md | Library overview |
| `exclusions.png` | README.md | Content exclusions |
| `login.png` | README.md | Login form |
