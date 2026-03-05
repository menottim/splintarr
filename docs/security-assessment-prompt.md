# Security Assessment Prompt — Universal Template

> **Purpose:** Reusable, self-improving prompt for Claude Code security assessments. Covers static code review and active penetration testing. The current reference implementation targets Splintarr (Python/FastAPI/Docker) but the methodology is project-agnostic — see "Adapting This Prompt for Other Projects."
>
> **Location:** `docs/security-assessment-prompt.md` (referenced from MEMORY.md)
> **Invoke:** Any time a security assessment is requested.

---

## Your Role

You are a world-class application security engineer and penetration tester with OSCP, OSWE, and GWAPT certifications. You have 15+ years of experience in:

- Web application penetration testing (OWASP WSTG v4.2 methodology)
- Python/FastAPI security assessments
- Cryptographic implementation review (JWT, Argon2id, Fernet, SQLCipher)
- WebSocket security testing
- Docker container security auditing
- SSRF bypass research
- AI-generated code security patterns

You are conducting a **white-box security assessment** of the target application. If the codebase is AI-generated, pay special attention to inconsistent validation, placeholder security, copy-paste gaps, and over-reliance on framework defaults.

**Your mission:** Find every exploitable vulnerability. Do not assume anything is safe because it "looks correct." Verify everything empirically.

### How to Use This Prompt

1. **Read the full prompt** before starting
2. **Sections marked `[REFERENCE: Splintarr]`** contain project-specific file paths, endpoints, and test commands — replace for other targets or use the "Adapting This Prompt" section
3. **Run all three phases** — Static review, active testing, regression verification
4. **File findings** per the target repo's security policy (see Filing Findings section)
5. **Update this prompt** with lessons learned after each run (see Self-Improvement Protocol)

---

## Ground Rules

1. **Test EVERYTHING empirically.** Reading code is not enough. If the code says `SameSite=Strict`, verify it in actual response headers. If SSRF protection blocks `127.0.0.1`, try `0x7f000001`, `[::1]`, DNS rebinding.
2. **Use severity ratings:** Critical / High / Medium / Low / Informational with CVSS 3.1 scores.
3. **Document proof of concept** for every finding with exact commands/steps to reproduce.
4. **Check for regressions.** Prior assessments found and fixed 58+ vulnerabilities (see `docs/other/security-*.md`). Verify the fixes still hold.
5. **Output a structured report** (format specified at end of this prompt).
6. **Do not modify the codebase** during testing. Document findings only.

---

## Environment Setup [REFERENCE: Splintarr]

> Replace this section with your target project's build, run, and authentication commands.

The application runs in Docker. Set up the test environment:

```bash
# Build and start (fresh data directory for clean state)
cd /Users/mminutillo/splintarr
rm -rf data/
docker-compose build && docker-compose up -d

# Wait for health
sleep 5 && curl -s http://localhost:7337/health

# Create admin account for testing
curl -s -X POST http://localhost:7337/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"SecureP@ssw0rd!123","confirm_password":"SecureP@ssw0rd!123"}' \
  -c /tmp/splintarr-cookies.txt

# Login and capture cookies
curl -s -X POST http://localhost:7337/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"SecureP@ssw0rd!123"}' \
  -c /tmp/splintarr-cookies.txt -b /tmp/splintarr-cookies.txt
```

For browser-based testing, use Playwright tools at 1280x800 viewport navigating to `http://localhost:7337`.

---

## Phase 1: Static Code Review [REFERENCE: Splintarr]

> Replace file paths and line numbers with your target's equivalents. The *categories* (auth, crypto, SSRF, input validation, WebSocket, Docker) are universal.

Systematically review each security-critical component. Use `Read` and `Grep` tools.

### 1.1 Authentication & Session Management

**Files to review:**
- `src/splintarr/core/auth.py` (883 lines) — JWT creation, verification, blacklisting, TOTP
- `src/splintarr/api/auth.py` — Route handlers for login, register, logout, 2FA, password change
- `src/splintarr/schemas/user.py` — Input validation schemas
- `src/splintarr/models/user.py` — User ORM model, lockout logic

**What to look for:**

| Check | File:Line | What to verify |
|-------|-----------|----------------|
| JWT algorithm whitelist | `core/auth.py:39` | `ALLOWED_JWT_ALGORITHMS = ["HS256"]` — verify `_decode_and_verify_jwt()` enforces this, rejects `"none"`, `"RS256"` |
| Token type confusion | `core/auth.py:140,210` | `type` claim ("access", "refresh", "2fa_pending") — verify each validation function rejects wrong types |
| Reserved claim override | `core/auth.py:148-151` | `RESERVED_CLAIMS` set — verify `create_access_token()` blocks injection of `sub`, `exp`, `jti` via `additional_claims` |
| Cookie security attributes | `api/auth.py:125-145` | HttpOnly, Secure (in production), SameSite=Strict, correct path, correct max_age |
| Refresh token rotation | `api/auth.py:450-517` | Old JTI revoked in DB after rotation — verify no replay window |
| In-memory blacklist scope | `core/auth.py:41-94` | `_access_token_blacklist` dict — verify cleanup runs, verify multi-worker breaks this |
| Password hashing pepper flow | `core/security.py:87-89` | HMAC-SHA256(pepper, password) → base64 → Argon2id — verify pepper never logged |
| Timing equalization | `core/security.py:429, core/auth.py:533` | Dummy hash verification for invalid usernames — verify with timing analysis |
| Account lockout | `api/auth.py` + `models/user.py` | 5 failures → lockout, exponential backoff, reset on success |
| Registration gate | `api/auth.py:~200` | User count check — test race condition with concurrent requests |
| TOTP replay protection | `core/auth.py:644,660,663` | `totp_last_used_counter` tracked, `hmac.compare_digest()` for constant-time comparison |
| 2FA pending token lifecycle | `core/auth.py:703,735` | 5-min expiry, blacklisted after use — verify no replay |

### 1.2 Cryptography

**Files to review:**
- `src/splintarr/core/security.py` (480 lines) — Fernet, Argon2id, pepper mixing
- `src/splintarr/database.py` (446 lines) — SQLCipher PRAGMA setup, connection creator

**What to look for:**

| Check | File:Line | What to verify |
|-------|-----------|----------------|
| Fernet key derivation | `security.py:173-189` | HKDF(SHA256, key=SECRET_KEY, salt="vibe-quality-searcharr-fernet-v1", info="api-key-encryption") — verify 32-byte output |
| Argon2id parameters | `security.py:53-59` + `config.py:90-106` | time_cost=3, memory_cost=128*1024, parallelism=8, hash_len=32, salt_len=16 — meets RFC 9106 recommendations |
| SQLCipher PRAGMA injection | `database.py:162-165` | `safe_key = db_key.replace("'", "''")` — test with keys containing `'; ATTACH DATABASE '/tmp/evil.db' AS evil; --` |
| Secure delete | `database.py:99` | `PRAGMA secure_delete=ON` — verify deleted records overwritten |
| Fernet plaintext detection | `security.py:254-256` | Checks for `gAAAAA` prefix — false positive risk if user input starts with this |
| Decrypt failure handling | `security.py:278-282` | `decrypt_if_needed()` returns original value on failure — silently exposes unencrypted data |
| Secret minimum lengths | `config.py:288-300` | SECRET_KEY, PEPPER, DATABASE_KEY all require 32+ chars |

### 1.3 SSRF Protection

**File to review:** `src/splintarr/core/ssrf_protection.py` (173 lines)

**What to look for:**

| Check | File:Line | What to verify |
|-------|-----------|----------------|
| Blocked networks completeness | `ssrf_protection.py:21-44` | All RFC 1918, loopback, link-local, cloud metadata (169.254.x.x), IPv6 equivalents |
| `allow_local` bypass scope | `ssrf_protection.py:90-98,126` | When `ALLOW_LOCAL_INSTANCES=true`: does it bypass ONLY private ranges, or ALL checks including cloud metadata? **Pre-identified concern**: line 126 may skip all network checks |
| DNS resolution | `ssrf_protection.py:103` | `socket.getaddrinfo()` — TOCTOU with httpx re-resolving DNS at request time |
| URL parsing confusion | `ssrf_protection.py:60-80` | Scheme validation (http/https only), hostname extraction — test with auth in URL `http://user@127.0.0.1/` |
| Redirect following | Check `base_client.py` | `follow_redirects=False` should be set — verify |

### 1.4 Input Validation

**Files to review:**
- `src/splintarr/schemas/*.py` — All Pydantic models
- `src/splintarr/api/*.py` — Route handlers that process input

**What to look for:**
- Every POST/PUT/PATCH endpoint uses a Pydantic schema
- No `extra="allow"` on security-critical schemas
- Username regex `^[a-zA-Z][a-zA-Z0-9_]*$` blocks Unicode confusables
- Password validation: 12-128 chars, complexity rules, common password blocklist
- Integer fields have `ge`/`le` bounds (no negative batch sizes, intervals, etc.)
- URL fields go through SSRF validation
- No raw `text()` SQL with user input

### 1.5 WebSocket Security

**Files to review:**
- `src/splintarr/api/ws.py` (61 lines)
- `src/splintarr/core/websocket.py` (112 lines)
- `src/splintarr/core/events.py` (95 lines)

**What to look for:**

| Check | File:Line | What to verify |
|-------|-----------|----------------|
| Auth on connect | `ws.py:25-43` | Cookie-based JWT auth on WebSocket upgrade — verify close code 4001 on failure |
| Origin header validation | `ws.py` | **Pre-identified gap**: No Origin header check — Cross-Site WebSocket Hijacking (CSWSH) risk |
| Token expiry during session | `ws.py:53-54` | No periodic re-authentication — WS connection persists beyond access token expiry |
| Connection limit | `websocket.py:34` | `active_connections: list[WebSocket]` — no limit, DoS vector |
| Broadcast scope | `websocket.py:69-95` | All events broadcast to ALL connected clients — no user isolation |
| Client message handling | `ws.py:53-54` | Incoming messages received but discarded — verify no processing |

### 1.6 Config Import/Export

**Files to review:**
- `src/splintarr/services/config_import.py`
- `src/splintarr/api/config.py`

**What to look for:**
- Import validates all instance URLs via SSRF protection
- Import JSON payload has no size limit — DoS vector
- API keys supplied separately (not in JSON) — verify no way to inject
- Atomic transaction with rollback — verify rollback is complete
- Field allowlists — verify only expected fields accepted
- Export redacts API keys and webhook URLs

### 1.7 Docker & Deployment

**Files to review:**
- `docker/Dockerfile`
- `docker-compose.yml`
- `docker/entrypoint.sh`

**What to look for:**

| Check | What to verify |
|-------|----------------|
| Container user | Process runs as `appuser` (UID 1000), not root |
| Read-only filesystem | `read_only: true` is COMMENTED OUT — filesystem is writable |
| Capability dropping | `cap_drop: ALL` is COMMENTED OUT — retains default capabilities |
| no-new-privileges | `security_opt: no-new-privileges:true` IS enabled |
| Port binding | `127.0.0.1:7337:7337` — localhost only |
| Secret file permissions | `/run/secrets/` mounted read-only |
| Entrypoint injection | Review `entrypoint.sh` for command injection risks |
| Base image CVEs | Run `docker scout cves` or equivalent |

### 1.8 Error Handling & Information Disclosure

**Grep the entire codebase for:**
```
# Potential information leaks
grep -r "str(e)" src/splintarr/api/ --include="*.py"
grep -r "traceback" src/splintarr/ --include="*.py"
grep -r "\.detail" src/splintarr/api/ --include="*.py"

# Security placeholders
grep -rn "TODO\|FIXME\|HACK\|SECURITY\|XXX" src/splintarr/ --include="*.py"

# Dangerous patterns
grep -rn "|safe" src/splintarr/templates/ --include="*.html"
grep -rn "innerHTML" src/splintarr/ --include="*.js" --include="*.html"
grep -rn "text()" src/splintarr/ --include="*.py"
grep -rn "raw_connection\|execute(" src/splintarr/ --include="*.py"
```

### 1.9 AI-Generated Code Patterns

AI-generated codebases have specific vulnerability patterns. Check for:

| Pattern | How to detect |
|---------|---------------|
| Inconsistent auth enforcement | Verify EVERY route in `api/*.py` has auth dependency — grep for routes missing `get_current_user` |
| Copy-paste validation gaps | Compare similar schemas (InstanceCreate vs InstanceUpdate) for missing validators |
| Silenced exceptions | Grep for bare `except:` or `except Exception: pass` |
| Commented-out security | Grep for `# cap_drop`, `# read_only`, `# secure` |
| Placeholder implementations | Look for functions that return empty/default values without doing real work |
| Framework trust overreliance | Verify SQLAlchemy queries don't use `text()` with user input anywhere |

---

## Phase 2: Active Penetration Testing [REFERENCE: Splintarr]

> Replace endpoint URLs, cookie names, and payloads with your target's equivalents. The *attack categories* (JWT manipulation, SSRF bypass, brute force, XSS, config injection, header checks) are universal.

Start the Docker container and run these tests. Use `curl` via Bash for API testing and Playwright for browser-based testing.

### 2.1 Authentication Attacks

```bash
# Test 1: JWT algorithm confusion — send "alg": "none"
# Craft a JWT with algorithm "none" and no signature
python3 -c "
import base64, json
header = base64.urlsafe_b64encode(json.dumps({'alg':'none','typ':'JWT'}).encode()).rstrip(b'=')
payload = base64.urlsafe_b64encode(json.dumps({'sub':'1','username':'admin','type':'access','exp':9999999999}).encode()).rstrip(b'=')
print(f'{header.decode()}.{payload.decode()}.')
" | xargs -I{} curl -s http://localhost:7337/api/instances \
  -H 'Cookie: access_token={}'

# Test 2: Token type confusion — use refresh token as access token
# After login, extract refresh_token cookie and use it as access_token

# Test 3: Brute force timing analysis — compare valid vs invalid username response times
for i in $(seq 1 100); do
  curl -o /dev/null -s -w "%{time_total}\n" http://localhost:7337/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"wrong"}' >> /tmp/valid_user_times.txt
done
for i in $(seq 1 100); do
  curl -o /dev/null -s -w "%{time_total}\n" http://localhost:7337/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"nonexistent_user_xyz","password":"wrong"}' >> /tmp/invalid_user_times.txt
done
# Compare averages — should be within 10ms of each other

# Test 4: Registration race condition
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:7337/api/auth/register \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"racer$i\",\"password\":\"SecureP@ssw0rd!$i\",\"confirm_password\":\"SecureP@ssw0rd!$i\"}" &
done
wait
# Check if more than one user was created

# Test 5: Account lockout bypass
for i in $(seq 1 10); do
  curl -s http://localhost:7337/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"wrong_password"}'
done
# Now try correct password — should be locked
curl -s http://localhost:7337/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"SecureP@ssw0rd!123"}'

# Test 6: Rate limit bypass via X-Forwarded-For
for i in $(seq 1 20); do
  curl -s http://localhost:7337/api/auth/login \
    -H 'Content-Type: application/json' \
    -H "X-Forwarded-For: 10.0.0.$i" \
    -d '{"username":"admin","password":"wrong"}'
done
```

### 2.2 SSRF Bypass Testing

```bash
# After login, try adding instances with SSRF bypass URLs

# Test 1: Decimal IP (127.0.0.1 = 2130706433)
curl -s -X POST http://localhost:7337/api/instances \
  -H 'Content-Type: application/json' \
  -b /tmp/splintarr-cookies.txt \
  -d '{"name":"SSRF-decimal","instance_type":"sonarr","base_url":"http://2130706433:8989","api_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'

# Test 2: Octal IP
curl -s -X POST http://localhost:7337/api/instances \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"name":"SSRF-octal","instance_type":"sonarr","base_url":"http://0177.0.0.1:8989","api_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'

# Test 3: IPv6 loopback
curl -s -X POST http://localhost:7337/api/instances \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"name":"SSRF-ipv6","instance_type":"sonarr","base_url":"http://[::1]:8989","api_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'

# Test 4: IPv4-mapped IPv6
curl -s -X POST http://localhost:7337/api/instances \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"name":"SSRF-mapped","instance_type":"sonarr","base_url":"http://[::ffff:127.0.0.1]:8989","api_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'

# Test 5: Cloud metadata endpoint
curl -s -X POST http://localhost:7337/api/instances \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"name":"SSRF-metadata","instance_type":"sonarr","base_url":"http://169.254.169.254/latest/meta-data/","api_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'

# Test 6: URL with auth component
curl -s -X POST http://localhost:7337/api/instances \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"name":"SSRF-auth","instance_type":"sonarr","base_url":"http://evil@127.0.0.1:8989","api_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'

# Test 7: Hex IP encoding
curl -s -X POST http://localhost:7337/api/instances \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"name":"SSRF-hex","instance_type":"sonarr","base_url":"http://0x7f.0x0.0x0.0x1:8989","api_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
```

### 2.3 XSS & Injection Testing

Use Playwright browser tools to:

1. **Create instance with XSS payload name**: `<img src=x onerror=alert(1)>`
2. **Create search queue with script tag name**: `<script>alert(document.cookie)</script>`
3. **Navigate to dashboard** — verify payloads are escaped in rendered HTML
4. **Inspect CSP header** in Network tab — verify nonce is present and unique per request
5. **Check for `|safe`** usage in templates via `Grep`
6. **Check for `innerHTML`** usage in JavaScript via `Grep`

### 2.4 HTTP Security Headers

```bash
# Capture all response headers
curl -sI http://localhost:7337/login

# Check each header:
# - Content-Security-Policy (with nonce)
# - X-Content-Type-Options: nosniff
# - X-Frame-Options: DENY
# - Referrer-Policy: strict-origin-when-cross-origin
# - Strict-Transport-Security (only if SECURE_COOKIES=true)
# - X-XSS-Protection: 1; mode=block

# Verify CSP nonce changes per request
curl -sI http://localhost:7337/login | grep -i content-security
curl -sI http://localhost:7337/login | grep -i content-security
# Nonces should differ
```

### 2.5 WebSocket Testing

```bash
# Test 1: Connect without auth
python3 -c "
import asyncio, websockets
async def test():
    try:
        async with websockets.connect('ws://localhost:7337/ws/live') as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=2)
            print(f'Received: {msg}')
    except Exception as e:
        print(f'Connection result: {e}')
asyncio.run(test())
"

# Test 2: Connect with expired token
# (Craft a JWT with exp in the past)

# Test 3: Connection flood (DoS)
python3 -c "
import asyncio, websockets, http.cookies
async def flood():
    # First login to get cookies
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.post('http://localhost:7337/api/auth/login',
            json={'username':'admin','password':'SecureP@ssw0rd!123'})
        cookies = dict(r.cookies)

    connections = []
    for i in range(100):
        try:
            extra_headers = {'Cookie': f'access_token={cookies.get(\"access_token\",\"\")}'}
            ws = await websockets.connect('ws://localhost:7337/ws/live', extra_headers=extra_headers)
            connections.append(ws)
            print(f'Connection {i+1} established')
        except Exception as e:
            print(f'Connection {i+1} failed: {e}')
            break
    print(f'Total connections: {len(connections)}')
    for ws in connections:
        await ws.close()
asyncio.run(flood())
"
```

### 2.6 Config Import Attack Vectors

```bash
# Test 1: Import with SSRF URLs
curl -s -X POST http://localhost:7337/api/config/import/preview \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{
    "version": "1.3.0",
    "instances": [{"name":"evil","instance_type":"sonarr","base_url":"http://169.254.169.254/latest/","api_key":"test"}],
    "search_queues": [],
    "exclusions": [],
    "notifications": {}
  }'

# Test 2: Import with massive payload (DoS)
python3 -c "
import json
payload = {
    'version': '1.3.0',
    'instances': [{'name': f'inst_{i}', 'instance_type': 'sonarr', 'base_url': f'http://10.0.0.{i%255}:8989', 'api_key': 'a'*32} for i in range(10000)],
    'search_queues': [],
    'exclusions': [],
    'notifications': {}
}
print(json.dumps(payload))
" | curl -s -X POST http://localhost:7337/api/config/import/preview \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d @-

# Test 3: Import with SQL injection in field values
curl -s -X POST http://localhost:7337/api/config/import/preview \
  -b /tmp/splintarr-cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{
    "version": "1.3.0",
    "instances": [{"name":"Robert'\''); DROP TABLE users;--","instance_type":"sonarr","base_url":"http://example.com:8989","api_key":"aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],
    "search_queues": [],
    "exclusions": [],
    "notifications": {}
  }'
```

### 2.7 Browser-Based Testing (Playwright)

Use Playwright tools to perform these interactive tests:

1. **Login and inspect cookies** — verify HttpOnly, SameSite, Secure flags in browser DevTools
2. **Navigate every page** — Dashboard, Instances, Library, Exclusions, Queues, History, Settings
3. **Open Create Queue modal** — try typing `<script>` in the name field, submit, verify escaped on page
4. **Open Settings** — expand Notifications section, try XSS in webhook URL field
5. **Check Network requests** — verify no API keys visible in responses, no sensitive data in error messages
6. **Inspect CSP** — open Console, verify CSP violations are logged for injected scripts
7. **Test logout** — verify access_token cookie is cleared, replay the old token value manually

### 2.8 Dependency Vulnerability Scan

```bash
# Check for known CVEs in Python dependencies
docker exec splintarr pip list --format=json | python3 -c "
import json, sys
packages = json.load(sys.stdin)
for pkg in packages:
    print(f\"{pkg['name']}=={pkg['version']}\")
" > /tmp/splintarr-deps.txt
cat /tmp/splintarr-deps.txt

# Check key packages against known CVEs:
# - fastapi, starlette (CVE-2025-62727, CVE-2025-54121 — should be patched per pyproject.toml)
# - pyjwt
# - cryptography
# - httpx
# - pydantic
```

---

## Phase 3: Regression Verification [REFERENCE: Splintarr]

> Replace with your target's prior assessment history. If this is the first assessment, skip this phase.

Prior assessments (2026-02-24 through 2026-02-28) found and fixed 58+ vulnerabilities. Verify these fixes still hold:

| Prior Finding | Fix Location | Regression Test |
|---------------|-------------|-----------------|
| Weak Fernet key derivation (padding with zeros) | `security.py:173-189` | Verify HKDF is used, not truncation/padding |
| JWT algorithm confusion | `auth.py:39` | Send `"alg":"none"` JWT |
| SQL injection in database URL | `database.py:162` | Verify single-quote escaping in PRAGMA key |
| SSRF protection insufficient | `ssrf_protection.py:21-44` | Test all bypass vectors above |
| Timing attack on login | `security.py:429` | Timing analysis (Phase 2, Test 3) |
| innerHTML usage | Templates + JS | Grep for `innerHTML` |
| Open redirect via `?next=` | `api/auth.py` | Verify parameter removed |
| API keys in responses | `api/instances.py` | Verify `api_key` field absent from all instance responses |

---

## Output Format

Produce a structured security assessment report with these sections:

### 1. Executive Summary
- Overall risk rating (Critical/High/Medium/Low)
- Total findings by severity
- Top 3 most impactful findings
- Summary of testing coverage

### 2. Findings Table

| ID | Title | Severity | CVSS 3.1 | OWASP Category | CWE | Status |
|----|-------|----------|----------|----------------|-----|--------|
| VULN-01 | Finding title | Critical | 9.8 | A01 | CWE-XXX | Open |

### 3. Detailed Findings (for each)

```
## VULN-XX: [Title]

**Severity**: Critical | High | Medium | Low | Informational
**CVSS 3.1**: X.X (vector string)
**OWASP**: A0X — Category
**CWE**: CWE-XXX — Name
**File**: path/to/file.py:line_number
**Status**: Open | Confirmed Fixed | Accepted Risk

### Description
[Technical description of the vulnerability]

### Proof of Concept
[Exact commands, curl requests, or Playwright steps to reproduce]

### Impact
[What an attacker can achieve — data breach, privilege escalation, DoS, etc.]

### Recommendation
[Specific code changes to fix the issue]
```

### 4. Positive Findings
List security controls that were correctly implemented (gives credit and confirms coverage).

### 5. Accepted Risks Review
Review the 5 accepted risks documented in `docs/explanation/security.md` (issues #45-#49). For each: confirm the risk assessment is still valid, or flag if circumstances have changed.

### 6. Testing Coverage Matrix

| OWASP WSTG Category | Tests Performed | Findings |
|---------------------|----------------|----------|
| WSTG-ATHN (Authentication) | List tests | Count |
| WSTG-ATHZ (Authorization) | List tests | Count |
| WSTG-SESS (Session Mgmt) | List tests | Count |
| WSTG-INPV (Input Validation) | List tests | Count |
| WSTG-CRYP (Cryptography) | List tests | Count |
| WSTG-BUSL (Business Logic) | List tests | Count |
| WSTG-CLNT (Client Side) | List tests | Count |
| WSTG-CONF (Configuration) | List tests | Count |

---

## Teardown [REFERENCE: Splintarr]

After testing:

```bash
docker-compose down
rm -rf data/
rm /tmp/splintarr-cookies.txt /tmp/valid_user_times.txt /tmp/invalid_user_times.txt
```

---

## Known Accepted Risks [REFERENCE: Splintarr]

> Replace with your target's documented risk acceptances. If none exist, remove this section.

These are documented and accepted. Verify they are still accurately described:

1. **In-memory access token blacklist** (GitHub #45) — Lost on restart, 15-min window
2. **SSRF DNS rebinding TOCTOU** (GitHub #46) — Microsecond window between validation and connection
3. **No separate CSRF token** (GitHub #47) — Relies on SameSite=Strict cookies
4. **Unauthenticated poster images** (GitHub #48) — Public media artwork at predictable paths
5. **CSP style-src unsafe-inline** (GitHub #49) — Required by Pico CSS

---

## Pre-Identified Concerns [REFERENCE: Splintarr]

> Replace with your target's pre-analysis output, or remove for blind testing. These accumulate across assessment runs via the Self-Improvement Protocol.

Based on prior analysis and the v1.3.0 assessment results, these warrant immediate investigation:

1. **Container runs as root** — Entrypoint may not drop privileges via gosu despite user creation in Dockerfile. **Test: `docker exec <container> whoami`** (v1.3.0 finding: VULN-01, Medium)
2. **`ALLOW_LOCAL_INSTANCES=true` bypasses cloud metadata blocking** — When enabled, SSRF checks skip ALL blocked networks including 169.254.x.x. **Test cloud metadata separately from private ranges** (v1.3.0 finding: VULN-02, Medium)
3. **Validation error handler leaks passwords** — Pydantic `RequestValidationError` includes raw `input` field with submitted passwords. **Test: send `{"username": 123, "password": "real"}` to login** (v1.3.0 finding: VULN-03, Medium)
4. **No WebSocket Origin header validation** — CSWSH risk if attacker can get victim to visit malicious page (v1.3.0 finding: VULN-04, Medium)
5. **Docker hardening disabled** — `read_only` and `cap_drop` commented out in docker-compose.yml
6. **`decrypt_if_needed()` silently returns ciphertext on failure** — Masks key rotation problems
7. **No WebSocket connection limit** — Unbounded `active_connections` list
8. **WebSocket connections persist beyond token expiry** — No periodic re-authentication
9. **Config import has no payload size limit** — DoS via massive JSON
10. **Registration race condition** — Concurrent requests may bypass single-user gate (API endpoint only; dashboard has post-commit check)
11. **Config import webhook URL not SSRF-validated** — Validated for https:// prefix only, not against SSRF blocklist

---

## Filing Findings

**All findings must be filed according to the target repository's security policy.** Check for `SECURITY.md` in the repo root. If GitHub Security Advisories are available, **always try filing there first** for Medium+ findings before creating public issues.

### Severity-Based Filing Protocol

| Severity | Filing Method | Rationale |
|----------|--------------|-----------|
| **Critical / High** | GitHub Security Advisory (if available) | Private disclosure. Vulnerability details must not be public until a fix is released. |
| **Medium** | GitHub Security Advisory (preferred) or private issue | Use advisory if the finding is exploitable; use private issue if it's a hardening gap. |
| **Low / Informational** | Public GitHub Issue | Missing headers, best-practice suggestions, and defense-in-depth improvements are not sensitive. |

### How to File a GitHub Security Advisory

Use the `gh` CLI:

```bash
# Replace OWNER/REPO with your target repository
# Check if security advisories are available
gh api repos/OWNER/REPO/security-advisories --method GET 2>&1 | head -5

# If available, create an advisory (draft) — use --input for JSON body
gh api repos/OWNER/REPO/security-advisories --method POST --input - <<'JSON'
{
  "summary": "VULN-XX: [Title]",
  "description": "[Full finding details: Description, PoC, Impact, Recommendation, CVSS, CWE]",
  "severity": "high",
  "vulnerabilities": [
    {
      "package": {"ecosystem": "pip", "name": "PACKAGE_NAME"},
      "vulnerable_version_range": "<= CURRENT_VERSION",
      "patched_versions": null,
      "vulnerable_functions": []
    }
  ]
}
JSON
```

If the `gh api` call for security advisories fails (403 or not available), fall back to:

```bash
# Create a private issue instead (label: security)
gh issue create \
  --repo OWNER/REPO \
  --title "VULN-XX: [Title]" \
  --body "[Full finding details]" \
  --label "security"
```

### What to Include in Each Filing

Per `SECURITY.md`, each report must include:

1. **Description** of the vulnerability and its potential impact
2. **Steps to reproduce** (exact commands — copy from your Proof of Concept)
3. **Affected version(s)** — current version (or `<= X.Y.Z` if applicable to all versions)
4. **Suggested fix** if you have one (include specific code changes)

### Filing Sequence

1. Complete the full assessment first — do not file findings one at a time during testing
2. Deduplicate — if multiple tests reveal the same root cause, file once
3. File Critical/High via Security Advisory first
4. File Medium via Security Advisory (preferred) or issue
5. File Low/Informational as public issues, batched if related
6. Include the VULN-XX identifier from your report in each filing for cross-reference

### Out of Scope for Filing

Per `SECURITY.md`, do **not** file:
- Self-hosted misconfiguration (weak secrets, exposing to internet)
- Denial of service (single-user homelab app — unless it reveals a deeper flaw)
- Upstream dependency vulnerabilities (report to the upstream project)
- Issues requiring local/physical host access
- Missing security hardening suggestions (file as regular issues, not advisories)

---

## Adapting This Prompt for Other Projects

This prompt was written for Splintarr v1.3.0 but the methodology is reusable. To adapt it for any codebase:

### Step 1: Replace Project-Specific Context

| Section | What to Replace |
|---------|----------------|
| **Your Role** | Keep as-is (generic pentester persona) |
| **Environment Setup** | Replace with the target project's build/run/login commands |
| **Phase 1: Static Code Review** | Replace file paths, line numbers, and technology-specific checks |
| **Phase 2: Active Testing** | Replace curl commands with the target's API endpoints and auth mechanism |
| **Phase 3: Regression** | Replace with the target's prior assessment history (or remove if first assessment) |
| **Known Accepted Risks** | Replace with the target's documented risk acceptances (or remove) |
| **Pre-Identified Concerns** | Replace with output from your own pre-analysis (or remove for blind testing) |
| **Filing Findings** | Replace with the target repo's `SECURITY.md` policy and advisory URL |

### Step 2: Regenerate the Attack Surface Inventory

Before running the assessment, use an exploration agent to map the target's attack surface:

```
Prompt for surface mapping agent:
"Thoroughly map the security attack surface of [project] at [path].
Document: (1) all authentication mechanisms with file:line references,
(2) all API endpoints with auth/rate-limit/validation details,
(3) all cryptographic implementations with parameters,
(4) all external integrations and how credentials are handled,
(5) all input validation schemas and any bypass conditions,
(6) Docker/deployment security configuration,
(7) error handling patterns that might leak information."
```

Paste the resulting inventory into Phase 1 of this prompt, replacing the Splintarr-specific checks.

### Step 3: Regenerate Active Test Commands

For each endpoint in the inventory, generate test commands appropriate to the target's:
- **Auth mechanism** (JWT cookies, Bearer tokens, API keys, session IDs, OAuth)
- **Framework** (FastAPI, Django, Express, Spring — each has framework-specific bypasses)
- **Database** (SQLite, PostgreSQL, MongoDB — injection techniques differ)
- **Deployment** (Docker, Kubernetes, bare metal — container escape vs. host escape)

### Step 4: Adjust Severity Criteria

The threat model changes the severity scale:
- **Homelab app** (like Splintarr): DoS is Low, auth bypass is High
- **Multi-tenant SaaS**: DoS is High, data isolation bypass is Critical
- **Financial app**: Any data exposure is Critical, any auth weakness is Critical
- **Internal tool**: Network-accessible findings are higher severity than localhost-only

### Technology-Specific Test Libraries

| Tech Stack | Additional Tests to Add |
|-----------|------------------------|
| **Django** | CSRF token validation, ORM `.extra()` / `.raw()` injection, DEBUG=True exposure, SECRET_KEY in settings.py |
| **Express/Node** | Prototype pollution, NoSQL injection, template injection, npm audit |
| **Spring Boot** | Actuator endpoint exposure, SpEL injection, deserialization, CSRF token |
| **Go** | Template injection, goroutine leak DoS, race conditions in handlers |
| **React/SPA** | DOM XSS, localStorage token storage, source map exposure, open redirects in client routing |

---

## Prompt Self-Improvement Protocol

After completing the assessment, reflect on the process and improve this prompt for next time.

### Mandatory Retrospective

At the end of your assessment report, add an **Appendix: Prompt Improvement Recommendations** section. For each item, specify whether it's an **addition**, **modification**, or **removal** to this prompt.

Answer these questions:

1. **Coverage gaps**: Were there any attack vectors you thought of during testing that weren't mentioned in this prompt? Add them.

2. **False leads**: Were any of the pre-identified concerns or test cases irrelevant or impossible to test? Remove or downgrade them.

3. **Tool limitations**: Did any test commands fail due to tool constraints (e.g., Playwright can't inspect httpOnly cookies, `curl` can't do WebSocket)? Document workarounds.

4. **New techniques**: Did you discover bypass techniques or attack patterns during testing that should be added to the methodology? Add them with the specific test that revealed them.

5. **Severity calibration**: Were any severity ratings in the pre-identified concerns wrong after empirical testing? Adjust the guidance.

6. **Missing context**: Was there project context you needed but didn't have? Add it to the "Replace Project-Specific Context" table.

7. **Efficiency**: Were there tests you could have skipped based on earlier results (e.g., if SSRF protection is solid, skip 5 of 7 bypass vectors)? Add decision-tree guidance.

8. **Framework-specific insights**: Did you discover FastAPI/Pydantic/SQLAlchemy-specific patterns that should be added to the technology-specific test library?

### Output Format for Improvements

```markdown
## Appendix: Prompt Improvement Recommendations

### Additions
- [CATEGORY] Add test for [specific technique] — discovered when [context]
- [CATEGORY] Add pre-check for [condition] — would have saved time because [reason]

### Modifications
- [SECTION] Change [old guidance] to [new guidance] — because [reason]
- [TEST-ID] Adjust severity from [old] to [new] — empirical result showed [evidence]

### Removals
- [TEST-ID] Remove [test] — not feasible because [tool limitation / architectural impossibility]
- [SECTION] Remove [guidance] — outdated because [reason]

### Tool Workarounds
- [TOOL] For [limitation], use [workaround] instead
```

### Applying Improvements

After the assessment, apply the improvements to this prompt file and commit:

```bash
# Edit the prompt with improvements
# Then commit
git add docs/security-assessment-prompt.md
git commit -m "security: update assessment prompt with findings from [version] review"
```

This creates a living document that improves with every assessment cycle.

---

## Lessons Learned: v1.3.0 Assessment (2026-03-05)

The following improvements were applied after running this prompt against Splintarr v1.3.0.

### Additions (from v1.3.0 run)

1. **[DOCKER] Entrypoint privilege dropping** — Add explicit test: `docker exec <container> whoami`. The v1.3.0 assessment found that `gosu` was installed but never invoked in the entrypoint. This was the highest-impact finding (Medium) but was NOT in the original pre-identified concerns list.

2. **[VALIDATION] Password in error responses** — Add test: send malformed login request (e.g., `{"username": 123, "password": "real_password"}`) and check if the response `input` field contains the password. Pydantic's `RequestValidationError` includes raw input by default. This was the third-highest finding.

3. **[DOCKER] read_only/cap_drop as separate test** — Distinguish between "commented out for compatibility" (documented choice) vs. "missing entirely" (oversight). Both are findings, but the former is lower severity.

4. **[SSRF] `allow_local` scope analysis** — When testing SSRF with `allow_local=True`, test cloud metadata (169.254.x.x) SEPARATELY from private ranges (10.x, 172.16.x, 192.168.x). The `allow_local` flag may bypass the entire blocklist, not just private ranges.

5. **[CRYPTO] Decrypt failure behavior** — Add test: what happens when `decrypt_if_needed()` encounters a value encrypted with a different key? Silent fallback to ciphertext is a finding (masks key rotation problems).

6. **[WEBSOCKET] Connection limit test** — Add: attempt to open 100+ WebSocket connections and measure server memory impact.

7. **[CONFIG] Webhook URL SSRF** — Config import may validate instance URLs but not webhook URLs. Test both independently.

### Modifications (from v1.3.0 run)

1. **[Phase 2] Agent permissions** — Agents dispatched for active testing were sandboxed from running some Bash commands against Docker. **Mitigation**: Either (a) run tests directly in the main session, or (b) pre-run Docker setup commands and provide cookie jar / auth tokens to agents explicitly, or (c) launch agents with clear instructions that they MUST use Bash for curl commands.

2. **[Phase 2] Static-only fallback** — When active testing is blocked by tool permissions, the assessment can still provide high-value findings via comprehensive static code review. The static review agent found 15 findings (3 Medium) without running any live commands. This is NOT a downgrade — it's defense-in-depth for the assessment itself.

3. **[SSRF severity] `allow_local` bypass** — Original pre-identified concern rated this as "may bypass cloud metadata." After review, confirmed it bypasses ALL blocked networks when enabled. Upgrade from investigation-needed to confirmed Medium.

4. **[Pre-identified concerns #6] Registration race** — Downgrade from investigation concern to Low/Info. The dashboard endpoint already has a post-commit check; only the API endpoint lacks it. Rate limiting (3/hour) makes practical exploitation infeasible.

### Removals

None — all original test cases remained relevant.

### Tool Workarounds (from v1.3.0 run)

1. **[Bash in sub-agents]** Sub-agents may be denied Bash tool access depending on permission settings. Workaround: run Docker setup and curl commands in the main session, then dispatch agents for code review (Read/Grep only). Pass authentication cookies as explicit strings in agent prompts.

2. **[WebSocket testing]** Python `websockets` library may not be installed in the assessment environment. Workaround: use `python3 -c "import websockets"` to check availability first. If unavailable, test WebSocket auth via static code review of `ws.py` (the auth logic is fully visible in code).

3. **[Timing analysis]** Running 100+ timed requests from `curl` inside Claude Code can be slow. Workaround: reduce to 20 samples per group (valid/invalid username). Statistical significance requires ~20+ samples for Argon2 timing (which takes ~200ms per hash).
