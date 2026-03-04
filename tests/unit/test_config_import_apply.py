"""Tests for config import apply logic."""
from unittest.mock import MagicMock, patch

import pytest

from splintarr.services.config_import import apply_import


def _make_config(**overrides):
    base = {
        "instances": [],
        "search_queues": [],
        "exclusions": [],
        "notifications": None,
    }
    base.update(overrides)
    return base


def _make_instance(name="New Sonarr", id=1):
    return {
        "id": id, "name": name, "instance_type": "sonarr", "url": "http://sonarr:8989",
        "api_key": "[REDACTED]", "is_active": True, "verify_ssl": True,
        "timeout_seconds": 30, "rate_limit_per_second": 5.0,
    }


class TestApplyImport:
    def test_creates_instance(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        data = _make_config(instances=[_make_instance()])
        secrets = {"instances": {"New Sonarr": "real-key"}, "webhook_url": None}

        with patch("splintarr.services.config_import.encrypt_field", return_value="encrypted"):
            result = apply_import(data, secrets, user_id=1, db=db)

        assert result["imported"]["instances"] == 1

    def test_skips_existing_instance(self):
        db = MagicMock()
        existing = MagicMock()
        existing.id = 99
        db.query.return_value.filter.return_value.first.return_value = existing
        data = _make_config(instances=[_make_instance(name="Existing")])
        secrets = {"instances": {}, "webhook_url": None}

        result = apply_import(data, secrets, user_id=1, db=db)
        assert result["skipped"]["instances"] == 1

    def test_rollback_on_error(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.add.side_effect = Exception("DB error")
        data = _make_config(instances=[_make_instance(name="Fail")])
        secrets = {"instances": {"Fail": "key"}, "webhook_url": None}

        with patch("splintarr.services.config_import.encrypt_field", return_value="enc"):
            with pytest.raises(Exception, match="DB error"):
                apply_import(data, secrets, user_id=1, db=db)

        db.rollback.assert_called()
