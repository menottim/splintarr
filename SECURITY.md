# Security Policy

## Reporting a Vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Instead, use [GitHub Security Advisories](https://github.com/menottim/splintarr/security/advisories/new) to report vulnerabilities privately. This keeps the details confidential until a fix is available.

When reporting, please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce (as specific as possible)
- Affected version(s)
- Any suggested fix, if you have one

## Response Timeline

Splintarr is a solo homelab project maintained in spare time. These are aspirational targets, not contractual commitments:

| Stage | Target |
|-------|--------|
| Acknowledge receipt | 7 days |
| Initial triage and severity assessment | 14 days |
| Fix released | 90 days |

If a report is particularly urgent (e.g., trivially exploitable API key exposure), I will prioritize accordingly.

## Supported Versions

Only the latest release receives security fixes. There are no backports to older versions.

| Version | Supported |
|---------|-----------|
| Latest (currently 1.3.x) | Yes |
| Older releases | No |

## Scope

### In scope

- Authentication or authorization bypass
- API key exposure (Sonarr/Radarr keys stored with Fernet encryption)
- Database encryption bypass (SQLCipher)
- SSRF protection bypass (`core/ssrf_protection.py`)
- Cross-site scripting (XSS) in the web UI
- Session hijacking or JWT token vulnerabilities
- Information disclosure in error responses or logs
- CSRF or cookie security issues

### Out of scope

- **Self-hosted misconfiguration** — exposing the app to the internet without a reverse proxy, using weak secrets, etc. The app is designed for trusted local networks.
- **Denial of service** — this is a single-user, single-worker homelab app. Resource exhaustion is not a meaningful threat model.
- **Vulnerabilities in dependencies** — report these to the upstream project. If a dependency vulnerability affects Splintarr specifically, that is in scope.
- **Issues requiring local/physical access** — if an attacker has shell access to the host, the threat model is already broken.
- **Social engineering** — phishing, credential stuffing, etc.
- **Missing security hardening** — suggestions for improvement are welcome as regular issues, not security reports.

## Disclosure Policy

I follow coordinated disclosure:

1. You report the vulnerability privately via GitHub Security Advisories.
2. I acknowledge, triage, and work on a fix.
3. Once a fix is released, I publish the advisory with details and credit.
4. If 90 days pass without a fix, you are free to disclose publicly.

Reporters are credited in the advisory by default. If you prefer to remain anonymous, let me know in your report.

## Security Model

For full details on Splintarr's security implementation (Argon2id password hashing, JWT session management, SQLCipher database encryption, Fernet API key encryption, SSRF protection, rate limiting, and CSP headers), see the [Security Guide](docs/explanation/security.md).

## AI-Generated Code Disclaimer

This codebase was generated with AI assistance (Claude Code). While it incorporates security best practices and has a comprehensive test suite including dedicated security tests, it has **not been professionally audited**. The security measures are defense-in-depth appropriate for a homelab tool, not guarantees.

If you are a security professional and would like to review the codebase, contributions are especially welcome.
