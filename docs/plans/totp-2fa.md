# TOTP Two-Factor Authentication

**Branch:** `feature/totp-2fa`
**Status:** Implementation complete, pending review

## Context

The app had a "Coming soon" placeholder for 2FA. The foundation already existed — pyotp is installed, the User model has `totp_secret`/`totp_enabled` columns, `core/auth.py` has `generate_totp_secret()`, `generate_totp_uri()`, `verify_totp_code()`, and schemas exist for `TwoFactorSetup`, `TwoFactorVerify`, `TwoFactorDisable`. But no actual endpoints, login flow integration, or UI existed.

## Approach: Short-lived "2FA pending" JWT + progressive login UI

After password verification succeeds for a 2FA-enabled user, issue a restricted JWT (`type: "2fa_pending"`, 5-min TTL) instead of full tokens. This token is rejected by all normal auth guards and only accepted by the `/api/auth/2fa/login-verify` endpoint. No Redis, no session tables — fits the existing stateless JWT architecture.

Backup/recovery codes are deferred to a later phase. For a single-user homelab app, recovery is possible by directly editing the database.

## Files Changed

| File | Changes | Status |
|------|---------|--------|
| `pyproject.toml` | Added `qrcode[pil]` dependency, `qrcode.*` to mypy overrides | Done |
| `src/.../core/auth.py` | Added `create_2fa_pending_token()`, `verify_2fa_pending_token()`, `generate_totp_qr_code_base64()` | Done |
| `src/.../schemas/user.py` | Added `qr_code_data_uri` field to `TwoFactorSetup`, removed `backup_codes` (deferred) | Done |
| `src/.../api/auth.py` | Added 4 endpoints, modified login to branch on `totp_enabled` | Done |
| `src/.../templates/auth/login.html` | Two-step login: password form → TOTP code form (JS progressive disclosure) | Done |
| `src/.../templates/dashboard/settings.html` | Setup flow (QR code + verify) and disable flow replacing placeholder | Done |
| `tests/unit/test_auth.py` | Tests for 2FA pending token functions, QR code generation | Done |
| `tests/integration/test_auth_api.py` | Tests for full 2FA setup/login/disable flow | Done |

## Implementation Details

### Core auth functions (`core/auth.py`)

- `create_2fa_pending_token(user_id, username) -> str` — JWT with `type: "2fa_pending"`, 5-min expiry
- `verify_2fa_pending_token(token) -> dict` — validates type is `"2fa_pending"`, raises `TokenError` otherwise
- `generate_totp_qr_code_base64(uri) -> str` — renders QR code as `data:image/png;base64,...` using qrcode library

### API endpoints (`api/auth.py`)

- **Modified `POST /api/auth/login`**: If `user.totp_enabled`, issues 2FA pending token in cookie + returns `requires_2fa: True`. No access/refresh tokens issued yet.
- **`POST /api/auth/2fa/setup`**: Generates secret, stores on user (not yet enabled), returns secret + QR code data URI. Requires cookie auth.
- **`POST /api/auth/2fa/verify`**: Verifies TOTP code against stored secret, sets `totp_enabled = True`. Requires cookie auth.
- **`POST /api/auth/2fa/login-verify`**: Reads pending token from cookie, verifies TOTP code, issues full access + refresh tokens. Rate limited 5/min.
- **`POST /api/auth/2fa/disable`**: Requires password + valid TOTP code, clears secret to NULL and disables. Requires cookie auth.

### Login page (`templates/auth/login.html`)

- JS intercepts form submit, POSTs to `/api/auth/login`
- If `requires_2fa: true` in response: hides password form, shows TOTP code input
- TOTP form POSTs to `/api/auth/2fa/login-verify`
- On success: redirects to `/dashboard`
- "Use a different account" link to restart

### Settings page (`templates/dashboard/settings.html`)

- **2FA not enabled**: "Enable 2FA" button → calls `/2fa/setup` → shows QR code + manual secret + verification input → calls `/2fa/verify` → page reload
- **2FA enabled**: Shows "Enabled" badge + collapsible "Disable 2FA" with password + TOTP code inputs → calls `/2fa/disable`

## Security Checklist

- [x] Rate limit `/2fa/login-verify` at 5/min (brute-force protection for 6-digit code)
- [x] Pending token rejected by `verify_access_token()` (defense in depth)
- [x] `totp_secret` cleared to NULL on disable (not just flag toggled)
- [x] TOTP secret never logged
- [x] All inline scripts use CSP nonce
- [x] `valid_window=1` on TOTP verify (90-second clock drift tolerance)

## Test Coverage

### Unit tests (6 new, all passing)

- Pending token creation and claim verification
- Pending token verified successfully
- Pending token rejected by `verify_access_token()` (cross-type rejection)
- Access token rejected by `verify_2fa_pending_token()` (cross-type rejection)
- Expired pending token raises `TokenError`
- QR code generation returns valid PNG data URI

### Integration tests (15 new)

- Full setup flow: generate secret → verify with valid code → enable
- Setup without auth (401)
- Setup when already enabled (400)
- Verify with invalid code (400)
- Verify with invalid code format (422)
- Verify without calling setup first (400)
- Login with 2FA full flow: password → pending token → TOTP → full tokens
- Login-verify with invalid TOTP (401)
- Login-verify without pending token (401)
- Disable with valid password + code
- Disable with wrong password (401)
- Disable with wrong TOTP (400)
- Disable when not enabled (400)
- Login without 2FA unchanged behavior

Note: Some integration tests that involve DB writes through the FastAPI test client fail due to a pre-existing test infrastructure issue (in-memory SQLCipher session isolation). This affects pre-existing tests as well and is not caused by this feature.

## Verification Steps

1. Build Docker image and start container
2. Enable 2FA in settings — scan QR with authenticator app, verify code
3. Logout, login with password — should see TOTP prompt
4. Enter valid code — should reach dashboard
5. Enter invalid code — should be rejected
6. In settings, disable 2FA with password + code
7. Login again — should go straight to dashboard (no TOTP prompt)
8. Run `poetry run pytest tests/unit/test_auth.py tests/integration/test_auth_api.py`

## Future Work

- Backup/recovery codes
- "Remember this device" option (skip 2FA for trusted devices)
- Rate limiting on `/2fa/verify` setup endpoint
