"""
WebSocket endpoint for real-time activity feed.

Provides a single WebSocket connection at /ws/live that replaces all
dashboard polling. Authenticates via access_token cookie on handshake.
"""

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from splintarr.config import settings
from splintarr.core.auth import TokenError, get_current_user_id_from_token
from splintarr.core.websocket import ws_manager
from splintarr.database import get_session_factory
from splintarr.models.user import User

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

    # Verify the user still exists and is active (token may outlive account)
    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                await websocket.close(code=4001, reason="Account inactive")
                return
    except Exception as e:
        logger.warning("websocket_user_check_failed", error=str(e), user_id=user_id)
        await websocket.close(code=4001, reason="Authentication error")
        return

    # Validate Origin header to prevent Cross-Site WebSocket Hijacking (CSWSH)
    origin = websocket.headers.get("origin", "")
    if origin:
        allowed_origins = list(settings.cors_origins) if settings.cors_origins else []
        # Also allow requests from the app's own host
        host = websocket.headers.get("host", "")
        if host:
            local_origins = [f"http://{host}", f"https://{host}"]
            allowed_origins.extend(local_origins)
        if origin not in allowed_origins:
            logger.warning(
                "websocket_origin_rejected",
                origin=origin,
                user_id=user_id,
            )
            await websocket.close(code=4003, reason="Origin not allowed")
            return

    await ws_manager.connect(websocket)
    logger.debug("websocket_client_connected", user_id=user_id)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.debug("websocket_client_disconnected", user_id=user_id)
    except Exception as e:
        ws_manager.disconnect(websocket)
        logger.warning("websocket_unexpected_error", error=str(e), user_id=user_id)
