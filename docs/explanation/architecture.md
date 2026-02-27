# Architecture

Understanding the architectural decisions and design philosophy behind Splintarr.

## Design Philosophy

Splintarr is built on three core principles:

1. **Security First** - Defense-in-depth security approach with encryption at rest, secure password storage, and comprehensive input validation
2. **Simplicity Over Complexity** - Pragmatic choices favoring maintainability and clarity over premature optimization
3. **Docker-First Deployment** - Containerized architecture designed for easy deployment and isolation

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         User Browser                         │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS
┌────────────────────────┴────────────────────────────────────┐
│                     FastAPI Application                      │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Web UI (Jinja2 Templates + Minimal JavaScript)       │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  REST API (FastAPI Routes + Pydantic Validation)      │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Business Logic (Search Strategies, Scheduling)       │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Data Access Layer (SQLAlchemy ORM)                   │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────┬─────────────────────────┬────────────────────┘
              │                         │
              │ Encrypted               │ HTTPS with API Key
              ▼                         ▼
  ┌───────────────────────┐  ┌─────────────────────────────┐
  │ SQLite + SQLCipher    │  │  Sonarr/Radarr Instances   │
  │ (Encrypted Database)  │  │  (External Services)        │
  └───────────────────────┘  └─────────────────────────────┘
```

## Technology Stack

### Why Python?

Python was chosen for its exceptional security library ecosystem and development velocity:

- **Cryptography Libraries**: Industry-leading implementations (`argon2-cffi`, `cryptography`, `sqlcipher3`)
- **Development Speed**: Rapid prototyping for CRUD applications with minimal boilerplate
- **Mature Ecosystem**: Battle-tested libraries for HTTP clients, scheduling, and async operations
- **Type Safety**: Modern type hints provide safety without compilation overhead
- **Docker Compatibility**: Official slim images are compact and reliable

### Why FastAPI?

FastAPI provides the perfect balance of performance, security, and developer experience:

**Async by Default**: Native async/await support enables concurrent API calls to multiple Sonarr/Radarr instances without blocking

**Automatic Validation**: Pydantic integration validates all input at the API boundary, preventing injection attacks and malformed data

**Self-Documenting**: OpenAPI schema generation provides automatic, always-accurate API documentation

**Modern Python**: Built on type hints, enabling excellent IDE support and catching errors before runtime

**Security Built-In**: Dependency injection makes authentication and authorization straightforward and type-safe

## Data Layer

### Why SQLite + SQLCipher?

SQLite with SQLCipher encryption provides an ideal solution for single-server deployments:

**Zero Administration**: Serverless architecture eliminates database setup, maintenance, and networking concerns

**Transparent Encryption**: SQLCipher provides AES-256 encryption with zero application-level complexity

**File-Based Storage**: Backups are as simple as copying a single file

**ACID Compliance**: Full transactional support without coordination overhead

**Performance**: Adequate for thousands of items with sub-millisecond query times

**Security**: No network attack surface, encrypted at rest, in-memory operation support

**Reliable Connection Handling**: Custom connection creator ensures encryption settings are applied correctly on all platforms, including Windows

**Trade-offs**: Not suitable for:
- Multi-server deployments (no concurrent write access)
- Massive scale (millions of records)
- Geographic distribution

For future scaling, the SQLAlchemy abstraction allows migration to PostgreSQL with minimal code changes.

### SQLCipher Connection Architecture

The application uses a custom connection creator to ensure proper encryption:

**Connection Initialization:**
1. Creates raw SQLite connection
2. Immediately sets `PRAGMA key` with encryption key
3. Configures cipher settings (aes-256-cfb)
4. Sets KDF iterations (256,000)
5. Only then allows database operations

This approach fixes the "unable to open database file" error that occurred on Windows and ensures encryption is properly configured before any database access.

### Database Schema Design

**Users Table**: Local authentication with Argon2id password hashes

**Instances Table**: Sonarr/Radarr connections with Fernet-encrypted API keys

**Search Queues Table**: Scheduled search configuration with cron expressions

**Search History Table**: Audit log preventing duplicate searches within cooldown period

The schema follows normal form principles while maintaining query performance through strategic denormalization where justified (e.g., caching instance configuration snapshots for drift detection).

## Frontend Architecture

### Server-Side Rendering Choice

The UI uses server-side rendering rather than a single-page application framework:

**Security Simplification**: No CORS complexity, reduced JavaScript attack surface

**Progressive Enhancement**: Core functionality works without JavaScript

**Performance**: Faster initial page load, no large JavaScript bundle

**Simplicity**: No build pipeline, no state management libraries

**Appropriate Scope**: Technical dashboard doesn't require SPA complexity

### Minimal JavaScript Philosophy

JavaScript is used sparingly and progressively:

- **Form Validation**: Client-side validation for UX, server-side for security
- **Dynamic Updates**: Optional polling or WebSocket for live status updates
- **Interactive Elements**: Collapsible sections, modal dialogs, tooltips

The application remains fully functional with JavaScript disabled.

## Security Architecture

### Defense in Depth

Security is implemented in layers:

**Layer 1 - Transport**: HTTPS with HSTS, secure cookies

**Layer 2 - Network**: Rate limiting, CORS controls, CSP headers

**Layer 3 - Authentication**: Argon2id password hashing, JWT tokens, optional 2FA

**Layer 4 - Authorization**: Role-based access control, resource ownership validation

**Layer 5 - Data**: Encrypted credentials (Fernet), encrypted database (SQLCipher)

**Layer 6 - Input**: Pydantic validation, parameterized queries, output encoding

**Layer 7 - Logging**: Sanitized logs, security event tracking

### Encryption Strategy

**Passwords**: Never stored, only Argon2id hashes with unique salts and pepper

**API Keys**: Fernet encryption (AES-128-CBC + HMAC) with pepper-derived key

**Database**: SQLCipher AES-256-CFB full-disk encryption

**Secrets**: Docker secrets or file-based secrets, never in environment variables

**Justification**: Multiple encryption layers prevent single-point-of-failure scenarios. Even with database access, attackers cannot retrieve API keys without the pepper.

## Scheduling Architecture

### APScheduler Design

Background job processing uses APScheduler for its flexibility and reliability:

**Job Store**: SQLite-based persistence ensures jobs survive restarts

**Execution**: Async execution prevents blocking the API server

**Coalescing**: Prevents duplicate job execution if system was offline

**Timezone Support**: Respects user-configured timezones for scheduling

**Misfire Handling**: Grace periods prevent job pile-up after downtime

**Shared Database Connection**: Scheduler uses the same encrypted database connection as the main application via `get_engine()`, ensuring all operations benefit from SQLCipher encryption

### Search Queue Processing

Search queues operate independently:

1. **Scheduler triggers** job at configured time
2. **Queue processor** fetches items based on strategy
3. **Rate limiting** ensures indexer limits respected
4. **Search execution** calls Sonarr/Radarr API asynchronously
5. **History recording** prevents duplicate searches
6. **Error handling** retries with exponential backoff

This decoupled design allows multiple queues to run concurrently while respecting system-wide rate limits.

## HTTP Client Architecture

### Async HTTP with httpx

The httpx library provides robust async HTTP client functionality:

**Connection Pooling**: Reuses connections to reduce overhead

**Timeout Controls**: Prevents hung connections to misbehaving services

**Retry Logic**: Exponential backoff with jitter for transient failures

**HTTP/2 Support**: Efficient multiplexing when supported

### Service Integration

Each external service (Sonarr, Radarr) has a dedicated client class:

```python
class SonarrClient:
    """Encapsulates Sonarr API communication."""

    async def get_wanted_missing(self) -> List[MissingItem]:
        """Fetch missing episodes."""

    async def search_items(self, ids: List[int]) -> None:
        """Trigger search for specific items."""

    async def get_system_status(self) -> SystemStatus:
        """Health check and version info."""
```

This abstraction:
- Centralizes API key handling
- Provides consistent error handling
- Enables easy mocking for tests
- Allows API version migration

## Configuration Management

### Twelve-Factor Methodology

Configuration follows twelve-factor app principles:

**Environment Variables**: All configuration via env vars

**Secrets Management**: Docker secrets for production, files for development

**Environment Parity**: Same code runs in all environments

**Config Validation**: Pydantic validates configuration on startup

**Fail Fast**: Invalid configuration prevents startup

### Configuration Hierarchy

1. **Default values** in `Settings` class
2. **Environment variables** from shell or Docker
3. **Secret files** mounted by Docker
4. **Runtime overrides** for testing only

This hierarchy provides sensible defaults while allowing secure production configuration.

## Deployment Architecture

### Container Design

The Docker image follows best practices:

**Multi-Stage Build**: Separates build dependencies from runtime

**Conditional User Switching**: Application runs as unprivileged user (UID 1000) on Linux, but as root on Windows to handle volume permission issues

**Minimal Base**: python:3.13-slim for security and size

**Read-Only Filesystem**: Only /data and /data/logs are writable

**Health Checks**: Kubernetes-compatible health endpoints

**Windows Compatibility**: Automatic detection and handling of Windows-specific Docker limitations, including volume permissions and line endings

### Logging Infrastructure

The application includes a comprehensive logging system:

**Multiple Log Files**: Separate files for all messages, errors only, and debug output

**Automatic Rotation**: Logs rotate at 10MB with 5 backups (50MB max per log type)

**Sensitive Data Filtering**: Automatic redaction of passwords, keys, and tokens

**Configurable Verbosity**: Five log levels from DEBUG to CRITICAL

**Location**: All logs stored in `/data/logs/` directory for easy access and backup

### Volume Strategy

**Persistent Data**: `/data` volume stores database and logs

**Secret Management**: `/run/secrets` for Docker secrets

**Configuration**: Environment variables, not mounted files

This separation enables:
- Easy backups (copy /data)
- Secret rotation (restart with new secrets)
- Stateless containers (all state in volumes)

## Testing Strategy

### Test Pyramid

**Unit Tests (60%)**: Fast, isolated tests of business logic

**Integration Tests (30%)**: API endpoint tests with database

**Security Tests (10%)**: OWASP Top 10 validation, penetration testing

### Test Isolation

Each test:
- Uses in-memory SQLite database
- Mocks external HTTP calls
- Resets state before and after
- Runs in parallel when possible

### Security Testing

Continuous security validation:

- **Static Analysis**: Bandit for code patterns
- **Dependency Scanning**: Safety for vulnerable packages
- **Input Fuzzing**: Property-based testing with Hypothesis
- **OWASP Coverage**: Tests for each Top 10 category

## Performance Characteristics

### Expected Scale

Designed for typical home media server scale:

- **Instances**: 1-20 Sonarr/Radarr instances
- **Library Size**: 1,000-50,000 items per instance
- **Search Operations**: 100-1,000 searches per day
- **Users**: 1-5 concurrent users

### Performance Profile

**Database Queries**: <10ms for typical queries

**API Response**: <100ms for dashboard rendering

**Search Execution**: 1-5 seconds per search operation

**Memory Usage**: 100-200 MB baseline, +50 MB per active search queue

**CPU Usage**: Minimal (<5% average), spikes during search operations

### Optimization Strategy

Performance optimization follows the "measure first" principle:

1. **Profile** actual usage patterns
2. **Identify** bottlenecks with metrics
3. **Optimize** only proven bottlenecks
4. **Validate** improvements with benchmarks

Premature optimization is avoided. Current architecture provides headroom for 10x growth before requiring optimization.

## Failure Modes & Resilience

### Expected Failures

**External API Unavailable**: Retry with exponential backoff, queue for later

**Database Lock**: Busy timeout with WAL mode reduces contention

**Search Timeout**: Individual search timeout doesn't affect queue

**Rate Limit Exceeded**: Backoff and reschedule automatically

### Recovery Mechanisms

**Job Persistence**: Scheduled jobs survive application restart

**Graceful Shutdown**: In-flight searches complete before shutdown

**Database Backups**: Automated backup script with retention

**Health Checks**: Kubernetes readiness/liveness probe support

## Evolution & Migration

### Designed for Growth

While optimized for single-server deployment, the architecture supports growth:

**Database Migration**: SQLAlchemy abstraction enables PostgreSQL switch

**Horizontal Scaling**: Stateless application layer allows load balancing

**Queue Distribution**: APScheduler supports Redis-based job stores

**API Versioning**: FastAPI router tags enable versioned APIs

### Technical Debt

Conscious technical debt decisions:

**SQLite Limitation**: Acceptable for target scale, migration path exists

**Synchronous Scheduler**: APScheduler 3.x is synchronous, 4.x will be async

**Minimal Frontend**: Server-side rendering appropriate for current UX needs

These decisions prioritize shipping a secure, maintainable product over speculative future requirements.

## Conclusion

Splintarr's architecture prioritizes:

1. **Security** through defense-in-depth and encryption
2. **Simplicity** through proven technologies and minimal dependencies
3. **Maintainability** through clear abstractions and comprehensive testing
4. **Practicality** through appropriate technology choices for the scale

The result is a system that is secure, understandable, and appropriate for its intended use case: personal home media automation.

## See Also

- [Security](security.md) - Detailed security implementation
- [Configuration Reference](../reference/configuration.md) - All configuration options
- [Deploy Production](../how-to-guides/deploy-production.md) - Production deployment guide
