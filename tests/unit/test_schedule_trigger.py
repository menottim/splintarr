"""Tests for schedule trigger selection."""
import pytest

from splintarr.services.scheduler import _build_trigger_kwargs


class TestBuildTriggerKwargs:
    def test_interval_mode(self):
        result = _build_trigger_kwargs(
            schedule_mode="interval", interval_hours=4,
            schedule_time=None, schedule_days=None, jitter_minutes=0,
        )
        assert result["trigger"] == "interval"
        assert result["hours"] == 4
        assert "jitter" not in result

    def test_interval_with_jitter(self):
        result = _build_trigger_kwargs(
            schedule_mode="interval", interval_hours=4,
            schedule_time=None, schedule_days=None, jitter_minutes=10,
        )
        assert result["jitter"] == 600

    def test_daily_mode(self):
        result = _build_trigger_kwargs(
            schedule_mode="daily", interval_hours=None,
            schedule_time="02:30", schedule_days=None, jitter_minutes=0,
        )
        assert result["trigger"] == "cron"
        assert result["hour"] == 2
        assert result["minute"] == 30

    def test_weekly_mode(self):
        result = _build_trigger_kwargs(
            schedule_mode="weekly", interval_hours=None,
            schedule_time="03:00", schedule_days="mon,wed,fri", jitter_minutes=5,
        )
        assert result["trigger"] == "cron"
        assert result["day_of_week"] == "mon,wed,fri"
        assert result["hour"] == 3
        assert result["minute"] == 0
        assert result["jitter"] == 300

    def test_none_mode_defaults_to_interval(self):
        result = _build_trigger_kwargs(
            schedule_mode=None, interval_hours=24,
            schedule_time=None, schedule_days=None, jitter_minutes=0,
        )
        assert result["trigger"] == "interval"

    def test_daily_without_time_falls_back(self):
        result = _build_trigger_kwargs(
            schedule_mode="daily", interval_hours=24,
            schedule_time=None, schedule_days=None, jitter_minutes=0,
        )
        assert result["trigger"] == "interval"
