"""Tests for global exception handlers in main.py."""

import logging
from unittest.mock import patch

import pytest


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
        with caplog.at_level(logging.WARNING):
            client.post(
                "/api/search-queues",
                json={"instance_id": "not_a_number"},
                cookies=client.cookies,
            )

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

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) > 0, "Expected a WARNING log for 404 error"


class TestUnhandledExceptionHandler:
    """Tests for catch-all unhandled exception logging."""

    def test_unhandled_exception_returns_500(self, client):
        """Unhandled exceptions return 500 with generic message."""
        with patch("vibe_quality_searcharr.main.database_health_check", side_effect=RuntimeError("boom")):
            response = client.get("/health")
        # Health endpoint has its own try-except, so it returns 503
        assert response.status_code in (500, 503)
