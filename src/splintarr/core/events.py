"""
EventBus for real-time event dispatching in Splintarr.

Provides a publish-subscribe mechanism that allows services to emit events
(e.g., search started, library synced) which WebSocket handlers and other
consumers can subscribe to. Supports both sync and async handlers.

Usage:
    from splintarr.core.events import event_bus

    # Register a handler
    event_bus.on("search_started", my_handler)

    # Emit an event (async)
    await event_bus.emit("search_started", {"queue_id": 1, "item": "..."})

    # Remove a handler
    event_bus.off("search_started", my_handler)
"""

import inspect
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger()


class EventBus:
    """In-process publish-subscribe event bus.

    Handlers registered via `on()` are called when the matching event type
    is emitted. Both sync and async handlers are supported. A handler that
    raises an exception is logged but does not prevent other handlers from
    running.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = defaultdict(list)

    def on(self, event_type: str, handler: Callable[..., Any]) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)
        logger.debug("event_handler_registered", event_type=event_type)

    def off(self, event_type: str, handler: Callable[..., Any]) -> None:
        """Remove a handler for an event type.

        No-op if the handler was never registered.
        """
        handlers = self._handlers.get(event_type)
        if handlers is None:
            return
        try:
            handlers.remove(handler)
            logger.debug("event_handler_removed", event_type=event_type)
        except ValueError:
            pass

    async def emit(self, event_type: str, data: Any) -> None:
        """Emit an event to all registered handlers.

        Each handler is called with *data* as its sole argument. If a handler
        raises an exception it is logged at WARNING level and the remaining
        handlers still execute.
        """
        handlers = self._handlers.get(event_type)
        if not handlers:
            return

        logger.debug(
            "event_emitted",
            event_type=event_type,
            handler_count=len(handlers),
        )

        for handler in handlers:
            try:
                result = handler(data)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.warning(
                    "event_handler_failed",
                    event_type=event_type,
                    handler=getattr(handler, "__name__", str(handler)),
                    error=str(e),
                )


# Module-level singleton used throughout the application
event_bus = EventBus()
