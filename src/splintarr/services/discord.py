"""
Discord Notification Service for Splintarr.

This module provides a stateless service for sending Discord webhook
notifications about search events, queue failures, instance health
changes, and test messages.

Each embed follows Discord's embed structure:
  {"embeds": [{"title": ..., "description": ..., "color": ...}]}

All methods are fire-and-forget: they log errors at warning level
and never raise exceptions to the caller.
"""

from datetime import datetime

import httpx
import structlog

logger = structlog.get_logger()

# Discord embed colour constants (decimal)
COLOR_GREEN = 0x2ECC71  # success / recovered
COLOR_ORANGE = 0xE67E22  # partial success / warning
COLOR_RED = 0xE74C3C  # failure / error
COLOR_BLUE = 0x3498DB  # informational

# Discord returns 204 No Content on successful webhook POST
DISCORD_SUCCESS_STATUS = 204


class DiscordNotificationService:
    """
    Stateless service for sending Discord webhook notifications.

    Instantiated per-call with a *decrypted* webhook URL.
    All public methods are async, wrap httpx errors, and never raise.
    """

    def __init__(self, webhook_url: str) -> None:
        """
        Initialize with a decrypted Discord webhook URL.

        Args:
            webhook_url: Plaintext Discord webhook URL (already decrypted)
        """
        self._webhook_url = webhook_url

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    async def send_search_started(
        self,
        search_name: str,
        instance_name: str,
        strategy: str,
        estimated_items: int,
    ) -> bool:
        """
        Send a search started notification (blue embed).

        Args:
            search_name: Name of the search queue
            instance_name: Name of the instance being searched
            strategy: Search strategy (e.g. 'missing', 'cutoff')
            estimated_items: Estimated number of items to evaluate

        Returns:
            bool: True if the webhook accepted the message
        """
        embed: dict = {
            "title": f"Search Started: {search_name}",
            "description": (
                f"**Instance:** {instance_name}\n"
                f"**Strategy:** {strategy}\n"
                f"**Items to evaluate:** {estimated_items}"
            ),
            "color": COLOR_BLUE,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info(
            "discord_notification_search_started",
            search_name=search_name,
            instance_name=instance_name,
            estimated_items=estimated_items,
        )

        return await self._send_embed(embed)

    async def send_search_summary(
        self,
        search_name: str,
        instance_name: str,
        strategy: str,
        items_searched: int,
        items_found: int,
        duration_seconds: float,
    ) -> bool:
        """
        Send a search run summary embed.

        Colour is green for full success, orange for partial, red for zero found.

        Args:
            search_name: Name of the search queue
            instance_name: Name of the instance searched
            strategy: Search strategy used (e.g. 'missing', 'cutoff')
            items_searched: Total items evaluated
            items_found: Items for which searches were triggered
            duration_seconds: Wall-clock time of the search run

        Returns:
            bool: True if the webhook accepted the message
        """
        if items_found == 0:
            color = COLOR_RED
        elif items_found < items_searched:
            color = COLOR_ORANGE
        else:
            color = COLOR_GREEN

        duration_display = (
            f"{duration_seconds:.1f}s" if duration_seconds < 60 else f"{duration_seconds / 60:.1f}m"
        )

        embed: dict = {
            "title": f"Search Complete: {search_name}",
            "description": (
                f"**Instance:** {instance_name}\n"
                f"**Strategy:** {strategy}\n"
                f"**Items searched:** {items_searched}\n"
                f"**Searches triggered:** {items_found}\n"
                f"**Duration:** {duration_display}"
            ),
            "color": color,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info(
            "discord_notification_search_summary",
            search_name=search_name,
            instance_name=instance_name,
            items_found=items_found,
        )

        return await self._send_embed(embed)

    async def send_queue_failed(
        self,
        queue_name: str,
        instance_name: str,
        error: str,
        consecutive_failures: int,
    ) -> bool:
        """
        Send a queue failure notification (red embed).

        Args:
            queue_name: Name of the failed search queue
            instance_name: Name of the instance
            error: Error message describing the failure
            consecutive_failures: Number of consecutive failures for this queue

        Returns:
            bool: True if the webhook accepted the message
        """
        embed: dict = {
            "title": f"Queue Failed: {queue_name}",
            "description": (
                f"**Instance:** {instance_name}\n"
                f"**Error:** {error}\n"
                f"**Consecutive failures:** {consecutive_failures}"
            ),
            "color": COLOR_RED,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info(
            "discord_notification_queue_failed",
            queue_name=queue_name,
            instance_name=instance_name,
            consecutive_failures=consecutive_failures,
        )

        return await self._send_embed(embed)

    async def send_instance_health(
        self,
        instance_name: str,
        status: str,
        error: str | None = None,
    ) -> bool:
        """
        Send an instance health change notification.

        Green for recovered, red for connection lost.

        Args:
            instance_name: Name of the instance
            status: Health status ('healthy' or 'unhealthy')
            error: Error message if unhealthy (optional)

        Returns:
            bool: True if the webhook accepted the message
        """
        if status == "healthy":
            color = COLOR_GREEN
            title = f"Instance Recovered: {instance_name}"
            description = "Connection to the instance has been restored."
        else:
            color = COLOR_RED
            title = f"Instance Down: {instance_name}"
            description = "Connection lost."
            if error:
                description += f"\n**Error:** {error}"

        embed: dict = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info(
            "discord_notification_instance_health",
            instance_name=instance_name,
            status=status,
        )

        return await self._send_embed(embed)

    async def send_library_sync(
        self,
        items_synced: int,
        instance_count: int,
        error_count: int,
    ) -> bool:
        """
        Send a library sync completion embed.

        Colour is green for clean sync, orange for partial errors, red for all-error.

        Args:
            items_synced: Total items synced across all instances
            instance_count: Number of instances synced
            error_count: Number of errors during sync

        Returns:
            bool: True if the webhook accepted the message
        """
        if error_count == 0:
            color = COLOR_GREEN
        elif error_count < instance_count:
            color = COLOR_ORANGE
        else:
            color = COLOR_RED

        embed: dict = {
            "title": "Library Sync Complete",
            "description": (
                f"**Instances:** {instance_count}\n"
                f"**Items synced:** {items_synced}\n"
                f"**Errors:** {error_count}"
            ),
            "color": color,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info(
            "discord_notification_library_sync",
            items_synced=items_synced,
            instance_count=instance_count,
            error_count=error_count,
        )

        return await self._send_embed(embed)

    async def send_update_available(
        self,
        current_version: str,
        latest_version: str,
        release_url: str,
    ) -> bool:
        """
        Send an update-available notification (blue embed).

        Args:
            current_version: Currently running version
            latest_version: Newest available version
            release_url: URL to the GitHub release page

        Returns:
            bool: True if the webhook accepted the message
        """
        description = (
            f"**Current:** v{current_version}\n"
            f"**Latest:** v{latest_version}"
        )
        if release_url:
            description += f"\n[View release]({release_url})"

        embed: dict = {
            "title": "Splintarr Update Available",
            "description": description,
            "color": COLOR_BLUE,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info(
            "discord_notification_update_available",
            current_version=current_version,
            latest_version=latest_version,
        )

        return await self._send_embed(embed)

    async def send_grab_confirmed(
        self,
        search_name: str,
        instance_name: str,
        checked: int,
        grabs: int,
    ) -> bool:
        """
        Send a grab confirmation result embed.

        Green if grabs were detected, orange if none found.

        Args:
            search_name: Name of the search queue
            instance_name: Name of the instance
            checked: Number of items checked for grabs
            grabs: Number of grabs detected

        Returns:
            bool: True if the webhook accepted the message
        """
        color = COLOR_GREEN if grabs > 0 else COLOR_ORANGE

        embed: dict = {
            "title": f"Grab Check: {search_name}",
            "description": (
                f"**Instance:** {instance_name}\n"
                f"**Items checked:** {checked}\n"
                f"**Grabs detected:** {grabs}"
            ),
            "color": color,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info(
            "discord_notification_grab_confirmed",
            search_name=search_name,
            instance_name=instance_name,
            checked=checked,
            grabs=grabs,
        )

        return await self._send_embed(embed)

    async def send_budget_alert(
        self,
        indexer_name: str,
        queries_used: int,
        query_limit: int,
        percent_used: int,
    ) -> bool:
        """Send a budget alert when indexer API usage is high.

        Args:
            indexer_name: Name of the indexer
            queries_used: Current query count
            query_limit: Maximum allowed queries
            percent_used: Usage percentage (0-100)

        Returns:
            bool: True if the webhook accepted the message
        """
        embed: dict = {
            "title": f"Indexer Budget Alert: {indexer_name}",
            "description": (
                f"**Usage:** {queries_used} / {query_limit} ({percent_used}%)\n"
                f"API budget is running low. Search batch sizes may be reduced automatically."
            ),
            "color": COLOR_RED,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        result = await self._send_embed(embed)

        if result:
            logger.info(
                "discord_notification_budget_alert_sent",
                indexer_name=indexer_name,
                percent_used=percent_used,
            )

        return result

    async def send_test_message(self) -> bool:
        """
        Send a test notification to verify webhook configuration.

        Returns:
            bool: True if the webhook accepted the message
        """
        embed: dict = {
            "title": "Splintarr Notifications Configured",
            "description": "Splintarr notifications configured successfully!",
            "color": COLOR_BLUE,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info("discord_notification_test_sent")

        return await self._send_embed(embed)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _send_embed(self, embed: dict) -> bool:
        """
        POST an embed payload to the Discord webhook URL.

        Args:
            embed: Discord embed dictionary

        Returns:
            bool: True if Discord returned 204 (success)
        """
        payload = {"embeds": [embed]}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self._webhook_url,
                    json=payload,
                )

            if response.status_code == DISCORD_SUCCESS_STATUS:
                logger.info(
                    "discord_webhook_sent",
                    status_code=response.status_code,
                )
                return True

            logger.warning(
                "discord_webhook_unexpected_status",
                status_code=response.status_code,
                response_body=response.text[:500],
            )
            return False

        except httpx.TimeoutException as e:
            logger.warning(
                "discord_webhook_timeout",
                error=str(e),
            )
            return False
        except httpx.HTTPError as e:
            logger.warning(
                "discord_webhook_http_error",
                error=str(e),
            )
            return False
        except Exception as e:
            logger.warning(
                "discord_webhook_unexpected_error",
                error=str(e),
            )
            return False
