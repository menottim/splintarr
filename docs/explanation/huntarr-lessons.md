# Lessons from the Huntarr Security Incident

In February 2026, a [security review of Huntarr](https://github.com/rfsbraz/huntarr-security-review) revealed 21 vulnerabilities across the application, including 7 critical findings. The review documented unauthenticated API access to credentials, account takeover via 2FA enrollment, arbitrary file writes, hardcoded secrets, and other issues. The project's GitHub repository and subreddit were subsequently taken offline.

Splintarr occupies the same problem space (automated backlog searching for the *arr ecosystem) and was built with awareness of this incident. This document maps each Huntarr finding to how Splintarr handles the same concern.

For Splintarr's full security model, see the [Security Guide](security.md). For the technical architecture, see [Architecture](architecture.md).

---

## Finding-by-Finding Comparison

### Critical Findings

**Huntarr #1: Unauthenticated Settings Write & Credential Disclosure**
Huntarr's `POST /api/settings/general` had no authentication. A single unauthenticated call could modify settings and the response returned API keys for every connected *arr application in cleartext.

*Splintarr:* Every API endpoint that writes data requires a valid JWT access token via httpOnly cookie (`Depends(get_current_user_from_cookie)`). There are no auth bypass lists or path-based skipping. The only unauthenticated endpoint is `GET /health`, which returns `{"status": "healthy"}` and nothing else. API keys are never included in any API response. They are Fernet-encrypted in the database and the encryption key is derived via HKDF from a secret stored outside the database.

**Huntarr #2: Unauthenticated Plex Account Linking (client-controlled `setup_mode`)**
A client-supplied `setup_mode` flag bypassed authentication, allowing attackers to link their own Plex tokens to the owner account.

*Splintarr:* There is no Plex integration and no client-controlled flags that bypass authentication. The setup wizard is gated by a server-side check: `db.query(User).count() == 0`. Once any user exists, registration is disabled. A post-commit race condition check was added in v1.3.1 to catch concurrent registration attempts.

**Huntarr #3: Unauthenticated Plex Unlink**
`POST /api/auth/plex/unlink` had no auth and defaulted to modifying the first user.

*Splintarr:* No Plex integration exists. All user-modifying endpoints (password change, 2FA setup/disable) require the authenticated user's current credentials.

**Huntarr #4: Unauthenticated 2FA Enrollment**
Substring matching in the auth bypass whitelist (`'/api/user/2fa/' in request.path`) let unauthenticated callers retrieve TOTP secrets and enroll 2FA on the owner account.

*Splintarr:* 2FA setup (`POST /api/auth/2fa/setup`) requires an authenticated session. The TOTP secret is Fernet-encrypted before storage. 2FA verification uses `hmac.compare_digest()` for constant-time comparison and tracks `last_used_counter` to prevent replay. There is no auth bypass whitelist and no substring-based path matching.

**Huntarr #5: Unauthenticated Recovery Key Generation**
A client-supplied `setup_mode` parameter bypassed password verification, letting attackers generate recovery keys.

*Splintarr:* There is no recovery key mechanism. Password reset requires CLI access to the Docker container (`docker exec splintarr splintarr reset-password`). This is intentional: if you can exec into the container, you already have host access.

**Huntarr #6: Zip Slip Arbitrary File Write**
Backup upload used `zipfile.extractall()` without filename sanitization. Combined with running as root, this allowed writing files anywhere on the filesystem.

*Splintarr:* There are no file upload endpoints. Config import accepts JSON via `POST` body (not file upload), validates the JSON structure, and applies changes through the ORM. A 1MB content-length limit prevents oversized payloads. The container runs as a non-root user (UID 1000) with a read-only filesystem and all capabilities dropped.

**Huntarr #7: Unauthenticated Setup Clear**
`POST /api/setup/clear` had no auth, letting attackers re-arm the setup flow and create a new owner account.

*Splintarr:* There is no setup clear or reset endpoint. The setup wizard is a one-time flow controlled by `User.count() == 0`. Once the first user is created, setup cannot be re-entered through the UI or API.

---

### High Findings

**Huntarr #8: Spoofable X-Forwarded-For in Local Access Bypass**
Huntarr trusted `X-Forwarded-For` headers to determine if a request was local, allowing remote attackers to spoof localhost.

*Splintarr:* `X-Forwarded-For` is only trusted when `ENVIRONMENT=production` (where a reverse proxy is expected). In development and Docker default mode, `request.client.host` is used directly. There is no "local access bypass" feature. Rate limiting uses the same IP extraction logic.

**Huntarr #9: World-Writable Windows Service Permissions**
Installation scripts granted `Everyone:(OI)(CI)F` on service directories.

*Splintarr:* There is no Windows service installer. The application runs in Docker. Database and secret files are set to `0600` permissions (owner read/write only) by the application at startup.

**Huntarr #10: Hardcoded External API Credentials**
TMDB API keys and Trakt client credentials were hardcoded across multiple source files.

*Splintarr:* There are zero hardcoded credentials in the codebase. All secrets (JWT key, database encryption key, password pepper) are loaded from Docker secret files or environment variables at runtime, with a minimum length of 32 characters enforced. A `grep` for `api_key = "`, `client_id = "`, `secret = "` across the entire codebase returns no results.

**Huntarr #11: Full Credential Exposure in Settings Response**
Settings responses returned API keys and credentials for all integrated *arr applications.

*Splintarr:* API keys are never returned in any response. The `InstanceResponse` schema does not include an `api_key` field. Config export replaces keys with `[REDACTED]`. Encrypted API keys exist only in the database and are decrypted only when making requests to *arr instances.

**Huntarr #12: Path Traversal in Backup Operations**
User-supplied `backup_id` went directly into filesystem paths, and `shutil.rmtree()` was called without validation.

*Splintarr:* There are no backup management API endpoints. Backups are handled by shell scripts (`scripts/backup.sh`) run by the host operator, not by the web application. Config import/export uses JSON through the ORM, not filesystem operations.

**Huntarr #13: Overly Broad Auth Bypass Patterns**
Auth used substring matching (`in request.path`) and suffix matching (`endswith`) to whitelist paths, inadvertently skipping auth on unintended routes.

*Splintarr:* There is no auth bypass whitelist. FastAPI's dependency injection (`Depends(get_current_user_from_cookie)`) is applied per-route. Each endpoint explicitly declares whether it requires authentication. Missing the dependency would result in the route having no access to user context, which would cause a runtime error.

---

### Medium Findings

**Huntarr #14: Weak Password Hashing (SHA-256)**
Passwords were hashed with salted SHA-256, which is not memory-hard and is vulnerable to GPU-accelerated offline cracking.

*Splintarr:* Passwords are hashed with Argon2id (time_cost=3, memory_cost=128 MiB, parallelism=8, hash_len=256-bit, salt_len=128-bit). A global pepper is mixed via HMAC-SHA256 before hashing. These parameters exceed [OWASP recommendations](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Dummy hash verification runs for invalid usernames to prevent timing-based enumeration.

**Huntarr #15: Low Recovery Key Entropy & Spoofable Rate Limiting**
Recovery keys used low-entropy word+digits format. Rate limiting trusted spoofable IP headers.

*Splintarr:* No recovery keys exist (see #5 above). Rate limiting uses `request.client.host` in non-production environments, preventing header spoofing. In production (behind a reverse proxy), `X-Forwarded-For` is trusted as expected.

**Huntarr #16: Missing Network Timeouts**
Outbound HTTP calls lacked explicit timeouts, risking thread starvation.

*Splintarr:* All outbound HTTP calls through `httpx` use explicit timeouts (default 30 seconds, configurable per instance). Discord notifications use a 10-second timeout. The `API_REQUEST_TIMEOUT` setting is bounded between 5 and 120 seconds.

**Huntarr #17: Unsafe XML Parsing**
Untrusted XML parsed with `ElementTree.fromstring()` without defusedxml.

*Splintarr:* There is no XML parsing in the codebase. The *arr APIs return JSON. All external communication uses `httpx` with JSON deserialization.

**Huntarr #18: Flask Dependency Vulnerability (CVE-2026-27205)**
Outdated Flask version with a known CVE.

*Splintarr:* Built on FastAPI (not Flask). Dependencies are locked via `poetry.lock` with SHA256 hash verification. Starlette is pinned above `>=0.49.1` to address CVE-2025-62727 and CVE-2025-54121. `pip-audit` and `safety` are included as development dependencies for vulnerability scanning.

---

### OSS Best-Practice Findings

**Huntarr #19: CI/CD Action Pinning & Governance Gaps**
No `dependabot.yml`, no `SECURITY.md`, GitHub Actions pinned to major version tags.

*Splintarr:* A [`SECURITY.md`](https://github.com/menottim/splintarr/blob/main/SECURITY.md) documents the vulnerability disclosure policy, scope, and response timeline. GitHub Security Advisories are enabled and actively used (4 advisories published and resolved as of v1.3.1). Security linting (Bandit, Ruff security rules) and type checking (strict mypy) are part of the development workflow.

**Huntarr #20: Container Runs as Root by Default**
Dockerfile set `PUID=0` and `PGID=0` with no non-root `USER` directive.

*Splintarr:* The Dockerfile creates `appuser` (UID 1000, GID 1000) with `/sbin/nologin` shell. The entrypoint drops privileges to `appuser` via `gosu` before starting the application. The container runs with `read_only: true`, `cap_drop: ALL`, `cap_add: [SETUID, SETGID]`, and `security_opt: no-new-privileges:true`. Verified: PID 1 runs as UID 1000 with `CapEff: 0x0` (all capabilities dropped).

---

## Process Differences

The Huntarr security review noted that the root cause wasn't just the 21 specific findings but the development process: no code review, no PR process, no automated testing, no security awareness in the development workflow.

Splintarr's process:

- **Security policy**: [`SECURITY.md`](https://github.com/menottim/splintarr/blob/main/SECURITY.md) with GitHub Security Advisories for private disclosure
- **Security testing**: Dedicated security test suite (`tests/security/`) covering OWASP Top 10 categories, plus SSRF blocklist tests
- **Security reviews**: Seven rounds of review including SAST (Bandit), manual code audit, and active penetration testing. All findings documented in [`docs/explanation/security.md`](security.md)
- **Accepted risks**: Five known limitations [documented with GitHub issue tracking](security.md#known-limitations-and-accepted-risks) rather than ignored
- **Code scanning**: GitHub CodeQL enabled, all alerts triaged (0 open)
- **Dependency management**: `poetry.lock` with hash verification, Starlette pinned above known CVEs

This is still AI-generated code maintained by one person. It has not been professionally audited by an external security firm. The difference is that security was treated as a first-class concern throughout development, not an afterthought.

---

## References

- [Huntarr Security Review](https://github.com/rfsbraz/huntarr-security-review) by rfsbraz
- [Splintarr Security Guide](security.md)
- [Splintarr Architecture](architecture.md)
- [Splintarr Known Limitations](security.md#known-limitations-and-accepted-risks)
- [Splintarr Security Advisories](https://github.com/menottim/splintarr/security/advisories)
