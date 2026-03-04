"""Tests for config import validation and preview."""
from splintarr.services.config_import import validate_import_data


def _make_config(**overrides):
    base = {
        "splintarr_version": "1.2.0",
        "exported_at": "2026-03-04T00:00:00",
        "instances": [],
        "search_queues": [],
        "exclusions": [],
        "notifications": None,
    }
    base.update(overrides)
    return base


def _make_instance(name="My Sonarr", id=1):
    return {
        "id": id, "name": name, "instance_type": "sonarr", "url": "http://sonarr:8989",
        "api_key": "[REDACTED]", "is_active": True, "verify_ssl": True,
        "timeout_seconds": 30, "rate_limit_per_second": 5.0,
    }


class TestValidateImportData:
    def test_valid_config_returns_preview(self):
        data = _make_config(instances=[_make_instance()])
        result = validate_import_data(data, existing_instance_names=set())
        assert result["valid"] is True
        assert len(result["instances"]) == 1
        assert result["instances"][0]["status"] == "new"
        assert result["instances"][0]["needs_api_key"] is True

    def test_missing_required_keys(self):
        result = validate_import_data({"splintarr_version": "1.0.0"}, existing_instance_names=set())
        assert result["valid"] is False

    def test_duplicate_instance_marked_conflict(self):
        data = _make_config(instances=[_make_instance(name="Existing")])
        result = validate_import_data(data, existing_instance_names={"Existing"})
        assert result["instances"][0]["status"] == "conflict_skip"
        assert result["instances"][0]["needs_api_key"] is False

    def test_queue_linked_to_conflict_instance_skipped(self):
        data = _make_config(
            instances=[_make_instance(name="Existing", id=1)],
            search_queues=[{
                "name": "Q1", "instance_id": 1, "strategy": "missing",
                "is_recurring": False, "interval_hours": None, "is_active": True, "filters": None,
            }],
        )
        result = validate_import_data(data, existing_instance_names={"Existing"})
        assert result["queues"][0]["status"] == "skip_instance_conflict"

    def test_notification_needs_webhook(self):
        data = _make_config(notifications={
            "webhook_url": "[REDACTED]",
            "events_enabled": {"search_triggered": True},
            "is_active": True,
        })
        result = validate_import_data(data, existing_instance_names=set())
        assert result["notifications"]["has_config"] is True
        assert result["notifications"]["needs_webhook"] is True
