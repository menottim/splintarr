"""
Update Checker Service for Splintarr.

Periodically checks GitHub Releases API for new versions and caches the result
in-memory. The dashboard reads this cache to display an update banner.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from packaging.version import InvalidVersion, Version

from splintarr import __version__

logger = structlog.get_logger()

GITHUB_RELEASES_URL = "https://api.github.com/repos/menottim/splintarr/releases/latest"
REQUEST_TIMEOUT = 10.0

# Module-level cache (same pattern as _sync_state in api/library.py)
_update_state: dict[str, Any] = {}
_notified_version: str | None = None  # Track which version we already notified about


def is_update_available(current: str, latest: str) -> bool:
    """Compare two version strings. Returns True if latest > current."""
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        logger.warning("update_check_version_parse_failed", current=current, latest=latest)
        return False


def get_update_state() -> dict[str, Any]:
    """Return cached update state (read-only copy)."""
    return dict(_update_state)


async def check_for_updates() -> dict[str, Any]:
    """Fetch latest release from GitHub API and update the cache."""
    global _update_state
    logger.info("update_check_started")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GITHUB_RELEASES_URL,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"Splintarr/{__version__}",
                },
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )

        if response.status_code == 403:
            logger.warning("update_check_rate_limited")
            return {}

        if response.status_code != 200:
            logger.warning("update_check_http_error", status_code=response.status_code)
            return {}

        data = response.json()

        # Skip drafts and pre-releases
        if data.get("draft") or data.get("prerelease"):
            logger.debug("update_check_skipped_prerelease", tag=data.get("tag_name"))
            return {}

        tag = data.get("tag_name", "")
        latest_version = tag.lstrip("v")

        _update_state = {
            "latest_version": latest_version,
            "release_url": data.get("html_url", ""),
            "release_name": data.get("name", ""),
            "checked_at": datetime.now(UTC).isoformat(),
        }

        update_found = is_update_available(__version__, latest_version)
        logger.info(
            "update_check_completed",
            current_version=__version__,
            latest_version=latest_version,
            update_available=update_found,
        )

        # Send Discord notification once per new version detected (fire-and-forget)
        global _notified_version
        if update_found and latest_version != _notified_version:
            try:
                _notified_version = latest_version
                await _notify_update_available(
                    current_version=__version__,
                    latest_version=latest_version,
                    release_url=_update_state.get("release_url", ""),
                )
            except Exception as notify_err:
                logger.warning("update_notification_failed", error=str(notify_err))

        return dict(_update_state)

    except httpx.ConnectError:
        logger.warning("update_check_network_error", error="connection failed")
        return {}
    except httpx.TimeoutException:
        logger.warning("update_check_timeout")
        return {}
    except Exception as e:
        logger.error("update_check_failed", error=str(e))
        _update_state.clear()
        return {}


async def _notify_update_available(
    current_version: str,
    latest_version: str,
    release_url: str,
) -> None:
    """Send Discord notification for available update if configured."""
    try:
        from splintarr.core.security import decrypt_field
        from splintarr.database import get_session_factory
        from splintarr.models.notification import NotificationConfig
        from splintarr.services.discord import DiscordNotificationService

        db = get_session_factory()()
        try:
            config = (
                db.query(NotificationConfig)
                .filter(NotificationConfig.is_active.is_(True))
                .first()
            )
            if not config or not config.is_event_enabled("update_available"):
                return

            webhook_url = decrypt_field(config.webhook_url)
            service = DiscordNotificationService(webhook_url)
            await service.send_update_available(
                current_version=current_version,
                latest_version=latest_version,
                release_url=release_url,
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning(
            "discord_notification_send_failed",
            event="update_available",
            error=str(e),
        )
