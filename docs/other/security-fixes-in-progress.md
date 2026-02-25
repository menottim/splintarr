# Security Fixes - In Progress

**Started:** 2026-02-24
**Status:** 4 of 15 vulnerabilities fixed

## ✅ Completed Fixes

### 🔴 CRITICAL Issues Fixed (3/3)

#### 1. Weak Fernet Key Derivation - **FIXED**
**File:** `src/vibe_quality_searcharr/core/security.py`

**Changes:**
- Replaced weak `key_bytes = secret_key.encode()[:32].ljust(32, b"0")` with proper HKDF
- Now uses `cryptography.hazmat.primitives.kdf.hkdf.HKDF` with SHA256
- Application-specific salt: `b"vibe-quality-searcharr-fernet-v1"`
- Context-specific info: `b"api-key-encryption"`
- Prevents weak keys even when SECRET_KEY is short

**Impact:** Eliminates critical vulnerability where 50% of encryption key could be known plaintext

---

#### 2. JWT Algorithm Confusion - **FIXED**
**File:** `src/vibe_quality_searcharr/core/auth.py`

**Changes:**
- Added hardcoded `ALLOWED_JWT_ALGORITHMS = ["HS256"]` constant
- Updated all `jwt.encode()` calls to use `ALLOWED_JWT_ALGORITHMS[0]`
- Updated `verify_access_token()` and `verify_refresh_token()` to:
  - Use hardcoded algorithm whitelist instead of config
  - Explicitly verify token header algorithm with `jwt.get_unverified_header()`
  - Reject any token with algorithm not in whitelist
- Prevents 'none' algorithm and other algorithm confusion attacks

**Impact:** Eliminates authentication bypass via algorithm confusion

---

#### 3. SQL Injection in Database URL - **FIXED**
**File:** `src/vibe_quality_searcharr/config.py`

**Changes:**
- Added `@field_validator("database_cipher")` with whitelist:
  - Allowed: `aes-256-cfb`, `aes-256-cbc`, `aes-128-cfb`, `aes-128-cbc`
  - Rejects any other value with clear error message
- Added `@field_validator("database_kdf_iter")` with range validation:
  - Minimum: 64,000 (security)
  - Maximum: 10,000,000 (DoS prevention)
  - Validates type is integer
- Updated `get_database_url()` to use `urllib.parse.urlencode()`
- Added upper bound `le=10000000` to Field definition

**Impact:** Prevents SQL injection via environment variable manipulation

---

### 🟠 HIGH Issues Fixed (1/5)

#### 4. Non-Functional 2FA Removed - **FIXED**
**File:** `src/vibe_quality_searcharr/api/auth.py`

**Changes:**
- Removed three non-functional endpoints:
  - `POST /api/auth/2fa/setup`
  - `POST /api/auth/2fa/verify`
  - `POST /api/auth/2fa/disable`
- Removed unused imports:
  - `generate_totp_secret`, `generate_totp_uri`, `verify_totp_code`
  - `TwoFactorSetup`, `TwoFactorVerify`, `TwoFactorDisable` schemas
- Updated login endpoint to remove misleading TODO comments
- Added clear note explaining 2FA is not implemented

**Impact:** Eliminates false security claims and user confusion

---

## 🚧 In Progress

### 🟠 HIGH Issues Remaining (4/5)

- [ ] Task #13: SSRF protection in instance URLs
- [ ] Task #14: Timing attack in password pepper concatenation
- [ ] Task #15: Rate limiting bypass via distributed attacks
- [ ] (Already completed above)

### 🟡 MEDIUM Issues Remaining (4/4)

- [ ] Task #16: Password complexity requirements
- [ ] Task #17: Session fixation vulnerability
- [ ] Task #18: IDOR in API endpoints
- [ ] Task #19: Missing CSRF protection

### 🔵 LOW Issues Remaining (3/3)

- [ ] Task #20: Verbose error messages
- [ ] Task #21: API documentation exposure (already secure, needs documentation)
- [ ] Task #22: Weak default max failed logins

---

## Next Steps

Continue with remaining HIGH-priority issues:
1. Add SSRF protection for Sonarr/Radarr URLs
2. Fix timing attack in password pepper
3. Add Redis support for rate limiting
4. Then proceed to MEDIUM and LOW priority issues

---

**Estimated Completion:** Working through remaining 11 issues
**Testing Required:** After all fixes complete, run test suite and manual verification
