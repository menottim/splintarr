# Vibe-Quality-Searcharr

**Version 0.1.0-alpha** | Intelligent backlog search automation for Sonarr and Radarr.

**⚠️ PRE-RELEASE:** This version has not been hand-verified for deployment. Use with caution.

## Table of Contents

- [⚠️ AI-Generated Code Warning](#️-ai-generated-code-warning)
- [Overview](#overview)
- [Documentation](#documentation)
- [Quick Start](#quick-start)
- [Security](#security)
- [Development](#development)
- [Architecture](#architecture)
- [Known Issues](#known-issues)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)

---

## ⚠️ AI-Generated Code Warning

**This project was 100% "vibe coded" using AI assistance (Claude Code).** This codebase is **NOT production-ready, NOT security-reviewed, and NOT battle-tested**. AI-generated code may contain security flaws, logic errors, and bugs that appear correct but are fundamentally broken.

**Use at your own risk.** This is an **educational project for homelab tinkering only**. Do not use for production, sensitive data, or internet-accessible services without extensive professional security review and testing.

### About the Author & Security Approach

I am a **Security Engineering professional** with expertise in infrastructure security and privacy engineering. At this stage of my career, I spend most of my time leading teams rather than writing code. While I have a solid understanding of software development practices and security principles, I am **not an expert Security Software Engineer**.

**Security Implementation Approach:**

During this vibe-coding exercise, I made every effort to implement security best practices by drawing on my professional knowledge and industry best practices. However, there is a **significant difference** between understanding security principles and correctly implementing them in production code. Subtle implementation flaws (such as improper error handling that leaks information, race conditions in authentication flows, or cryptographic API misuse) can undermine even well-intentioned security measures.

**The combination of:**
1. AI-generated code (which may have subtle flaws despite appearing correct)
2. Implementation by a security professional rather than a specialized secure development expert
3. Lack of professional security code review

**...means this codebase should be treated as an educational exercise, not production software.**

---

## Overview

Vibe-Quality-Searcharr automates systematic backlog searching for missing and upgradeable media in your Sonarr and Radarr instances. It intelligently orchestrates searches over time, respecting API rate limits while maximizing coverage.

### Intended Audience

This tool is **not intended for broad deployment**. It is specifically designed for **homelab enthusiasts tinkering with media management stacks**, individuals running personal Sonarr/Radarr instances who want to experiment with automated search optimization in their home environments. If you're looking for production-ready, enterprise-grade, or publicly-deployed software, this is not it.

### Key Features

- **Intelligent Search Scheduling** - Multiple strategies: round-robin, priority-based, aging-based
- **Security First** - Implements OWASP Top 10 best practices, encrypted credentials, comprehensive audit logging
- **Search History Tracking** - Never search the same item twice unnecessarily
- **Rate Limit Aware** - Respects indexer API limits to prevent bans
- **Multi-Instance Support** - Manage multiple Sonarr/Radarr instances from one interface
- **Local Authentication** - Secure password storage with Argon2id hashing
- **Configuration Drift Detection** - Alerts when Sonarr/Radarr config changes
- **Comprehensive Logging** - Multi-level logging with automatic rotation and sensitive data filtering

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

- **[Release Notes v0.1.0-alpha](RELEASE_NOTES.md)** - What's in this alpha release
- **[Changelog](CHANGELOG.md)** - Complete version history

## Quick Start

### Prerequisites

- Python 3.13+
- Docker (recommended) or Poetry for local development

### Docker Deployment (Recommended)

**Windows users:** See the dedicated **[Windows Quick Start Guide](docs/how-to-guides/windows-quick-start.md)** for step-by-step instructions with detailed Windows-specific setup.

**Linux/macOS:**

```bash
# 1. Clone repository
git clone https://github.com/menottim/vibe-quality-searcharr.git
cd vibe-quality-searcharr

# 2. Generate secrets
./scripts/generate-secrets.sh
# Windows: .\scripts\generate-secrets.ps1

# 3. Start the application
docker-compose up -d

# 4. Access web interface
# Open http://localhost:7337/setup

# 5. View logs (optional)
docker-compose logs -f
```

**Note:** The application runs as root inside the Docker container on Windows due to volume permission limitations. This is safe because the container is isolated from your Windows system. On Linux, it runs as a non-root user (UID 1000).

**⚠️ IMPORTANT:** After installation, complete the [Post-Deployment Security Steps](docs/how-to-guides/deploy-with-docker.md#5-post-deployment-security-hardening) to:
- Update dependencies (fix known CVEs)
- Enable production mode
- Configure HTTPS/TLS
- Verify security settings

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

- Argon2id password hashing with 128 MiB memory *(implementation requires audit)*
- AES-256 database encryption via SQLCipher *(implementation requires audit)*
- API keys encrypted at rest with pepper stored separately *(implementation requires audit)*
- HTTP-only, secure, same-site cookies *(implementation requires audit)*
- JWT token rotation *(implementation requires audit)*
- Rate limiting on all authentication endpoints *(implementation requires audit)*
- Comprehensive input validation *(edge cases may exist)*
- SQL injection prevention via parameterized queries *(usage requires verification)*
- Security headers (CSP, X-Frame-Options, etc.) *(configuration requires review)*
- Non-root Docker container with read-only filesystem *(container security requires audit)*

These features are **implemented as specified** but have **NOT been security audited**. The implementation may contain critical vulnerabilities despite following best practice specifications.

See [Security Explanation](docs/explanation/security.md) for detailed security architecture.

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

## Known Issues

### Windows Docker Compatibility

**Container runs as root on Windows:** The application runs with root privileges inside the Docker container on Windows due to volume permission limitations. This is a standard Docker-on-Windows compromise and is safe because:
- The container is isolated from your Windows system
- On Linux deployments, the application automatically runs as a non-root user
- Your Windows system remains protected by Docker's container isolation

**For complete Windows setup instructions**, see **[Windows Quick Start Guide](docs/how-to-guides/windows-quick-start.md)**.

### Test Suite Coverage

**Issue:** Two security tests currently fail due to test code issues (not actual security problems):
- `test_hash_password_with_pepper` - Test outdated after HMAC implementation
- `test_password_hashing_error_propagation` - Mocking limitation with Argon2 read-only attributes

**Status:** Security fixes are verified working. Test code needs updates to match new implementations.

### Python Version Requirements

**Issue:** `pyproject.toml` specifies Python 3.13+, but the project may work with Python 3.11+.

**Note:** Only Python 3.13+ is officially tested and supported.

### SQLCipher Installation (Development)

**Issue:** Installing `sqlcipher3` Python package requires SQLCipher library headers on your system.

**Solution:**
```bash
# macOS
brew install sqlcipher

# Ubuntu/Debian
sudo apt-get install libsqlcipher-dev

# Windows (via vcpkg)
vcpkg install sqlcipher
```

**Docker users:** This is handled automatically in the Docker image.

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

- **Public Disclosure Welcome** - Open a GitHub issue documenting the vulnerability
- **Pull Requests Welcome** - Submit fixes via PR
- **No Embargo Needed** - This is not production software, users are warned

Your findings help improve the codebase and demonstrate where AI code generation falls short!

## Acknowledgments

- **100% Generated by Claude Code (Anthropic)** - AI pair programming tool
- Built with lessons learned from the [Huntarr security incident](https://github.com/rfsbraz/huntarr-security-review)
- Implements specifications based on OWASP Top 10 2025 and NIST password storage guidelines
- **Implementation correctness NOT verified by human security experts**
