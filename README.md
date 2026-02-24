# Vibe-Quality-Searcharr

**Version 1.0.0** | Intelligent backlog search automation for Sonarr and Radarr.

---

## ⚠️ **IMPORTANT: AI-Generated Code Warning**

**This entire project was 100% "vibe coded" using AI assistance (Claude Code).** While implementing OWASP Top 10 2025 and NIST security guidelines, this codebase is **NOT production-ready, NOT security-reviewed, and NOT battle-tested**. AI-generated code may contain subtle security flaws, logic errors, cryptographic misuse, race conditions, and authentication bypasses that appear correct but are fundamentally broken.

**Use at your own risk.** Before deploying: conduct a professional security audit, perform penetration testing, review all cryptographic implementations, run static analysis tools (Bandit, Semgrep), deploy in isolated environments with aggressive monitoring, and maintain regular backups. This codebase is intended for **educational purposes only** - learning about Python security patterns, FastAPI architecture, and OWASP mitigation strategies. Do not use for production deployments, sensitive data, critical infrastructure, or internet-accessible services without extensive professional review.

---

## Overview

Vibe-Quality-Searcharr automates systematic backlog searching for missing and upgradeable media in your Sonarr and Radarr instances. It intelligently orchestrates searches over time, respecting API rate limits while maximizing coverage.

### Key Features

- 🔍 **Intelligent Search Scheduling** - Multiple strategies: round-robin, priority-based, aging-based
- 🔒 **Security First** - OWASP Top 10 2025 compliant, encrypted credentials, comprehensive audit logging
- 📊 **Search History Tracking** - Never search the same item twice unnecessarily
- ⚡ **Rate Limit Aware** - Respects indexer API limits to prevent bans
- 🎯 **Multi-Instance Support** - Manage multiple Sonarr/Radarr instances from one interface
- 🔐 **Local Authentication** - Secure password storage with Argon2id hashing
- 📈 **Configuration Drift Detection** - Alerts when Sonarr/Radarr config changes

## Documentation

Documentation is organized following the [Diátaxis](https://diataxis.fr/) framework:

### 📚 Tutorials (Learning-Oriented)
*Step-by-step lessons to get you started*

- **[Getting Started](docs/tutorials/getting-started.md)** - Install and configure your first search queue in 5 minutes

### 🔧 How-To Guides (Problem-Oriented)
*Practical guides for specific tasks*

- **[Deploy with Docker](docs/how-to-guides/deploy-with-docker.md)** - Deploy using Docker and Docker Compose
- **[Deploy to Production](docs/how-to-guides/deploy-production.md)** - Production deployment best practices
- **[Backup and Restore](docs/how-to-guides/backup-and-restore.md)** - Protect and recover your data
- **[Upgrade](docs/how-to-guides/upgrade.md)** - Upgrade to new versions
- **[Troubleshoot](docs/how-to-guides/troubleshoot.md)** - Solve common problems

### 📖 Reference (Information-Oriented)
*Technical descriptions and specifications*

- **[API Reference](docs/reference/api.md)** - Complete REST API documentation
- **[Configuration Reference](docs/reference/configuration.md)** - All configuration options and environment variables
- **[Quality Gates](docs/reference/quality-gates.md)** - Testing and quality standards

### 💡 Explanation (Understanding-Oriented)
*Conceptual guides for deeper understanding*

- **[Architecture](docs/explanation/architecture.md)** - System design and architectural decisions
- **[Security](docs/explanation/security.md)** - Security model and best practices
- **[Search Strategies](docs/explanation/search-strategies.md)** - How different search strategies work

### 📋 Release Information

- **[Release Notes v1.0.0](RELEASE_NOTES.md)** - What's new in v1.0.0
- **[Changelog](CHANGELOG.md)** - Complete version history

## Quick Start

### Prerequisites

- Python 3.13+
- Docker (recommended) or Poetry for local development

### Docker Deployment (Recommended)

```bash
# 1. Clone repository
git clone https://github.com/yourusername/vibe-quality-searcharr.git
cd vibe-quality-searcharr

# 2. Generate secrets
./scripts/generate-secrets.sh

# 3. Start the application
docker-compose up -d

# 4. Access web interface
# Open http://localhost:7337/setup
```

See [Deploy with Docker](docs/how-to-guides/deploy-with-docker.md) for complete instructions.

### Local Development

1. **Install dependencies:**
   ```bash
   poetry install
   ```

2. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env with development configuration
   ```

3. **Initialize database:**
   ```bash
   poetry run alembic upgrade head
   ```

4. **Run development server:**
   ```bash
   poetry run uvicorn src.vibe_quality_searcharr.main:app --reload
   ```

## Security

⚠️ **REMINDER: This is AI-generated code. See disclaimer above.**

Vibe-Quality-Searcharr **attempts to implement** defense-in-depth security features:

- ✅ Argon2id password hashing with 128 MiB memory *(implementation requires audit)*
- ✅ AES-256 database encryption via SQLCipher *(implementation requires audit)*
- ✅ API keys encrypted at rest with pepper stored separately *(implementation requires audit)*
- ✅ HTTP-only, secure, same-site cookies *(implementation requires audit)*
- ✅ JWT token rotation *(implementation requires audit)*
- ✅ Rate limiting on all authentication endpoints *(implementation requires audit)*
- ✅ Comprehensive input validation *(edge cases may exist)*
- ✅ SQL injection prevention via parameterized queries *(usage requires verification)*
- ✅ Security headers (CSP, X-Frame-Options, etc.) *(configuration requires review)*
- ✅ Non-root Docker container with read-only filesystem *(container security requires audit)*

These features are **implemented as specified** but have **NOT been security audited**. The implementation may contain critical vulnerabilities despite following best practice specifications.

See [SECURITY_IMPLEMENTATION.md](SECURITY_IMPLEMENTATION.md) for intended security design.

## Development

### Running Tests

```bash
# All tests with coverage
poetry run pytest

# Security tests only
poetry run pytest tests/security/

# With verbose output
poetry run pytest -v
```

### Code Quality

```bash
# Linting
poetry run ruff check src/

# Type checking
poetry run mypy src/

# Security scanning
poetry run bandit -r src/
poetry run safety check
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
poetry run pre-commit install

# Run manually
poetry run pre-commit run --all-files
```

## Architecture

Vibe-Quality-Searcharr is built with:

- **FastAPI** - Modern async web framework
- **SQLAlchemy** - Type-safe ORM with SQLCipher encryption
- **APScheduler** - Background job scheduling
- **httpx** - Async HTTP client for *arr APIs
- **Argon2** - Password hashing
- **Pydantic** - Input validation

## Contributing

This is primarily a demonstration/educational project. If you find issues or want to improve the codebase:

1. **Security Issues** - Please open a public GitHub issue documenting the vulnerability. Since this is not production software and is clearly marked as requiring security review, responsible disclosure delays are not necessary.
2. **Bugs/Improvements** - Open a pull request with your changes
3. **Code Review** - All contributions welcome, especially from security professionals

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines (if present).

## License

MIT License - Use at your own risk. See LICENSE file for details.

**By using this software, you acknowledge:**
- This is AI-generated code requiring professional security review
- No warranty or guarantee of security or fitness for any purpose
- You assume all responsibility for any use of this software

## Security Vulnerability Reporting

**This project is clearly marked as AI-generated and requiring security review.** If you discover vulnerabilities:

- ✅ **Public Disclosure Welcome** - Open a GitHub issue documenting the vulnerability
- ✅ **Pull Requests Welcome** - Submit fixes via PR
- ✅ **No Embargo Needed** - This is not production software, users are warned

Your findings help improve the codebase and demonstrate where AI code generation falls short!

## Acknowledgments

- 🤖 **100% Generated by Claude Code (Anthropic)** - AI pair programming tool
- 📚 Built with lessons learned from the [Huntarr security incident](https://github.com/rfsbraz/huntarr-security-review)
- 📖 Implements specifications based on OWASP Top 10 2025 best practices
- 📖 Follows specifications from NIST password storage guidelines
- ⚠️ **Implementation correctness NOT verified by human security experts**

## Final Warning

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ⚠️  THIS SOFTWARE IS AI-GENERATED AND UNAUDITED  ⚠️       │
│                                                             │
│  Do NOT use in production without professional security    │
│  audit and extensive testing. You have been warned!        │
│                                                             │
│  Use at your own risk. No warranty provided.               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
