"""
WebSocket endpoint for real-time activity feed.

Provides a single WebSocket connection at /ws/live that replaces all
dashboard polling. Authenticates via access_token cookie on handshake.
"""

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from splintarr.core.auth import TokenError, get_current_user_id_from_token
from splintarr.core.websocket import ws_manager

logger = structlog.get_logger()

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket) -> None:
    """Real-time activity feed WebSocket endpoint."""
    # Authenticate from cookie
    token = websocket.cookies.get("access_token")
    if not token:
        await websocket.close(code=4001, reason="Not authenticated")
        return

    try:
        user_id = get_current_user_id_from_token(token)
    except TokenError:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await ws_manager.connect(websocket)
    logger.debug("websocket_client_connected", user_id=user_id)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.debug("websocket_client_disconnected", user_id=user_id)
    except Exception:
        ws_manager.disconnect(websocket)
