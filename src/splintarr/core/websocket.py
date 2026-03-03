"""
WebSocket connection manager for Splintarr real-time activity feed.

Manages a registry of active WebSocket connections and provides broadcasting
capabilities to push events (search progress, sync updates, health status)
to all connected clients in real time.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import WebSocket

logger = structlog.get_logger()


class WebSocketManager:
    """Manages WebSocket connections and broadcasts events to all clients.

    Maintains a list of active connections and handles:
    - Connection registration (accept + track)
    - Disconnection cleanup
    - Broadcasting messages to all connected clients
    - Automatic removal of dead connections on send failure

    Security note: broadcasts reach ALL connected clients regardless of user.
    This is acceptable for the single-admin homelab design. If multi-user
    support is added, connections must be keyed by user_id and broadcasts
    filtered to only the owning user's connections.
    """

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and register it.

        Args:
            websocket: The incoming WebSocket to accept and track.
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            "websocket_connected",
            connection_count=self.connection_count,
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the registry.

        Safe to call with a WebSocket that was never registered (no-op).

        Args:
            websocket: The WebSocket to remove.
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                "websocket_disconnected",
                connection_count=self.connection_count,
            )

    @property
    def connection_count(self) -> int:
        """Return the number of active WebSocket connections."""
        return len(self.active_connections)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected WebSocket clients.

        Adds a UTC ISO-8601 timestamp to the message. Dead connections
        (those that raise on send) are automatically removed.

        Args:
            message: The JSON-serializable message dict to broadcast.
        """
        if not self.active_connections:
            return

        message["timestamp"] = datetime.now(UTC).isoformat()
        dead_connections: list[WebSocket] = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(
                    "websocket_send_failed",
                    error=str(e),
                )
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(connection)

    async def send_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast a typed event to all connected clients.

        Wraps the event type and data payload into a standard message
        format and delegates to broadcast().

        Args:
            event_type: The event type identifier (e.g. "search_started").
            data: The event payload data.
        """
        await self.broadcast({"type": event_type, "data": data})


# Module-level singleton — import this from other modules
ws_manager = WebSocketManager()
