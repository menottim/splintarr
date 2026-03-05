# Security Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 4 Medium security advisories (GHSA-x58h, GHSA-9wq6, GHSA-j98q, GHSA-g27f) and 7 Low/Info findings from issue #127.

**Architecture:** Each fix is isolated — no cross-dependencies. Fixes are ordered by severity (Medium first) then by complexity (simplest first). Each task includes a test to verify the fix.

**Tech Stack:** Python 3.13, FastAPI, Docker, pytest

---

## Task 1: VULN-01 — Drop to appuser via gosu in entrypoint (GHSA-x58h-pwmm-vfpf)

**Files:**
- Modify: `docker/entrypoint.sh:60-61`

**Step 1: Fix the entrypoint**

In `docker/entrypoint.sh`, change lines 60-61 from:

```bash
log "Starting application as root..."
exec "$@"
```

To:

```bash
log "Dropping privileges to appuser..."
exec gosu appuser "$@"
```

**Step 2: Verify the fix**

```bash
rm -rf data/ && docker-compose build && docker-compose up -d
sleep 5
docker exec splintarr whoami
# Expected: appuser (NOT root)
docker exec splintarr id
# Expected: uid=1000(appuser) gid=1000(appuser)
curl -s http://localhost:7337/health
# Expected: {"status":"healthy",...}
docker-compose down
```

**Step 3: Commit**

```bash
git add docker/entrypoint.sh
git commit -m "security: drop to appuser via gosu in entrypoint (GHSA-x58h-pwmm-vfpf)

Fixes container running as root. The gosu binary was already installed
but never invoked. Now exec's as appuser (UID 1000) before starting
the application."
```

---

## Task 2: VULN-02 — Split SSRF blocklist so allow_local doesn't bypass cloud metadata (GHSA-9wq6-96r6-j6p6)

**Files:**
- Modify: `src/splintarr/core/ssrf_protection.py:21-44,126-140`
- Test: `tests/unit/test_ssrf_protection.py` (add new test cases)

**Step 1: Write failing tests**

Add to `tests/unit/test_ssrf_protection.py`:

```python
def test_cloud_metadata_blocked_even_with_allow_local(self):
    """VULN-02: allow_local must NOT bypass cloud metadata blocking."""
    with pytest.raises(SSRFError, match="blocked"):
        validate_instance_url("http://169.254.169.254/latest/", allow_local=True)

def test_multicast_blocked_even_with_allow_local(self):
    """Multicast should always be blocked regardless of allow_local."""
    with pytest.raises(SSRFError, match="blocked"):
        validate_instance_url("http://224.0.0.1/", allow_local=True)

def test_private_ip_allowed_with_allow_local(self):
    """Private IPs should be allowed when allow_local=True."""
    # This should NOT raise (192.168.x.x is a local network)
    # It will fail connection but should pass SSRF validation
    try:
        validate_instance_url("http://192.168.1.1:8989", allow_local=True)
    except SSRFError:
        pytest.fail("Private IP should be allowed with allow_local=True")
    except Exception:
        pass  # Connection errors are fine, we just test SSRF validation
```

**Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/unit/test_ssrf_protection.py -k "cloud_metadata_blocked_even" -v --no-cov
# Expected: FAIL — currently allow_local skips ALL checks
```

**Step 3: Implement the fix**

In `src/splintarr/core/ssrf_protection.py`, split `BLOCKED_NETWORKS` into two lists:

```python
# Networks that are ALWAYS blocked regardless of allow_local.
# These are dangerous even in homelab contexts (cloud metadata, multicast, reserved).
ALWAYS_BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / AWS metadata
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved
    ipaddress.ip_network("255.255.255.255/32"), # Broadcast
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("100.64.0.0/10"),      # Shared address space (CGN)
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("198.18.0.0/15"),      # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("fe80::/10"),           # IPv6 Link-local
    ipaddress.ip_network("ff00::/8"),            # IPv6 Multicast
]

# Networks blocked by default but allowed when allow_local=True (homelab mode).
LOCAL_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Private (Class A)
    ipaddress.ip_network("172.16.0.0/12"),      # Private (Class B)
    ipaddress.ip_network("192.168.0.0/16"),     # Private (Class C)
    ipaddress.ip_network("::1/128"),             # IPv6 Loopback
    ipaddress.ip_network("::ffff:0:0/96"),       # IPv6 IPv4-mapped
    ipaddress.ip_network("fc00::/7"),            # IPv6 ULA
]

# Combined for backward compatibility
BLOCKED_NETWORKS = ALWAYS_BLOCKED_NETWORKS + LOCAL_NETWORKS
```

Then change the check at line ~126 from:

```python
        if not allow_local:
            for network in BLOCKED_NETWORKS:
                if ip in network:
```

To:

```python
        # Always check dangerous networks (cloud metadata, multicast, reserved)
        for network in ALWAYS_BLOCKED_NETWORKS:
            if ip in network:
                logger.warning(
                    "ssrf_blocked",
                    url=url,
                    hostname=hostname,
                    ip=str(ip),
                    blocked_network=str(network),
                )
                raise SSRFError(
                    f"URL resolves to blocked network: {network}. "
                    f"This network is always blocked for security reasons."
                )

        # Check local/private networks (skipped when allow_local=True)
        if not allow_local:
            for network in LOCAL_NETWORKS:
                if ip in network:
                    logger.warning(
                        "ssrf_blocked",
                        url=url,
                        hostname=hostname,
                        ip=str(ip),
                        blocked_network=str(network),
                    )
                    raise SSRFError(
                        f"URL resolves to blocked network: {network}. "
                        f"Private IPs are not allowed for security reasons."
                    )
```

**Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/unit/test_ssrf_protection.py -v --no-cov
# Expected: ALL PASS including the new tests
```

**Step 5: Commit**

```bash
git add src/splintarr/core/ssrf_protection.py tests/unit/test_ssrf_protection.py
git commit -m "security: split SSRF blocklist — cloud metadata always blocked (GHSA-9wq6-96r6-j6p6)

Split BLOCKED_NETWORKS into ALWAYS_BLOCKED_NETWORKS (cloud metadata,
multicast, reserved — never bypassed) and LOCAL_NETWORKS (private IPs —
bypassed by allow_local=True for homelab use). Previously allow_local
skipped ALL checks including cloud metadata endpoints."
```

---

## Task 3: VULN-03 — Strip input from validation error responses (GHSA-j98q-225j-p8cf)

**Files:**
- Modify: `src/splintarr/main.py:444-449`
- Test: `tests/unit/test_main.py` or `tests/integration/` (add validation error test)

**Step 1: Write failing test**

Add a test that sends a malformed login request and checks that the password is NOT in the response:

```python
def test_validation_error_does_not_leak_password(client):
    """VULN-03: Validation errors must not include raw input values."""
    response = client.post(
        "/api/auth/login",
        json={"username": 123, "password": "SuperSecretPassword123!"},
    )
    assert response.status_code == 422
    body = response.text
    assert "SuperSecretPassword123!" not in body
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/ -k "validation_error_does_not_leak" -v --no-cov
# Expected: FAIL — password currently appears in response
```

**Step 3: Implement the fix**

In `src/splintarr/main.py`, change the validation error handler (lines ~444-449) from:

```python
    errors = []
    for error in exc.errors():
        sanitized = {k: _sanitize_for_json(v) for k, v in error.items()}
        errors.append(sanitized)
```

To:

```python
    errors = []
    for error in exc.errors():
        # Strip 'input' key to prevent leaking sensitive values (passwords, API keys)
        sanitized = {
            k: _sanitize_for_json(v)
            for k, v in error.items()
            if k != "input"
        }
        errors.append(sanitized)
```

Also strip it from the logger call above (line ~442):

```python
    # Sanitize errors for logging too — remove input values
    safe_errors = [
        {k: v for k, v in e.items() if k != "input"}
        for e in exc.errors()
    ]
    logger.warning(
        "http_validation_error",
        path=request.url.path,
        method=request.method,
        errors=safe_errors,
    )
```

**Step 4: Run test**

```bash
.venv/bin/python -m pytest tests/ -k "validation_error_does_not_leak" -v --no-cov
# Expected: PASS
```

**Step 5: Commit**

```bash
git add src/splintarr/main.py tests/
git commit -m "security: strip input values from validation error responses (GHSA-j98q-225j-p8cf)

Remove 'input' key from Pydantic validation error responses and logs.
Previously, malformed login/register requests would include the raw
password in the 422 response body."
```

---

## Task 4: VULN-04 — Add WebSocket Origin header validation (GHSA-g27f-2vx9-gvhr)

**Files:**
- Modify: `src/splintarr/api/ws.py:22-28`
- Test: `tests/unit/test_ws.py` or `tests/integration/` (add origin test)

**Step 1: Implement the fix**

In `src/splintarr/api/ws.py`, add Origin validation after the token check and before `ws_manager.connect()`. Insert before the `await ws_manager.connect(websocket)` line:

```python
    # Validate Origin header to prevent Cross-Site WebSocket Hijacking (CSWSH)
    origin = websocket.headers.get("origin", "")
    if origin:
        allowed_origins = settings.cors_origins if settings.cors_origins else []
        # Also allow requests from the app's own host
        host = websocket.headers.get("host", "")
        local_origins = [f"http://{host}", f"https://{host}"]
        all_allowed = list(allowed_origins) + local_origins
        if origin not in all_allowed:
            logger.warning(
                "websocket_origin_rejected",
                origin=origin,
                allowed=all_allowed,
            )
            await websocket.close(code=4003, reason="Origin not allowed")
            return
```

**Step 2: Verify manually**

The WebSocket origin check is hard to unit test without a full ASGI test client. Verify via code review that:
- Origin header is checked before accepting the connection
- Empty origin (same-origin requests) is allowed
- Mismatched origin closes with 4003

**Step 3: Commit**

```bash
git add src/splintarr/api/ws.py
git commit -m "security: add WebSocket Origin header validation (GHSA-g27f-2vx9-gvhr)

Validate the Origin header on WebSocket upgrade to prevent Cross-Site
WebSocket Hijacking. Rejects connections from origins not in
cors_origins or the app's own host. Empty origin (same-origin) allowed."
```

---

## Task 5: VULN-05 — Enable Docker read_only and cap_drop with Windows override

**Files:**
- Modify: `docker-compose.yml:22-35`
- Create: `docker-compose.override.windows.yml`

**Step 1: Uncomment security directives in docker-compose.yml**

Change lines 22-35 from commented-out to active:

```yaml
    # Security: Read-only root filesystem
    read_only: true

    # Security: Drop all capabilities, add back only what's needed
    cap_drop:
      - ALL
    cap_add:
      - SETUID
      - SETGID
```

**Step 2: Create Windows override file**

Create `docker-compose.override.windows.yml`:

```yaml
# Windows override: disable read_only and cap_drop for compatibility.
# Usage: docker-compose -f docker-compose.yml -f docker-compose.override.windows.yml up -d
services:
  splintarr:
    read_only: false
    cap_drop: []
    cap_add: []
```

**Step 3: Verify the fix**

```bash
rm -rf data/ && docker-compose build && docker-compose up -d
sleep 5
# Verify read-only filesystem
docker exec splintarr touch /app/test-write 2>&1
# Expected: touch: cannot touch '/app/test-write': Read-only file system
# Verify data dir still writable
docker exec splintarr touch /data/test-write 2>&1
# Expected: success (no error)
docker exec splintarr rm /data/test-write
curl -s http://localhost:7337/health
# Expected: {"status":"healthy",...}
docker-compose down
```

**Step 4: Commit**

```bash
git add docker-compose.yml docker-compose.override.windows.yml
git commit -m "security: enable read_only filesystem and cap_drop in Docker

Uncommented read_only: true and cap_drop: ALL in docker-compose.yml.
Added docker-compose.override.windows.yml for Windows compatibility.
Resolves VULN-05 from security assessment."
```

---

## Task 6: VULN-06 — Log warning on decrypt failure instead of silent return

**Files:**
- Modify: `src/splintarr/core/security.py:277-282`

**Step 1: Implement the fix**

Change the `decrypt_if_needed()` except block from:

```python
        except EncryptionError:
            # If decryption fails, return original value
            # This handles legacy data that wasn't encrypted
            return value
```

To:

```python
        except EncryptionError:
            # Decryption failed — likely a key rotation or corruption issue.
            # Log warning so operators can detect the problem.
            logger.warning(
                "decryption_failed_returning_original",
                value_prefix=value[:10] + "..." if len(value) > 10 else value,
            )
            return value
```

**Step 2: Commit**

```bash
git add src/splintarr/core/security.py
git commit -m "security: log warning on decrypt failure instead of silent return

decrypt_if_needed() now logs a WARNING when decryption fails, making
key rotation problems visible. Previously returned ciphertext silently.
Resolves VULN-06 from security assessment."
```

---

## Task 7: VULN-07 — Add WebSocket connection limit

**Files:**
- Modify: `src/splintarr/core/websocket.py:36-43`

**Step 1: Implement the fix**

Add a `MAX_CONNECTIONS` constant and a check in `connect()`:

```python
MAX_WEBSOCKET_CONNECTIONS = 50

class WebSocketManager:
    ...
    async def connect(self, websocket: WebSocket) -> None:
        if len(self.active_connections) >= MAX_WEBSOCKET_CONNECTIONS:
            logger.warning(
                "websocket_connection_limit_reached",
                limit=MAX_WEBSOCKET_CONNECTIONS,
                current=len(self.active_connections),
            )
            await websocket.close(code=4008, reason="Connection limit reached")
            return
        await websocket.accept()
        self.active_connections.append(websocket)
        ...
```

**Step 2: Commit**

```bash
git add src/splintarr/core/websocket.py
git commit -m "security: add WebSocket connection limit of 50

Reject new WebSocket connections when 50 are already active.
Prevents memory exhaustion via connection flooding.
Resolves VULN-07 from security assessment."
```

---

## Task 8: VULN-09 — Add content-length check on config import

**Files:**
- Modify: `src/splintarr/api/config.py:204-205,247-248`

**Step 1: Implement the fix**

Add a size check before `request.json()` in both `import_preview` and `import_apply`:

```python
    # Reject oversized payloads (max 1MB)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 1_048_576:
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body too large. Maximum 1MB."},
        )
```

Add this before the `body = await request.json()` line in both endpoints.

**Step 2: Commit**

```bash
git add src/splintarr/api/config.py
git commit -m "security: add 1MB size limit on config import payloads

Reject config import requests with Content-Length > 1MB before parsing.
Prevents memory exhaustion via large JSON payloads.
Resolves VULN-09 from security assessment."
```

---

## Task 9: VULN-10 — Add post-commit user count check to API registration

**Files:**
- Modify: `src/splintarr/api/auth.py:235-237`

**Step 1: Implement the fix**

After the `db.commit()` on line 236, add the same post-commit check that exists in `api/dashboard.py`:

```python
        db.add(user)
        db.commit()

        # Post-commit race condition check: if another request created a user
        # between our count check and commit, roll back.
        final_count = db.query(User).count()
        if final_count > 1:
            logger.warning(
                "registration_race_detected",
                username=user.username,
                user_count=final_count,
            )
            db.delete(user)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is disabled. Users already exist.",
            )

        db.refresh(user)
```

**Step 2: Commit**

```bash
git add src/splintarr/api/auth.py
git commit -m "security: add post-commit race check to API registration

Adds user count verification after commit to detect concurrent
registration race conditions. Mirrors the existing check in
the dashboard setup endpoint. Resolves VULN-10."
```

---

## Task 10: VULN-11 — Validate webhook URLs against SSRF blocklist

**Files:**
- Modify: `src/splintarr/services/config_import.py:271`

**Step 1: Implement the fix**

Replace the simple `startswith("https://")` check with SSRF validation:

```python
        if webhook_url:
            if not webhook_url.startswith("https://"):
                logger.warning("config_import_webhook_url_invalid", user_id=user_id)
                webhook_url = None
            else:
                # SSRF-validate the webhook URL (block cloud metadata, private IPs)
                try:
                    validate_instance_url(webhook_url, allow_local=False)
                except Exception as e:
                    logger.warning(
                        "config_import_webhook_url_ssrf_blocked",
                        user_id=user_id,
                        error=str(e),
                    )
                    webhook_url = None
```

Make sure `validate_instance_url` is imported at the top of the file.

**Step 2: Commit**

```bash
git add src/splintarr/services/config_import.py
git commit -m "security: SSRF-validate webhook URLs during config import

Webhook URLs now go through validate_instance_url() during config
import, blocking cloud metadata and private IPs. Previously only
checked for https:// prefix. Resolves VULN-11."
```

---

## Task 11: Final verification and Docker rebuild

**Step 1: Run linting**

```bash
.venv/bin/ruff check src/ --fix
.venv/bin/ruff format src/
```

**Step 2: Run tests**

```bash
.venv/bin/python -m pytest tests/unit/ tests/integration/ tests/security/ --no-cov -x
```

**Step 3: Docker smoke test**

```bash
rm -rf data/ && docker-compose build && docker-compose up -d
sleep 5
curl -s http://localhost:7337/health
docker exec splintarr whoami  # Should be: appuser
docker exec splintarr touch /app/test 2>&1  # Should fail: Read-only
docker-compose down
```

**Step 4: Final commit if any lint fixes**

```bash
git add -A
git commit -m "chore: lint fixes from security hardening"
```
