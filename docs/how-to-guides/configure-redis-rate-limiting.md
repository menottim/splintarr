# Rate Limiting with Redis - Implementation Guide

## Current Status

Rate limiting currently uses in-memory storage which is vulnerable to bypass with multiple workers.

**File:** `src/splintarr/main.py:54`
```python
storage_uri="memory://",  # In-memory storage (use Redis in production for multiple workers)
```

## Security Issue

With multiple workers, each worker has independent rate limit counters. An attacker can bypass rate limits by distributing requests across workers.

**Example Attack:**
- App configured with 4 workers
- Rate limit: 5 login attempts/minute
- Attacker achieves: 5 × 4 = 20 attempts/minute

## Solution: Redis-Based Rate Limiting

### For Production Deployment

Add Redis to your `docker-compose.yml`:

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    networks:
      - app-network

  app:
    # ... existing config ...
    environment:
      - RATE_LIMIT_STORAGE=redis://redis:6379/0
    depends_on:
      - redis
    networks:
      - app-network

volumes:
  redis_data:

networks:
  app-network:
```

### For Homelab/Development (Single Worker)

If running with `workers=1`, memory storage is acceptable:

```yaml
services:
  app:
    environment:
      - WORKERS=1  # Single worker - memory storage is safe
```

**Trade-off:** Single worker reduces concurrency but eliminates rate limit bypass.

## Configuration Options

Add to `.env`:
```bash
# Rate limiting storage backend
RATE_LIMIT_STORAGE=redis://redis:6379/0  # Production
# RATE_LIMIT_STORAGE=memory://           # Development (workers=1 only)
```

## Implementation (Future Enhancement)

To fully implement Redis rate limiting, update `config.py`:

```python
rate_limit_storage_uri: str = Field(
    default="memory://",
    description="Rate limit storage URI (redis://host:port/db for production)",
)
```

And update `main.py`:

```python
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
    storage_uri=settings.rate_limit_storage_uri,
)
```

## Current Mitigation

**For now, the recommended approach for homelab use is:**
1. Run with single worker (`WORKERS=1`)
2. Accept lower concurrency for improved security
3. Monitor for rate limit bypass attempts in logs

## References

- [SlowAPI Documentation](https://slowapi.readthedocs.io/)
- [Redis Rate Limiting](https://redis.io/docs/reference/patterns/distributed-locks/)
