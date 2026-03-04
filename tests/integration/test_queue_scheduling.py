"""Integration tests for queue scheduling modes."""
import pytest

from splintarr.services.scheduler import _build_trigger_kwargs


class TestScheduleModesIntegration:
    def test_interval_backward_compatible(self):
        """Existing queues with no schedule_mode default to interval."""
        result = _build_trigger_kwargs(
            schedule_mode=None,
            interval_hours=24,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["trigger"] == "interval"
        assert result["hours"] == 24

    def test_daily_parses_time(self):
        result = _build_trigger_kwargs(
            schedule_mode="daily",
            interval_hours=None,
            schedule_time="14:30",
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["hour"] == 14
        assert result["minute"] == 30

    def test_weekly_all_days(self):
        result = _build_trigger_kwargs(
            schedule_mode="weekly",
            interval_hours=None,
            schedule_time="02:00",
            schedule_days="mon,tue,wed,thu,fri,sat,sun",
            jitter_minutes=15,
        )
        assert result["day_of_week"] == "mon,tue,wed,thu,fri,sat,sun"
        assert result["jitter"] == 900

    def test_jitter_zero_omitted(self):
        result = _build_trigger_kwargs(
            schedule_mode="interval",
            interval_hours=6,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=0,
        )
        assert "jitter" not in result

    def test_daily_without_time_falls_back(self):
        """Daily mode with no time falls back to interval."""
        result = _build_trigger_kwargs(
            schedule_mode="daily",
            interval_hours=24,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["trigger"] == "interval"

    def test_midnight_schedule(self):
        """00:00 parses correctly."""
        result = _build_trigger_kwargs(
            schedule_mode="daily",
            interval_hours=None,
            schedule_time="00:00",
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["hour"] == 0
        assert result["minute"] == 0
