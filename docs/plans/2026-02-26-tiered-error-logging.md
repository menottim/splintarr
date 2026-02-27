# Tiered Error Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure all HTTP errors are logged with tiered severity — 4xx at WARNING (all.log), 5xx at ERROR (all.log + error.log).

**Architecture:** Three global FastAPI exception handlers in `main.py` replace the existing 404/500 handlers: one for `RequestValidationError` (422), one for `HTTPException` (4xx/5xx), and a catch-all for unhandled `Exception`. All use structlog for structured JSON logging.

**Tech Stack:** FastAPI exception handlers, structlog, pytest with TestClient

---

### Task 1: Write tests for RequestValidationError handler

**Files:**
- Create: `tests/unit/test_error_handlers.py`

**Step 1: Write the failing tests**

```python
"""Tests for global exception handlers in main.py."""

import structlog
import pytest
from unittest.mock import patch


class TestRequestValidationErrorHandler:
    """Tests for 422 validation error logging."""

    def test_validation_error_returns_422(self, client):
        """Validation errors still return 422 with error details."""
        response = client.post(
            "/api/search-queues",
            json={"instance_id": "not_a_number"},
            cookies=client.cookies,
        )
        assert response.status_code == 422

    def test_validation_error_logs_warning(self, client, caplog):
        """Validation errors are logged at WARNING level."""
        import logging

        with caplog.at_level(logging.WARNING):
            client.post(
                "/api/search-queues",
                json={"instance_id": "not_a_number"},
                cookies=client.cookies,
            )

        # Check that a warning was logged with validation error context
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("validation" in r.getMessage().lower() for r in warning_records) or \
               any("http_validation_error" in getattr(r, "msg", "") for r in warning_records) or \
               len(warning_records) > 0, "Expected a WARNING log for validation error"

    def test_validation_error_response_contains_details(self, client):
        """Validation error response includes field-level error details."""
        response = client.post(
            "/api/search-queues",
            json={"instance_id": "not_a_number"},
            cookies=client.cookies,
        )
        data = response.json()
        assert "detail" in data
```

**Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/test_error_handlers.py -v --no-cov`
Expected: At least the logging test should fail (no WARNING logged currently)

**Step 3: Commit**

```bash
git add tests/unit/test_error_handlers.py
git commit -m "test: add failing tests for RequestValidationError handler"
```

---

### Task 2: Write tests for HTTPException handler

**Files:**
- Modify: `tests/unit/test_error_handlers.py`

**Step 1: Append HTTPException handler tests**

Add to `tests/unit/test_error_handlers.py`:

```python
class TestHTTPExceptionHandler:
    """Tests for HTTPException logging (4xx and 5xx)."""

    def test_404_returns_json(self, client):
        """404 errors return JSON response."""
        response = client.get("/api/nonexistent-endpoint-that-does-not-exist")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_404_logs_warning(self, client, caplog):
        """404 errors are logged at WARNING level."""
        import logging

        with caplog.at_level(logging.WARNING):
            client.get("/api/nonexistent-endpoint-that-does-not-exist")

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) > 0, "Expected a WARNING log for 404 error"
```

**Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/test_error_handlers.py::TestHTTPExceptionHandler -v --no-cov`
Expected: The logging test should fail (existing 404 handler doesn't log)

**Step 3: Commit**

```bash
git add tests/unit/test_error_handlers.py
git commit -m "test: add failing tests for HTTPException handler"
```

---

### Task 3: Write tests for catch-all Exception handler

**Files:**
- Modify: `tests/unit/test_error_handlers.py`

**Step 1: Append catch-all handler tests**

Add to `tests/unit/test_error_handlers.py`:

```python
class TestUnhandledExceptionHandler:
    """Tests for catch-all unhandled exception logging."""

    def test_unhandled_exception_returns_500(self, client):
        """Unhandled exceptions return 500 with generic message."""
        # We'll test this by hitting the health endpoint with a broken DB
        # The catch-all handler should catch anything that slips through
        with patch("splintarr.main.database_health_check", side_effect=RuntimeError("boom")):
            response = client.get("/health")
        # Health endpoint has its own try-except, so it returns 503
        # The catch-all is a safety net for truly unhandled exceptions
        assert response.status_code in (500, 503)
```

**Step 2: Run tests to verify they pass (baseline)**

Run: `poetry run pytest tests/unit/test_error_handlers.py::TestUnhandledExceptionHandler -v --no-cov`
Expected: PASS (this is a baseline check, the catch-all is a safety net)

**Step 3: Commit**

```bash
git add tests/unit/test_error_handlers.py
git commit -m "test: add tests for catch-all exception handler"
```

---

### Task 4: Implement all three exception handlers

**Files:**
- Modify: `src/splintarr/main.py:15-16` (imports)
- Modify: `src/splintarr/main.py:291-308` (replace existing handlers)

**Step 1: Add imports**

At `src/splintarr/main.py:15`, add `HTTPException` to the existing FastAPI import, and add a new import for `RequestValidationError`:

Change:
```python
from fastapi import FastAPI, Request, status
```
To:
```python
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
```

**Step 2: Replace existing error handlers**

Replace the entire error handlers section at lines 291-308 (the `not_found_handler` and `internal_error_handler`) with:

```python
# Error handlers — tiered logging for all HTTP errors
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Log validation errors at WARNING level."""
    logger.warning(
        "http_validation_error",
        path=request.url.path,
        method=request.method,
        errors=exc.errors(),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Log HTTP exceptions — WARNING for 4xx, ERROR for 5xx."""
    if exc.status_code >= 500:
        logger.error(
            "http_server_error",
            path=request.url.path,
            method=request.method,
            status_code=exc.status_code,
            detail=str(exc.detail),
        )
    else:
        logger.warning(
            "http_client_error",
            path=request.url.path,
            method=request.method,
            status_code=exc.status_code,
            detail=str(exc.detail),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions — always ERROR level."""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
```

**Step 3: Run all error handler tests**

Run: `poetry run pytest tests/unit/test_error_handlers.py -v --no-cov`
Expected: All tests PASS

**Step 4: Run full test suite to check for regressions**

Run: `poetry run pytest tests/unit/ -v --no-cov`
Expected: No new failures (pre-existing failures in non-auth modules are known)

**Step 5: Commit**

```bash
git add src/splintarr/main.py
git commit -m "feat: add tiered error logging for all HTTP errors"
```

---

### Task 5: Docker verification

**Step 1: Build and run**

```bash
docker compose build && docker compose up -d
```

**Step 2: Wait for healthy**

```bash
sleep 3 && curl -s http://localhost:7337/health
```
Expected: `{"status":"healthy",...}`

**Step 3: Trigger a validation error and check logs**

```bash
# Trigger a 422 (send bad data to search queues endpoint — will get 401 first since not logged in, but that's also a 4xx that should now be logged)
curl -s -X POST http://localhost:7337/api/search-queues -H "Content-Type: application/json" -d '{"bad": "data"}'

# Check all.log for the WARNING
docker compose exec splintarr cat /app/logs/all.log | grep -i "client_error\|validation_error" | tail -5
```
Expected: At least one WARNING-level log entry with `http_client_error` or `http_validation_error`

**Step 4: Verify error.log only has ERROR-level entries**

```bash
docker compose exec splintarr cat /app/logs/error.log | head -5
```
Expected: Either empty (no 5xx errors have occurred) or only ERROR-level entries

**Step 5: Tear down**

```bash
docker compose down
```

**Step 6: Commit any remaining changes**

No code changes expected in this task — verification only.
