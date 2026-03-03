"""Tests for the EventBus core module."""

from unittest.mock import MagicMock

from splintarr.core.events import EventBus, event_bus


class TestEventBus:
    """Tests for EventBus event dispatching."""

    def setup_method(self) -> None:
        """Create a fresh EventBus for each test."""
        self.bus = EventBus()

    async def test_emit_calls_registered_handler(self) -> None:
        """Emitting an event calls a registered sync handler with the data."""
        handler = MagicMock()
        self.bus.on("test_event", handler)

        await self.bus.emit("test_event", {"key": "value"})

        handler.assert_called_once_with({"key": "value"})

    async def test_emit_calls_multiple_handlers(self) -> None:
        """Emitting an event calls all registered handlers for that event type."""
        handler_a = MagicMock()
        handler_b = MagicMock()
        self.bus.on("test_event", handler_a)
        self.bus.on("test_event", handler_b)

        await self.bus.emit("test_event", {"n": 42})

        handler_a.assert_called_once_with({"n": 42})
        handler_b.assert_called_once_with({"n": 42})

    async def test_emit_unregistered_event_is_noop(self) -> None:
        """Emitting an event with no handlers does nothing (no error)."""
        # Should not raise
        await self.bus.emit("nonexistent_event", {"data": True})

    async def test_off_removes_handler(self) -> None:
        """Removing a handler prevents it from being called on future emits."""
        handler = MagicMock()
        self.bus.on("test_event", handler)
        self.bus.off("test_event", handler)

        await self.bus.emit("test_event", {"data": True})

        handler.assert_not_called()

    async def test_off_nonexistent_handler_is_noop(self) -> None:
        """Removing a handler that was never registered does nothing (no error)."""
        handler = MagicMock()
        # Should not raise
        self.bus.off("test_event", handler)

    async def test_async_handler(self) -> None:
        """Async handlers are awaited correctly."""
        result: dict = {}

        async def async_handler(data: dict) -> None:
            result["received"] = data

        self.bus.on("async_event", async_handler)

        await self.bus.emit("async_event", {"async": True})

        assert result["received"] == {"async": True}

    async def test_handler_exception_does_not_break_others(self) -> None:
        """A handler that raises does not prevent other handlers from running."""
        calls: list[str] = []

        def bad_handler(data: dict) -> None:
            raise RuntimeError("handler exploded")

        def good_handler(data: dict) -> None:
            calls.append("good")

        self.bus.on("test_event", bad_handler)
        self.bus.on("test_event", good_handler)

        await self.bus.emit("test_event", {})

        assert "good" in calls


class TestModuleSingleton:
    """Test that the module-level singleton exists."""

    def test_event_bus_singleton_is_event_bus_instance(self) -> None:
        """The module-level event_bus is an EventBus instance."""
        assert isinstance(event_bus, EventBus)
