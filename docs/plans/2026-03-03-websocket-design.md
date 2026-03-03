# WebSocket Real-Time Activity Feed — Design Document

> **Feature:** F2 / PRD #15
> **Date:** 2026-03-03
> **Status:** Approved
> **Release:** v1.1.0

---

## Overview

Replace all dashboard polling with a single WebSocket connection. One connection per browser tab, all real-time events pushed from server to client. Graceful fallback to polling if WebSocket fails.

## Architecture

```
Services (emit events)          Core                         Client
┌─────────────────────┐     ┌───────────┐     ┌──────────────────┐     ┌──────────┐
│ search_queue.py     │────▶│           │────▶│                  │────▶│ Browser  │
│ library_sync.py     │     │ EventBus  │     │ WebSocketManager │     │ WS Client│
│ scheduler.py        │────▶│ (asyncio) │────▶│ (connections[])  │────▶│ (app.js) │
│ dashboard helpers   │     │           │     │                  │     │          │
└─────────────────────┘     └───────────┘     └──────────────────┘     └──────────┘
```

### New Modules

| Module | Responsibility |
|---|---|
| `src/splintarr/core/events.py` | EventBus singleton. `emit(type, data)` and `on(type, handler)`. Async, in-process. |
| `src/splintarr/core/websocket.py` | WebSocketManager. Connection registry, broadcast to all clients, auth validation. |
| `src/splintarr/api/ws.py` | FastAPI WebSocket route at `/ws/live`. Accepts connection, validates auth, delegates to manager. |

### Dependencies

None new. FastAPI 0.115+ includes WebSocket support via Starlette. The `websockets` package is a transitive dependency.

---

## Authentication

1. Client opens `ws://host:7337/ws/live`
2. Browser automatically sends cookies (including `access_token` httpOnly cookie)
3. Server extracts `access_token` from WebSocket handshake headers via `websocket.cookies.get("access_token")`
4. Validates token with existing `get_current_user_id_from_token()`
5. Rejects connection (close code 4001) on auth failure

### Token Expiry Handling

- Access tokens expire after 15 minutes
- Server sends `{"type": "auth.expired"}` when token validation fails during keepalive
- Client closes WS, calls `/api/auth/refresh` (browser sends refresh token cookie automatically), then reconnects
- Client-side: after receiving `auth.expired`, do a fetch to `/api/auth/refresh`, then `ws.connect()` again

---

## Event Types

### Message Envelope

All messages use a consistent JSON format:

```json
{
  "type": "search.item_result",
  "timestamp": "2026-03-03T14:30:00Z",
  "data": { ... }
}
```

### Polling Replacement Events

| Event Type | Replaces | Trigger |
|---|---|---|
| `stats.updated` | `/api/dashboard/stats` (30s poll) | After search execution, queue state change |
| `activity.updated` | `/api/dashboard/activity` (15s poll) | After search execution completes |
| `status.updated` | `/api/dashboard/system-status` (30s poll) | After health check, on connect |
| `indexer_health.updated` | `/api/dashboard/indexer-health` (60s poll) | After Prowlarr sync |
| `sync.progress` | `/api/library/sync-status` (2s poll) | During library sync |
| `queue_status.updated` | `/api/search-queues/{id}/status` (3s poll) | During queue execution |

### New Real-Time Events

| Event Type | Trigger | Data |
|---|---|---|
| `search.started` | Queue execution begins | `{queue_id, queue_name, strategy, max_items}` |
| `search.item_result` | Each item searched | `{queue_id, item_name, series_name, result, reason, score}` |
| `search.completed` | Queue execution ends | `{queue_id, status, items_searched, items_found, duration_seconds}` |
| `search.failed` | Queue execution fails | `{queue_id, error}` |
| `sync.completed` | Library sync done | `{instances_synced, total_items, errors}` |
| `auth.expired` | Token validation fails | `{}` |

### On Connect

Server immediately sends current state so client doesn't wait for the next event:
- `stats.updated` with current dashboard stats
- `status.updated` with current system status
- `indexer_health.updated` with current indexer data

---

## EventBus Design

```python
# src/splintarr/core/events.py

class EventBus:
    """In-process async event bus. Singleton."""

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def on(self, event_type: str, handler: Callable) -> None:
        """Register a handler for an event type."""

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to all registered handlers."""

    def off(self, event_type: str, handler: Callable) -> None:
        """Remove a handler."""

# Module-level singleton
event_bus = EventBus()
```

Usage in services:
```python
from splintarr.core.events import event_bus

# In search_queue.py, after each item is searched:
await event_bus.emit("search.item_result", {
    "queue_id": queue_id,
    "item_name": record.get("title", ""),
    "series_name": series_name,
    "result": "found",
    "score": item_score,
})
```

---

## WebSocketManager Design

```python
# src/splintarr/core/websocket.py

class WebSocketManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        """Accept and register a new connection."""

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection."""

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send message to all connected clients. Remove dead connections."""

    async def send_initial_state(self, websocket: WebSocket, db: Session) -> None:
        """Send current stats/status/indexer data on connect."""

# Module-level singleton
ws_manager = WebSocketManager()
```

The WebSocketManager registers itself as a handler on the EventBus during app startup:
```python
event_bus.on("search.started", lambda data: ws_manager.broadcast({"type": "search.started", "data": data}))
event_bus.on("stats.updated", lambda data: ws_manager.broadcast({"type": "stats.updated", "data": data}))
# ... etc for all event types
```

---

## WebSocket Route

```python
# src/splintarr/api/ws.py

@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket, db: Session = Depends(get_db)):
    # 1. Extract access_token cookie from handshake
    token = websocket.cookies.get("access_token")
    if not token:
        await websocket.close(code=4001, reason="Not authenticated")
        return

    # 2. Validate token
    try:
        user_id = get_current_user_id_from_token(token)
    except TokenError:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # 3. Accept connection
    await ws_manager.connect(websocket, user_id)

    # 4. Send initial state
    await ws_manager.send_initial_state(websocket, db)

    # 5. Keep alive loop (listen for client messages, handle disconnect)
    try:
        while True:
            # Only expected client message is pong (WS protocol level)
            # Any text message is ignored
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
```

---

## Frontend: app.js WebSocket Client

```javascript
Splintarr.ws = (function() {
    var socket = null;
    var handlers = {};       // {type: [fn, fn, ...]}
    var reconnectAttempts = 0;
    var maxReconnectAttempts = 3;  // After this, fall back to polling
    var reconnectTimer = null;
    var useFallbackPolling = false;

    function connect() {
        var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(protocol + '//' + location.host + '/ws/live');

        socket.onopen = function() {
            reconnectAttempts = 0;
            useFallbackPolling = false;
            // Stop any polling that was running as fallback
            if (Splintarr.ws.onConnected) Splintarr.ws.onConnected();
        };

        socket.onmessage = function(event) {
            var msg = JSON.parse(event.data);
            if (msg.type === 'auth.expired') {
                // Refresh token and reconnect
                fetch('/api/auth/refresh', {method: 'POST'}).then(function() {
                    connect();
                });
                return;
            }
            var fns = handlers[msg.type] || [];
            fns.forEach(function(fn) { fn(msg.data, msg.timestamp); });
        };

        socket.onclose = function() {
            reconnectAttempts++;
            if (reconnectAttempts <= maxReconnectAttempts) {
                var delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 30000);
                reconnectTimer = setTimeout(connect, delay);
            } else {
                useFallbackPolling = true;
                if (Splintarr.ws.onFallback) Splintarr.ws.onFallback();
            }
        };
    }

    function on(type, fn) {
        if (!handlers[type]) handlers[type] = [];
        handlers[type].push(fn);
    }

    function close() {
        if (reconnectTimer) clearTimeout(reconnectTimer);
        if (socket) socket.close();
    }

    return { connect: connect, on: on, close: close, useFallbackPolling: false };
})();
```

### Dashboard Migration

```javascript
// Before: 4 setInterval blocks
// After: 4 WS handlers using the same DOM update functions

Splintarr.ws.on('stats.updated', function(data) {
    // Same logic as the current setInterval callback
    updateDashboardStats(data);
});
Splintarr.ws.on('activity.updated', function(data) {
    updateActivityTable(data.activity);
});
Splintarr.ws.on('status.updated', function(data) {
    updateSystemStatus(data);
});
Splintarr.ws.on('indexer_health.updated', function(data) {
    refreshIndexerHealthFromData(data);
});

// Fallback: if WS fails, start polling
Splintarr.ws.onFallback = function() {
    setInterval(pollStats, 30000);
    setInterval(pollActivity, 15000);
    // ... etc
};

Splintarr.ws.connect();
```

---

## Keepalive

- Server sends `{"type": "ping"}` every 30 seconds via an asyncio background task
- Uses WebSocket protocol-level ping/pong (not application-level)
- Connection considered dead after 90 seconds of silence → removed from registry

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Auth failure on connect | Close with code 4001 |
| Token expires mid-session | Send `auth.expired`, client refreshes and reconnects |
| Server restart | Client sees close, triggers reconnect with backoff |
| Client navigates away | `beforeunload` calls `Splintarr.ws.close()` |
| Multiple tabs | Each tab gets its own connection. All receive broadcasts. |
| Broadcast to dead connection | Caught, connection removed from registry |
| 3 failed reconnects | Client falls back to polling, WS reconnect continues in background every 60s |

---

## Files Modified

| File | Change |
|---|---|
| `src/splintarr/core/events.py` | **New** — EventBus singleton |
| `src/splintarr/core/websocket.py` | **New** — WebSocketManager singleton |
| `src/splintarr/api/ws.py` | **New** — WebSocket route `/ws/live` |
| `src/splintarr/main.py` | Register WS route, wire EventBus → WebSocketManager on startup |
| `src/splintarr/static/js/app.js` | Add `Splintarr.ws` module |
| `src/splintarr/templates/dashboard/index.html` | Replace setInterval polling with WS handlers |
| `src/splintarr/templates/library.html` | Replace sync polling with WS handler |
| `src/splintarr/templates/search_queue_detail.html` | Replace execution polling with WS handler |
| `src/splintarr/services/search_queue.py` | Add `event_bus.emit()` calls at key points |
| `src/splintarr/services/library_sync.py` | Add `event_bus.emit()` calls for progress |
| `src/splintarr/services/scheduler.py` | Add `event_bus.emit()` for health changes |
| `tests/unit/test_events.py` | **New** — EventBus unit tests |
| `tests/unit/test_websocket.py` | **New** — WebSocketManager unit tests |
