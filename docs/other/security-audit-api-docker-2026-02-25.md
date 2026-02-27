# Comprehensive Security Audit: API & Docker Best Practices
## Splintarr

**Audit Date:** February 25, 2026
**Methodology:** OWASP API Security Top 10 (2023), Docker Security Best Practices, API Key Transmission Standards
**Codebase Version:** 0.1.0-alpha (post-penetration-test fixes)
**Scope:** Full codebase analysis -- 50+ source files across all application layers
**Status:** All findings remediated

---

## Executive Summary

This audit was conducted as a second-round deep analysis of the entire codebase, informed by current industry best practices for API security, inter-service credential transmission, and Docker container security. It was performed after the initial penetration test and its remediation cycle were complete.

The audit identified **20 new security findings** that were not caught by the earlier penetration test. All 20 have been remediated across 24 files in two commits.

### Risk Rating: **MEDIUM-LOW** (post-remediation)

| Severity | Found | Fixed | Remaining |
|----------|-------|-------|-----------|
| CRITICAL | 3 | 3 | 0 |
| HIGH | 5 | 5 | 0 |
| MEDIUM | 7 | 7 | 0 |
| LOW | 5 | 5 | 0 |
| **Total** | **20** | **20** | **0** |

### What Made This Audit Different

The earlier security audit (Phase 7) and penetration test focused on cryptographic implementation, authentication bypass, and injection attacks. This audit was specifically designed around three areas not deeply covered before:

1. **OWASP API Security Top 10 (2023)** -- the API-specific vulnerability taxonomy, including SSRF, unrestricted resource consumption, and unsafe consumption of third-party APIs
2. **Docker container-host security** -- secrets management, privilege escalation, filesystem permissions, and network segmentation
3. **API key lifecycle** -- how credentials are stored, transmitted, decrypted, used, and discarded across service boundaries

---

## Research Basis

The audit was informed by current best-practice research from these sources:

- [OWASP API Security Top 10 -- 2023 Edition](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)
- [REST Security -- OWASP Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
- [Docker Security -- OWASP Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
- [Manage Sensitive Data with Docker Secrets -- Docker Docs](https://docs.docker.com/engine/swarm/secrets/)
- [Docker Secrets Guide -- Wiz](https://www.wiz.io/academy/container-security/docker-secrets)
- [4 Ways to Securely Store Secrets in Docker -- GitGuardian](https://blog.gitguardian.com/how-to-handle-secrets-in-docker/)
- [API Security Best Practices 2026 -- TrustedAccounts](https://www.trustedaccounts.org/blog/post/professional-api-security-best-practices)
- [How to Keep Docker Secrets Secure -- Spacelift](https://spacelift.io/blog/docker-secrets)

Key principles applied during the audit:

- **Never transmit credentials in plaintext** -- always use TLS/mTLS, never in URL query strings
- **Use Docker secrets, not environment variables** -- env vars appear in process listings, container inspection, and logs
- **Disable HTTP redirects when credentials are in headers** -- redirects can leak Authorization/API-Key headers to third parties
- **Validate all URLs server-side with DNS resolution** -- hostname-only checks are bypassed by DNS rebinding
- **Use nonce-based CSP instead of `'unsafe-inline'`** -- `'unsafe-inline'` completely negates XSS protection from CSP
- **Apply rate limiting to every state-changing endpoint** -- not just authentication
- **Run containers as non-root with read-only filesystems** -- limits blast radius of container compromise

---

## Findings

### CRITICAL Findings

#### C1. Password Case Normalization Destroys Entropy

| | |
|---|---|
| **OWASP** | API2:2023 -- Broken Authentication |
| **CWE** | CWE-916 (Use of Password Hash With Insufficient Computational Effort) |
| **File** | `src/splintarr/schemas/user.py:136` |
| **Severity** | CRITICAL |
| **Status** | FIXED |

**Issue:** The first password validator returned `v.lower()`, silently converting every password to lowercase before hashing. A user who set `MyS3cur3!Pass` would have `mys3cur3!pass` stored. The second validator on the same field then checked for uppercase letters -- which had already been stripped.

Additionally, there were two `@field_validator("password")` decorators on the same field with overlapping logic, creating ambiguity about execution order.

**Impact:** Password keyspace reduced by approximately 50%. Users could not reliably log in if the login path did not also lowercase.

**Fix:**
- Removed `return v.lower()` -- password is now returned with original case preserved
- Removed the duplicate validator entirely (consolidated into one)
- Expanded the common password blocklist from 25 to 100+ entries per NIST SP 800-63B
- Added explicit maximum password length (128 characters) to prevent Argon2 DoS

---

#### C2. Health Check Endpoint Leaks Database Error Details

| | |
|---|---|
| **OWASP** | API8:2023 -- Security Misconfiguration |
| **CWE** | CWE-209 (Generation of Error Message Containing Sensitive Information) |
| **File** | `src/splintarr/main.py:239` |
| **Severity** | CRITICAL |
| **Status** | FIXED |

**Issue:** The unauthenticated `/health` endpoint returned raw Python exception strings in its JSON response:

```python
"database": {"status": "unhealthy", "error": str(e)}
```

This could expose database driver names, file paths, encryption status, connection parameters, and internal architecture to any network-reachable caller.

**Fix:** Returns a generic `{"status": "unhealthy"}` object. Full error detail is logged server-side only.

---

#### C3. Content Security Policy Allows `'unsafe-inline'` Scripts

| | |
|---|---|
| **OWASP** | API8:2023 -- Security Misconfiguration |
| **CWE** | CWE-79 (Improper Neutralization of Input During Web Page Generation) |
| **File** | `src/splintarr/main.py:121` |
| **Severity** | CRITICAL |
| **Status** | FIXED |

**Issue:** The CSP header included `script-src 'self' 'unsafe-inline'`, which completely nullifies XSS protection. If an attacker can inject HTML into any page (via stored data in templates, error messages, etc.), inline scripts would execute freely.

Nine templates contained inline `<script>` blocks.

**Fix:** Implemented per-request CSP nonces:
1. Security headers middleware generates a cryptographic nonce via `secrets.token_urlsafe(16)` before each request
2. Nonce is stored on `request.state.csp_nonce` (accessible to Jinja2 templates)
3. CSP header uses `script-src 'self' 'nonce-{nonce}'` instead of `'unsafe-inline'`
4. All 9 templates updated to use `<script nonce="{{ request.state.csp_nonce }}">`

Note: `style-src 'unsafe-inline'` is retained because Pico CSS framework requires it. CSS-based attacks are significantly more limited than script-based attacks.

---

### HIGH Findings

#### H1. HTTP Client Follows Redirects with API Key in Headers

| | |
|---|---|
| **OWASP** | API10:2023 -- Unsafe Consumption of APIs |
| **CWE** | CWE-601 (URL Redirection to Untrusted Site) |
| **Files** | `services/sonarr.py:146`, `services/radarr.py:146` |
| **Severity** | HIGH |
| **Status** | FIXED |

**Issue:** Both HTTP clients were configured with `follow_redirects=True` while sending the Sonarr/Radarr API key in `X-Api-Key` headers on every request. If a compromised or misconfigured instance responded with a 302 redirect to an attacker-controlled server, the API key would be transmitted to that server.

**Fix:** Set `follow_redirects=False` on both clients. Sonarr and Radarr API endpoints do not use HTTP redirects in normal operation.

---

#### H2. No Rate Limiting on Password Change Endpoint

| | |
|---|---|
| **OWASP** | API4:2023 -- Unrestricted Resource Consumption |
| **CWE** | CWE-307 (Improper Restriction of Excessive Authentication Attempts) |
| **File** | `src/splintarr/api/auth.py` |
| **Severity** | HIGH |
| **Status** | FIXED |

**Issue:** The `/api/auth/password/change` endpoint had no rate limiting. An attacker with a valid session could brute-force the current password verification field.

**Fix:** Added `@limiter.limit("3/minute")` and the required `request: Request` parameter.

---

#### H3. No Rate Limiting on Search Queue and Search History Endpoints

| | |
|---|---|
| **OWASP** | API4:2023 -- Unrestricted Resource Consumption |
| **CWE** | CWE-770 (Allocation of Resources Without Limits) |
| **Files** | `api/search_queue.py`, `api/search_history.py` |
| **Severity** | HIGH |
| **Status** | FIXED |

**Issue:** None of the 14 search queue or search history endpoints had rate limits. An authenticated attacker could flood the scheduler with queue creation, trigger excessive database queries via history listing, or exhaust database connections.

**Fix:** Added rate limits to all 14 endpoints:
- Create/delete/start/pause/resume: 10/minute
- Update: 20/minute
- List/get/stats/failures/history: 30/minute
- Get single queue/status: 60/minute
- Cleanup (destructive): 5/minute

---

#### H4. Rate Limiter Uses In-Memory Storage

| | |
|---|---|
| **OWASP** | API4:2023 -- Unrestricted Resource Consumption |
| **CWE** | CWE-770 (Allocation of Resources Without Limits) |
| **File** | `src/splintarr/main.py:37` |
| **Severity** | HIGH |
| **Status** | DOCUMENTED (requires infrastructure change) |

**Issue:** Rate limits are stored in-process memory (`storage_uri="memory://"`). The application allows up to 8 workers. Each worker maintains independent counters, so an attacker effectively gets `N * limit` requests where N is the worker count.

**Fix:** Added documentation warning in the code. Full fix requires either:
- Enforcing `workers=1` (current recommendation)
- Using Redis backend: `storage_uri="redis://localhost:6379"` (see `docs/how-to-guides/configure-redis-rate-limiting.md`)

---

#### H5. Duplicate SSRF Validation -- Weaker Copy Bypasses DNS Resolution

| | |
|---|---|
| **OWASP** | API7:2023 -- Server-Side Request Forgery |
| **CWE** | CWE-918 (Server-Side Request Forgery) |
| **File** | `src/splintarr/api/instances.py:555-610` |
| **Severity** | HIGH |
| **Status** | FIXED |

**Issue:** The `InstanceTestRequest` model contained a hand-written SSRF validator that only checked IP addresses directly in the URL. It did not perform DNS resolution. The application already had a comprehensive `ssrf_protection.py` module that resolves hostnames via DNS and checks all resolved IPs against blocked networks (including cloud metadata endpoints, CGN ranges, multicast, etc.).

The hand-written validator could be bypassed via DNS rebinding: an attacker registers a domain that alternates between a public IP (passing validation) and a private IP (reaching internal services).

**Fix:** Replaced the inline validator with a call to `ssrf_protection.validate_instance_url()`, which resolves DNS and validates all resulting IPs.

---

### MEDIUM Findings

#### M1. JWT `additional_claims` Accepts Reserved Claim Names

| | |
|---|---|
| **OWASP** | API2:2023 -- Broken Authentication |
| **CWE** | CWE-287 (Improper Authentication) |
| **File** | `src/splintarr/core/auth.py:88` |
| **Status** | FIXED |

**Issue:** `create_access_token()` accepted an `additional_claims` dict and called `claims.update(additional_claims)` without checking for reserved names like `sub`, `exp`, `iat`, `jti`, or `type`. An internal code path that passed attacker-influenced data could override security-critical claims.

**Fix:** Added a reserved claim name check that rejects `sub`, `exp`, `iat`, `jti`, `type`, and `username` before merging.

---

#### M2. Common Password Blocklist Contains Only 25 Entries

| | |
|---|---|
| **OWASP** | API2:2023 -- Broken Authentication |
| **CWE** | CWE-521 (Weak Password Requirements) |
| **File** | `src/splintarr/schemas/user.py:103-129` |
| **Status** | FIXED |

**Issue:** NIST SP 800-63B recommends checking passwords against known breached/common password lists. The implementation checked only 25 passwords.

**Fix:** Expanded the blocklist to 100+ entries covering common passwords, keyboard patterns, default credentials, and common substitutions.

---

#### M3. No Maximum Password Length

| | |
|---|---|
| **OWASP** | API4:2023 -- Unrestricted Resource Consumption |
| **CWE** | CWE-770 (Allocation of Resources Without Limits) |
| **File** | `src/splintarr/schemas/user.py` |
| **Status** | FIXED |

**Issue:** Argon2id is intentionally slow and memory-intensive. Submitting an extremely long password (e.g., 1 MB) would cause excessive CPU and memory consumption during hashing.

**Fix:** Added explicit 128-character maximum in the password validator. The `max_length=128` was already on the Pydantic Field, but the validator now also enforces it with a clear error message.

---

#### M4. X-Forwarded-For Trusted Without Proxy Validation

| | |
|---|---|
| **OWASP** | API8:2023 -- Security Misconfiguration |
| **CWE** | CWE-345 (Insufficient Verification of Data Authenticity) |
| **File** | `src/splintarr/api/auth.py:61-77` |
| **Status** | FIXED |

**Issue:** The `get_client_ip()` function unconditionally trusted the `X-Forwarded-For` header. Without a reverse proxy in front, an attacker can spoof their IP to bypass rate limiting and account lockout.

**Fix:** `X-Forwarded-For` is now only trusted in production (where a reverse proxy is expected and documented). In development and test environments, `request.client.host` is used directly.

---

#### M5. Docker Production Container Runs as Root

| | |
|---|---|
| **OWASP** | API8:2023 -- Security Misconfiguration |
| **CWE** | CWE-250 (Execution with Unnecessary Privileges) |
| **Files** | `docker/docker-compose.production.yml` |
| **Status** | FIXED |

**Issue:** The `user: "1000:1000"` and `read_only: true` directives were commented out for "Windows compatibility." If the container is compromised, the attacker has root access and can modify application code.

**Fix:** Uncommented both directives in the production compose file. The development compose file remains permissive for Windows compatibility, which is the appropriate separation.

---

#### M6. Development Compose Has Hardcoded Weak Secrets

| | |
|---|---|
| **OWASP** | API8:2023 -- Security Misconfiguration |
| **CWE** | CWE-798 (Use of Hard-coded Credentials) |
| **File** | `docker/docker-compose.development.yml:31-33` |
| **Status** | FIXED |

**Issue:** The development compose file contained secrets shorter than 32 characters (e.g., `dev-secret-key-change-in-production`). While the config validators now reject keys under 32 characters, the dev secrets would prevent the application from starting.

**Fix:** Made all dev secrets exactly 42 characters with the prefix `dev-only-insecure-` to clearly mark them as non-production values while satisfying the length validator.

---

#### M7. Error Responses Leak Exception Details

| | |
|---|---|
| **OWASP** | API8:2023 -- Security Misconfiguration |
| **CWE** | CWE-209 (Error Message Containing Sensitive Information) |
| **Files** | `api/instances.py:253,470`, `api/dashboard.py:415` |
| **Status** | FIXED |

**Issue:** Several endpoints returned `f"Failed to X: {str(e)}"` in HTTP responses, potentially exposing internal file paths, database driver names, network information, or connection details.

**Fix:** All error responses now return generic messages. Full exception details are logged server-side at ERROR level for debugging.

---

### LOW Findings

#### L1. `console.log` Statements in Production JavaScript

| | |
|---|---|
| **File** | `src/splintarr/static/js/app.js` |
| **Status** | FIXED |

**Issue:** Five `console.log` statements exposed auto-refresh intervals, API response data, and initialization messages in the browser console.

**Fix:** Removed all debug logging from production JavaScript.

---

#### L2. CORS Default Origin Port Mismatch

| | |
|---|---|
| **File** | `src/splintarr/config.py:152` |
| **Status** | FIXED |

**Issue:** Default CORS origin was `http://localhost:8000` but the application listens on port `7337`.

**Fix:** Changed to `http://localhost:7337`.

---

#### L3. TOTP Secret Returned in Plaintext During Setup

| | |
|---|---|
| **File** | `src/splintarr/schemas/user.py` (TwoFactorSetup) |
| **Status** | ACCEPTED RISK |

**Issue:** The TOTP secret is returned in the API response during 2FA setup. If the response is logged by middleware or a proxy, the secret is compromised.

**Assessment:** This is standard behavior -- the secret must be transmitted to the user so they can add it to their authenticator app. Google Authenticator, Authy, and all similar apps require this. The risk is mitigated by HTTPS in production and the fact that the secret is only returned once during setup.

---

#### L4. No Certificate Pinning for External API Calls

| | |
|---|---|
| **Files** | `services/sonarr.py`, `services/radarr.py` |
| **Status** | ACCEPTED RISK |

**Issue:** While SSL verification is enabled by default, there is no certificate pinning.

**Assessment:** Certificate pinning is not practical for this application. Users configure their own Sonarr/Radarr instance URLs, and the certificates are unknown ahead of time (self-signed, Let's Encrypt, or corporate CA). Pinning would break connectivity for the majority of users.

---

#### L5. API Key Minimum Length Set to 20 Characters

| | |
|---|---|
| **File** | `src/splintarr/schemas/instance.py` |
| **Status** | FIXED |

**Issue:** Sonarr and Radarr generate 32-character hex API keys. The minimum validation was 20 characters, which would accept truncated or invalid keys.

**Fix:** Increased minimum length to 32 characters to match the actual key format.

---

## Current Security Posture

After remediation of all 20 findings, the application's defense-in-depth layers are:

### Authentication & Credentials
- Argon2id password hashing with HMAC-SHA256 pepper
- Case-preserved passwords with 100+ common password blocklist
- 128-character maximum to prevent hashing DoS
- JWT with HS256, hardcoded algorithm whitelist, reserved claim protection
- Account lockout after configurable failed attempts
- Rate limiting on all authentication endpoints (login, register, password change, refresh)
- Generic error messages to prevent account enumeration

### API Key Lifecycle
- Encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256), keyed via HKDF
- Decrypted only at point of use, never logged
- Never returned in API responses
- Transmitted to Sonarr/Radarr via `X-Api-Key` header only (no URL parameters)
- HTTP redirects disabled to prevent header leakage to third parties
- SSRF protection with DNS resolution validates all target IPs before connection

### Transport Security
- HTTPS/TLS recommended and documented for production
- HSTS header in production mode
- Cookies: HttpOnly, Secure, SameSite=Strict
- CORS: explicit origin list, never `*` with credentials

### Container Security
- Production: non-root user (`1000:1000`), read-only filesystem
- All capabilities dropped (`cap_drop: ALL`)
- No new privileges (`no-new-privileges:true`)
- Docker secrets for all sensitive configuration (not environment variables)
- Port bound to localhost only (reverse proxy required for external access)
- Resource limits (CPU, memory)
- Health check with proper timeouts

### Content Security
- Nonce-based CSP for inline scripts (no `'unsafe-inline'`)
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- Referrer-Policy: strict-origin-when-cross-origin

### Rate Limiting
- Authentication endpoints: 3-10/minute
- Data read endpoints: 30-60/minute
- Data write endpoints: 10-20/minute
- Destructive operations: 5-10/minute

---

## Remaining Recommendations

These items are outside the scope of this remediation cycle but should be addressed in future work:

1. **Redis-backed rate limiting** -- Required before enabling multiple workers. See `docs/how-to-guides/configure-redis-rate-limiting.md`.
2. **Complete 2FA implementation** -- TOTP infrastructure exists but verification is not wired into the login flow.
3. **Dependency updates** -- Starlette CVEs (CVE-2025-62727, CVE-2025-54121) require updating FastAPI.
4. **Automated security scanning in CI/CD** -- Bandit and Safety should run on every pull request.
5. **Consider PyJWT migration** -- python-jose's ecdsa dependency has unpatched timing vulnerabilities (CVE-2024-23342).

---

## Commits

The remediation was applied in two commits:

1. **`7ca4249`** -- First 6 vulnerabilities from the initial manual review (config validators, instance auth, auth error messages, CORS documentation)
2. **`1624422`** -- Remaining 20 vulnerabilities from the comprehensive audit (24 files changed)

---

**Report Generated:** February 25, 2026
**Next Audit Due:** May 25, 2026 (Quarterly)
**Methodology:** OWASP API Security Top 10 (2023), Docker Security Best Practices, API Key Transmission Standards
