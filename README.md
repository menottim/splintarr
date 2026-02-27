<p align="center">
  <img src="src/splintarr/static/img/logo.svg" alt="Splintarr" width="128" height="128" />
</p>

<h1 align="center">Splintarr</h1>

<p align="center"><strong>Version 0.1.0-alpha</strong> | Automated backlog search for Sonarr and Radarr, designed for homelab use.</p>

> **Status: Active Development -- Not Ready for Use**
>
> This project is under active development and is **not a stable or working release**. Many core features are incomplete, untested, or broken. There is significant work remaining before this is ready for others to test. **Do not use this expecting a functional application.**

---

## AI-Generated Code Warning

**This project was 100% "vibe coded" using AI assistance (Claude Code).** This codebase is **NOT production-ready, NOT security-reviewed, and NOT battle-tested**. AI-generated code may contain security flaws, logic errors, and bugs that appear correct but are fundamentally broken.

**Use at your own risk.** This is an **educational project for homelab tinkering only**. Do not expose this application to the internet without extensive professional security review and testing.

### About the Author and Security Approach

I am a **Security Engineering professional** with expertise in infrastructure security and privacy engineering. At this stage of my career, I spend most of my time leading teams rather than writing code. While I have a solid understanding of software development practices and security principles, I am **not an expert Security Software Engineer**.

During this vibe-coding exercise, I made every effort to implement security best practices by drawing on my professional knowledge. However, there is a **significant difference** between understanding security principles and correctly implementing them in code. The combination of AI-generated code, implementation by a security professional rather than a specialized secure development expert, and lack of professional security code review means this codebase should be treated as an educational exercise, not production software.

---

## Table of Contents

- [Overview](#overview)
- [Screenshots](#screenshots)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Architecture Overview](#architecture-overview)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Splintarr automates systematic backlog searching for missing and upgradeable media in your Sonarr and Radarr instances. It runs as a Docker container on your home network and intelligently schedules searches over time, respecting API rate limits while maximizing coverage.

### Who This Is For

This tool is designed for **homelab enthusiasts** running personal Sonarr and Radarr instances who want to automate search optimization in their home environment.

### Key Features

- **Intelligent Search Scheduling** -- Multiple strategies including round-robin, priority-based, and aging-based
- **Search History Tracking** -- Avoids searching the same item twice unnecessarily
- **Rate Limit Aware** -- Respects indexer API limits to prevent bans
- **Multi-Instance Support** -- Manage multiple Sonarr and Radarr instances from one interface
- **Local Authentication** -- Secure password storage with Argon2id hashing
- **Configuration Drift Detection** -- Alerts when Sonarr or Radarr configuration changes
- **Encrypted Database** -- AES-256 encryption via SQLCipher

---

## Screenshots

### Dashboard

![Dashboard — overview of search queues, recent activity, and system status](docs/images/dashboard.png)

### Instance Management

![Add Instance — connect Sonarr or Radarr with URL and API key](docs/images/instances.png)

### Search Queue Creation

![Create Search Queue — choose instance, strategy, and schedule](docs/images/search-queues.png)

### Settings

![Settings — account info, password management, 2FA, and session control](docs/images/settings.png)

### Login

![Login — secure authentication with optional two-factor support](docs/images/login.png)

---

## Quick Start

### Windows

See the **[Windows Quick Start Guide](docs/how-to-guides/windows-quick-start.md)** for step-by-step instructions.

### Linux / macOS

See the **[Docker Deployment Guide](docs/how-to-guides/deploy-with-docker.md)** for complete instructions.

**Short version:**

```bash
git clone https://github.com/menottim/splintarr.git
cd splintarr
./scripts/generate-secrets.sh
docker-compose up -d
```

Then open **http://localhost:7337/setup** to complete the setup wizard.

After installation, see the **[Getting Started Tutorial](docs/tutorials/getting-started.md)** for a walkthrough of the setup wizard, dashboard, and creating your first search queue.

---

## Documentation

Documentation is organized following the [Diataxis](https://diataxis.fr/) framework:

### Tutorials (Learning-Oriented)

- **[Getting Started](docs/tutorials/getting-started.md)** -- Post-install walkthrough: setup wizard, dashboard, first search queue

### How-To Guides (Problem-Oriented)

- **[Windows Quick Start](docs/how-to-guides/windows-quick-start.md)** -- Install and run on Windows with Docker Desktop
- **[Deploy with Docker](docs/how-to-guides/deploy-with-docker.md)** -- Deploy using Docker and Docker Compose on Linux/macOS
- **[Backup and Restore](docs/how-to-guides/backup-and-restore.md)** -- Protect and recover your data
- **[Upgrade](docs/how-to-guides/upgrade.md)** -- Upgrade to new versions
- **[Troubleshoot](docs/how-to-guides/troubleshoot.md)** -- Solve common problems

### Reference (Information-Oriented)

- **[API Reference](docs/reference/api.md)** -- Complete REST API documentation
- **[Configuration Reference](docs/reference/configuration.md)** -- All configuration options and environment variables
- **[Quality Gates](docs/reference/quality-gates.md)** -- Testing and quality standards

### Explanation (Understanding-Oriented)

- **[Architecture](docs/explanation/architecture.md)** -- System design and architectural decisions
- **[Security](docs/explanation/security.md)** -- Security model and implementation details
- **[Search Strategies](docs/explanation/search-strategies.md)** -- How different search strategies work

### Release Information

- **[Release Notes v0.1.0-alpha](RELEASE_NOTES.md)** -- What is in this alpha release
- **[Changelog](CHANGELOG.md)** -- Complete version history

---

## Architecture Overview

Splintarr is built with:

- **FastAPI** -- Async web framework serving the UI and REST API
- **SQLAlchemy + SQLCipher** -- ORM with encrypted database storage
- **APScheduler** -- Background job scheduling for search queues
- **httpx** -- Async HTTP client for communicating with Sonarr and Radarr APIs
- **Argon2id** -- Password hashing
- **Pydantic** -- Input validation and configuration management

The application runs as a single Docker container with a SQLite/SQLCipher database stored in a mounted volume. See **[Architecture](docs/explanation/architecture.md)** for the full design.

---

## Development

### Running Tests

```bash
poetry install
poetry run pytest

# Security tests only
poetry run pytest tests/security/

# With verbose output
poetry run pytest -v
```

### Code Quality

```bash
poetry run ruff check src/
poetry run mypy src/
poetry run bandit -r src/
```

---

## Contributing

This is primarily a demonstration and educational project. Contributions are welcome:

- **Security Issues** -- Open a public GitHub issue. Since this is not production software, responsible disclosure delays are not necessary.
- **Bugs and Improvements** -- Open a pull request with your changes.
- **Code Review** -- All contributions welcome, especially from security professionals.

## License

MIT License -- Use at your own risk. See LICENSE file for details.

**By using this software, you acknowledge:**
- This is AI-generated code requiring professional security review
- No warranty or guarantee of security or fitness for any purpose
- You assume all responsibility for any use of this software

## Acknowledgments

- **100% Generated by Claude Code (Anthropic)** -- AI pair programming tool
- Built with lessons learned from the [Huntarr security incident](https://github.com/rfsbraz/huntarr-security-review)
- Implements specifications based on OWASP Top 10 2025 and NIST password storage guidelines
- **Implementation correctness NOT verified by human security experts**
