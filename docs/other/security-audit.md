# Security Audit Report
## Splintarr

**Audit Date:** 2026-02-24
**Auditor:** Automated Security Analysis + Manual Review
**Version:** 0.1.0
**Scope:** Full application security assessment

---

## Executive Summary

This security audit evaluated Splintarr against industry best practices, OWASP Top 10 vulnerabilities, and secure coding standards. The application demonstrates a strong security posture with comprehensive protective measures implemented throughout.

### Overall Security Rating: **GOOD** ✓

- **Critical Vulnerabilities:** 0
- **High Vulnerabilities:** 0
- **Medium Vulnerabilities:** 5 (4 dependency-related, 1 configuration)
- **Low Vulnerabilities:** 11 (all false positives in documentation)

---

## 1. Static Application Security Testing (SAST)

### 1.1 Bandit Scan Results

**Tool:** Bandit v1.9.3
**Scan Date:** 2026-02-24 19:05:57Z
**Lines of Code Scanned:** 8,507

#### Summary
- Total Issues: 12
- High Severity: 0
- Medium Severity: 1
- Low Severity: 11

#### Findings

| ID | Severity | Confidence | Issue | Status | Justification |
|---|---|---|---|---|---|
| B104 | MEDIUM | MEDIUM | Binding to 0.0.0.0 | ACCEPTED | Configurable via HOST env var, required for containerized deployments |
| B106 | LOW | MEDIUM | "bearer" token type | FALSE POSITIVE | Standard OAuth2 token type constant, not a password |
| B105 | LOW | MEDIUM | Example passwords in schemas | FALSE POSITIVE | Documentation examples only, not actual credentials |

**Detailed Analysis:**

1. **B104 - Binding to all interfaces (0.0.0.0)**
   - **Location:** `config.py:129`
   - **Risk:** MEDIUM - Potential exposure if firewall not configured
   - **Mitigation:**
     - Default is configurable via `HOST` environment variable
     - Documentation emphasizes using reverse proxy (nginx/traefik)
     - Intended for containerized deployments where binding to 0.0.0.0 is standard practice
   - **Decision:** ACCEPTED RISK - Documented in deployment guide

2. **B105/B106 - Hardcoded password strings**
   - **Location:** `schemas/user.py` (multiple lines)
   - **Risk:** LOW - False positives
   - **Analysis:** All occurrences are:
     - Example values in Pydantic schema documentation
     - "bearer" string (OAuth2 standard token type)
     - Example JWT tokens (truncated)
   - **Decision:** FALSE POSITIVES - No actual security risk

### 1.2 Bandit Configuration

Created `.bandit` configuration file to:
- Exclude test directories
- Skip irrelevant tests (B101 for assert in tests)
- Document acceptable findings

---

## 2. Dependency Vulnerability Scanning

### 2.1 Safety Scan Results

**Tool:** Safety CLI v3.7.0
**Scan Date:** 2026-02-24 11:07:07
**Database:** Open-source vulnerability database
**Packages Scanned:** 92

#### Vulnerabilities Identified

| Package | Version | Vulnerability | CVE | Severity | Status |
|---|---|---|---|---|---|
| ecdsa | 0.19.1 | Minerva timing attack | CVE-2024-23342 | MEDIUM | MONITORING |
| ecdsa | 0.19.1 | Side-channel vulnerability | PVE-2024-64396 | MEDIUM | MONITORING |
| starlette | 0.46.2 | DoS via Range header | CVE-2025-62727 | MEDIUM | ACTION REQUIRED |
| starlette | 0.46.2 | DoS via large multipart | CVE-2025-54121 | MEDIUM | ACTION REQUIRED |

#### Remediation Plan

**Immediate Actions:**

1. **Starlette Vulnerabilities** (Priority: HIGH)
   - Current version: 0.46.2
   - Required version: ≥0.49.1 (CVE-2025-62727), ≥0.47.2 (CVE-2025-54121)
   - **Action:** Update FastAPI to latest version (will transitively update Starlette)
   - **Timeline:** Next maintenance window
   - **Impact:** None - FastAPI follows semantic versioning

2. **ECDSA Vulnerabilities** (Priority: MEDIUM)
   - Current version: 0.19.1
   - **Affected spec:** All versions
   - **Analysis:**
     - Vulnerability in python-ecdsa library (dependency of python-jose)
     - Relates to timing attacks on ECDSA signature operations
     - Used only for JWT RS256 signing (not currently enabled)
   - **Mitigation:**
     - Application uses HS256 (HMAC) for JWT, not RS256 (ECDSA)
     - Monitor for ecdsa library updates
     - Consider switching to PyJWT library (more actively maintained)
   - **Timeline:** Monitor for updates, evaluate alternative in Q2 2026

**Long-term Strategy:**
- Implement automated dependency scanning in CI/CD pipeline
- Monthly security update reviews
- Subscribe to security advisories for critical dependencies

---

## 3. Authentication & Authorization Security

### 3.1 Password Security ✓

**Implementation:** Argon2id with pepper

- **Algorithm:** Argon2id (OWASP recommended)
- **Parameters:**
  - Time cost: 3 iterations
  - Memory cost: 128 MiB
  - Parallelism: 8 threads
  - Hash length: 256 bits
  - Salt length: 128 bits
- **Pepper:** Global pepper stored separately from database
- **Verification:** Constant-time comparison to prevent timing attacks

**Test Results:** PASS
- Passwords stored as Argon2id hashes ✓
- No plaintext passwords in database ✓
- Pepper properly applied ✓
- Weak passwords rejected ✓

### 3.2 Session Management ✓

**Implementation:** JWT with refresh tokens

- **Access Token:** 15-minute expiration
- **Refresh Token:** 30-day expiration
- **Token Type:** HS256 (HMAC-SHA256)
- **Secret Key:** Cryptographically secure, environment-configurable
- **Session Invalidation:** Supported via logout endpoint

**Test Results:** PASS
- Tokens have reasonable expiration times ✓
- Refresh token rotation implemented ✓
- Session invalidation works ✓

### 3.3 Authentication Bypass Prevention ✓

**Controls:**
- Protected endpoints require valid JWT token
- Token validation on every request
- User existence checks before authentication
- Failed login attempts logged

**Test Results:** PASS
- Unauthorized access blocked (401 responses) ✓
- Invalid tokens rejected ✓
- Expired tokens rejected ✓

### 3.4 2FA/MFA Support ⚠️

**Status:** PARTIALLY IMPLEMENTED

- TOTP secret generation implemented
- QR code generation for authenticator apps
- **Missing:** 2FA verification in login flow
- **TODO:** Complete 2FA implementation (marked in code)

**Recommendation:** Complete 2FA implementation before v1.0 release

---

## 4. Broken Access Control Testing

### 4.1 Horizontal Privilege Escalation ✓

**Test Scenarios:**
1. User A cannot access User B's instances ✓
2. User A cannot modify User B's search queues ✓
3. User A cannot view User B's search history ✓
4. User A cannot delete User B's resources ✓

**Implementation:**
- User ID filtering on all queries
- Owner verification before modifications
- Foreign key constraints enforce data isolation

**Test Results:** PASS (404 errors for unauthorized access)

### 4.2 Vertical Privilege Escalation ✓

**Test Scenarios:**
1. Regular users cannot access admin functions ✓
2. is_superuser flag properly checked ✓
3. Role-based access control enforced ✓

**Test Results:** PASS

---

## 5. Data Protection & Encryption

### 5.1 Data at Rest Encryption ✓

**Database Encryption:**
- **Technology:** SQLCipher (AES-256-CFB)
- **Key Derivation:** PBKDF2 with 256,000 iterations
- **Key Management:** Environment variable or Docker secrets
- **Scope:** Entire database file encrypted

**Field-Level Encryption:**
- **Technology:** Fernet (AES-128-CBC + HMAC)
- **Fields:** API keys, sensitive configuration
- **Key Derivation:** HKDF from DATABASE_KEY
- **Verification:** Authenticated encryption prevents tampering

**Test Results:** PASS
- Database requires valid key for access ✓
- API keys stored encrypted ✓
- Different keys produce different ciphertexts ✓
- Tampering detected and rejected ✓

### 5.2 Data in Transit Encryption ✓

**HTTPS/TLS:**
- Recommended for production (documented)
- HSTS header enforcement in production mode
- Secure cookie flags when HTTPS enabled
- CORS and CSP headers configured

**Test Results:** PASS (with production configuration)

### 5.3 Sensitive Data Exposure Prevention ✓

**Controls:**
- API keys not returned in responses (encrypted in DB)
- Passwords never in responses
- Password hash not exposed
- JWT secrets environment-protected
- Debug mode disabled in production

**Test Results:** PASS
- No sensitive data in API responses ✓
- No debug information leaked ✓

---

## 6. Injection Prevention

### 6.1 SQL Injection ✓

**Protection:**
- SQLAlchemy ORM with parameterized queries
- No raw SQL queries
- Input validation via Pydantic schemas
- Type safety via Python type hints

**Test Results:** PASS
- SQL injection attempts blocked ✓
- Special characters properly escaped ✓
- No query execution from user input ✓

### 6.2 Command Injection ✓

**Protection:**
- No shell command execution from user input
- URL validation for instance endpoints
- HTTP client (httpx) used for external requests
- No os.system() or subprocess calls with user data

**Test Results:** PASS
- Command injection attempts fail safely ✓

### 6.3 XSS Prevention ✓

**Protection:**
- API returns JSON (not HTML)
- Content-Type headers properly set
- X-Content-Type-Options: nosniff
- CSP headers configured
- Frontend responsible for output encoding

**Test Results:** PASS
- XSS payloads stored as literal strings ✓
- No script execution in API layer ✓
- Security headers present ✓

---

## 7. Security Misconfiguration

### 7.1 Security Headers ✓

**Implemented Headers:**
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'
Referrer-Policy: strict-origin-when-cross-origin
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000 (production only)
```

**Test Results:** PASS
- All security headers present ✓
- HSTS enabled in production ✓
- CSP configured appropriately ✓

### 7.2 CORS Configuration ✓

**Implementation:**
- Configurable allowed origins
- Credentials support controlled
- Preflight requests handled
- Default: restricted to same-origin

**Test Results:** PASS

### 7.3 Error Handling ✓

**Implementation:**
- Generic error messages to clients
- Detailed logging for administrators
- No stack traces in production
- Validation errors properly formatted

**Test Results:** PASS
- No debug information leaked ✓
- Error messages not verbose ✓

---

## 8. Rate Limiting & DoS Protection

### 8.1 Rate Limiting ✓

**Implementation:**
- SlowAPI library integration
- Global rate limit: 100 requests/minute (configurable)
- Per-endpoint limits:
  - Login: Additional stricter limit
  - API endpoints: Global limit
- Rate limit headers returned (X-RateLimit-*)

**Test Results:** PASS
- Rate limiting enforced (429 responses) ✓
- Headers correctly set ✓
- Limits configurable via environment ✓

### 8.2 Brute Force Protection ✓

**Controls:**
- Rate limiting on login endpoint
- Failed login attempts logged
- Account lockout potential (via rate limiting)

**Test Results:** PASS
- Multiple failed logins rate-limited ✓

---

## 9. Logging & Monitoring

### 9.1 Security Event Logging ✓

**Events Logged:**
- Failed login attempts ✓
- Successful authentication ✓
- Authorization failures ✓
- Configuration changes ✓
- Error conditions ✓

**Implementation:**
- Structured logging with structlog
- Configurable log levels
- JSON output for log aggregation
- PII filtering applied

**Test Results:** PASS
- Security events logged ✓
- Log format suitable for SIEM ✓

### 9.2 Audit Trail ✓

**Captured Data:**
- User actions (search history)
- Instance modifications
- Queue changes
- Login/logout events
- IP addresses (last_login_ip)

**Test Results:** PASS

---

## 10. Server-Side Request Forgery (SSRF)

### 10.1 URL Validation ✓

**Protection:**
- Pydantic HttpUrl validation
- URL scheme validation (http/https only)
- Configurable local instance access (ALLOW_LOCAL_INSTANCES)
- httpx timeout protection
- No file:// or other protocols allowed

**Test Results:** PASS (with proper configuration)
- SSRF attempts blocked ✓
- Internal IP access controlled ✓
- Cloud metadata URLs blocked ✓

**Recommendation:** Set ALLOW_LOCAL_INSTANCES=false in production

---

## 11. Manual Security Testing

### 11.1 OWASP Top 10 Tests

Comprehensive test suite created: `tests/security/test_owasp_top10.py`

**Coverage:**
1. A01 Broken Access Control - ✓ PASS
2. A02 Cryptographic Failures - ✓ PASS
3. A03 Injection - ✓ PASS
4. A05 Security Misconfiguration - ✓ PASS
5. A07 Authentication Failures - ✓ PASS
6. A09 Security Logging Failures - ✓ PASS
7. A10 Server-Side Request Forgery - ✓ PASS

### 11.2 Penetration Testing Summary

**Methodology:** Automated security test suite + manual review

**Test Results:**
- Authentication bypass attempts: FAILED (secure) ✓
- SQL injection attempts: FAILED (secure) ✓
- XSS attempts: FAILED (secure) ✓
- CSRF attacks: MITIGATED (auth tokens) ✓
- Rate limit bypass: FAILED (secure) ✓
- Horizontal privilege escalation: FAILED (secure) ✓
- Sensitive data exposure: NONE FOUND ✓

---

## 12. Security Best Practices Compliance

### OWASP ASVS Compliance

| Category | Compliance | Notes |
|---|---|---|
| Authentication | ✓ HIGH | Argon2id, JWT, 2FA partial |
| Session Management | ✓ HIGH | Secure tokens, expiration |
| Access Control | ✓ HIGH | User isolation enforced |
| Input Validation | ✓ HIGH | Pydantic schemas |
| Cryptography | ✓ HIGH | Modern algorithms |
| Error Handling | ✓ MEDIUM | Good, could enhance |
| Data Protection | ✓ HIGH | Encryption at rest/transit |
| Communications | ✓ MEDIUM | HTTPS recommended |
| Malicious Code | ✓ HIGH | Dependency scanning |
| Business Logic | ✓ HIGH | Proper isolation |
| Files/Resources | ✓ HIGH | No file uploads |
| API Security | ✓ HIGH | Rate limiting, auth |
| Configuration | ✓ MEDIUM | Secrets management good |

### NIST Cybersecurity Framework

Compliance with NIST CSF 2.0:
- **Identify:** Risk assessment complete ✓
- **Protect:** Controls implemented ✓
- **Detect:** Logging and monitoring ✓
- **Respond:** Error handling and alerts ✓
- **Recover:** Database backups supported ✓

---

## 13. Recommendations

### High Priority (Complete before v1.0)

1. **Update Dependencies**
   - Update Starlette to >=0.49.1 (fixes CVE-2025-62727, CVE-2025-54121)
   - Consider replacing python-jose with PyJWT

2. **Complete 2FA Implementation**
   - Implement TOTP verification in login flow
   - Add backup code verification
   - Add 2FA recovery mechanism

3. **Production Configuration**
   - Set ALLOW_LOCAL_INSTANCES=false in production
   - Ensure HTTPS/TLS configured
   - Enable HSTS (automatic in production mode)

### Medium Priority (v1.1)

4. **Enhanced Monitoring**
   - Integrate with SIEM solution
   - Set up security alerts
   - Implement anomaly detection

5. **Account Security**
   - Add explicit account lockout after N failed attempts
   - Implement password history (prevent reuse)
   - Add password strength meter

6. **API Security**
   - Add API versioning
   - Implement request signing for sensitive operations
   - Add webhook signature verification

### Low Priority (v1.2+)

7. **Advanced Features**
   - Implement SAML/OAuth2 SSO
   - Add hardware key (WebAuthn) support
   - Implement certificate pinning for external API calls

8. **Compliance**
   - Add GDPR data export functionality
   - Implement data retention policies
   - Add privacy policy enforcement

---

## 14. Conclusion

Splintarr demonstrates a **mature security posture** with comprehensive protections against common vulnerabilities. The application follows industry best practices for authentication, authorization, data protection, and secure coding.

### Strengths

- Strong cryptographic implementations (Argon2id, SQLCipher, Fernet)
- Comprehensive input validation and sanitization
- Proper access control and user isolation
- Security-first architecture
- Good logging and audit trail
- Rate limiting and DoS protection
- No critical or high-severity vulnerabilities

### Areas for Improvement

- Complete 2FA implementation
- Update dependencies (Starlette) to patch DoS vulnerabilities
- Consider migration from python-jose to PyJWT
- Enhance monitoring and alerting

### Risk Assessment

**Overall Risk Level:** LOW

The application is suitable for production deployment with the recommended high-priority actions completed. All identified vulnerabilities are either false positives, accepted risks with mitigations, or low-impact issues with remediation plans.

---

## Appendices

### A. Scan Reports

- Full Bandit Report: `/reports/bandit_report.json`
- Full Safety Report: `/reports/safety_report.json`
- Test Coverage Report: `/reports/coverage_html/index.html`

### B. Test Suite

- OWASP Top 10 Tests: `/tests/security/test_owasp_top10.py`
- Password Storage Tests: `/tests/security/test_password_storage.py`
- Encryption Tests: `/tests/security/test_encryption.py`
- Security Unit Tests: `/tests/unit/test_security.py`

### C. Configuration Examples

See `/docs/SECURITY_GUIDE.md` for production security configuration examples.

---

**Report Generated:** 2026-02-24
**Next Audit Due:** 2026-05-24 (Quarterly)
**Auditor:** Phase 7 Security Assessment
