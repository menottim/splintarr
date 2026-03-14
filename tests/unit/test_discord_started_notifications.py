"""Tests for Discord 'started' notification embeds."""
import pytest
from unittest.mock import AsyncMock, patch

from splintarr.services.discord import DiscordNotificationService


class TestSendSearchStarted:
    """Test send_search_started Discord embed."""

    @pytest.mark.asyncio
    async def test_sends_blue_embed(self):
        service = DiscordNotificationService("https://discord.com/api/webhooks/test")
        with patch.object(service, "_send_embed", new_callable=AsyncMock, return_value=True) as mock:
            result = await service.send_search_started(
                search_name="Missing TV",
                instance_name="Sonarr Main",
                strategy="missing",
                estimated_items=20,
            )
            assert result is True
            embed = mock.call_args[0][0]
            assert embed["color"] == 0x3498DB  # COLOR_BLUE
            assert "Missing TV" in embed["title"]
            assert "Started" in embed["title"]

    @pytest.mark.asyncio
    async def test_embed_includes_details(self):
        service = DiscordNotificationService("https://discord.com/api/webhooks/test")
        with patch.object(service, "_send_embed", new_callable=AsyncMock, return_value=True) as mock:
            await service.send_search_started(
                search_name="Cutoff Upgrades",
                instance_name="Sonarr 4K",
                strategy="cutoff",
                estimated_items=15,
            )
            embed = mock.call_args[0][0]
            assert "Sonarr 4K" in embed["description"]
            assert "cutoff" in embed["description"]
            assert "15" in embed["description"]
            assert "footer" in embed
            assert "timestamp" in embed
