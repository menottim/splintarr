"""Tests for global exception handlers in main.py."""

import logging


class TestRequestValidationErrorHandler:
    """Tests for 422 validation error logging."""

    def test_validation_error_returns_422(self, client):
        """Validation errors still return 422 with error details."""
        response = client.post(
            "/api/auth/login",
            json={"username": 123},
        )
        assert response.status_code == 422

    def test_validation_error_logs_warning(self, client, caplog):
        """Validation errors are logged at WARNING level."""
        with caplog.at_level(logging.WARNING):
            client.post(
                "/api/auth/login",
                json={"username": 123},
                cookies=client.cookies,
            )
        assert (
            "http_validation_error" in caplog.text
        ), f"Expected 'http_validation_error' in logs, got: {caplog.text}"

    def test_validation_error_response_contains_details(self, client):
        """Validation error response includes field-level error details."""
        response = client.post(
            "/api/auth/login",
            json={"username": 123},
        )
        data = response.json()
        assert "detail" in data


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
        with caplog.at_level(logging.WARNING):
            client.get("/api/nonexistent-endpoint-that-does-not-exist")
        assert (
            "http_client_error" in caplog.text
        ), f"Expected 'http_client_error' in logs, got: {caplog.text}"

    def test_5xx_logs_error(self, client, caplog):
        """5xx HTTP errors are logged at ERROR level."""
        from fastapi import HTTPException, Request

        from splintarr.main import app

        @app.get("/test-5xx")
        async def error_500_endpoint(request: Request):
            raise HTTPException(status_code=500, detail="test server error")

        try:
            with caplog.at_level(logging.ERROR):
                client.get("/test-5xx")
            assert (
                "http_server_error" in caplog.text
            ), f"Expected 'http_server_error' in logs, got: {caplog.text}"
        finally:
            app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/test-5xx"]


class TestUnhandledExceptionHandler:
    """Tests for catch-all unhandled exception logging."""

    def test_unhandled_exception_returns_500(self, client):
        """Unhandled exceptions return 500 with generic message."""
        from fastapi import Request

        from splintarr.main import app

        @app.get("/test-crash")
        async def crash_endpoint(request: Request):
            raise RuntimeError("test unhandled crash")

        try:
            response = client.get("/test-crash")
            assert response.status_code == 500
            data = response.json()
            assert data["detail"] == "Internal server error"
        finally:
            # Clean up the test route
            app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/test-crash"]

    def test_unhandled_exception_logs_error(self, client, caplog):
        """Unhandled exceptions are logged at ERROR level."""
        from fastapi import Request

        from splintarr.main import app

        @app.get("/test-crash-log")
        async def crash_log_endpoint(request: Request):
            raise RuntimeError("test logging crash")

        try:
            with caplog.at_level(logging.ERROR):
                client.get("/test-crash-log")
            assert (
                "unhandled_exception" in caplog.text
            ), f"Expected 'unhandled_exception' in logs, got: {caplog.text}"
        finally:
            app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/test-crash-log"]
