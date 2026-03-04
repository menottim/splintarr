"""Tests for budget alert Discord notification."""
import pytest
from unittest.mock import AsyncMock, patch

from splintarr.services.discord import DiscordNotificationService


class TestSendBudgetAlert:
    """Test send_budget_alert Discord embed."""

    @pytest.mark.asyncio
    async def test_sends_red_embed(self):
        service = DiscordNotificationService("https://discord.com/api/webhooks/test")
        with patch.object(service, "_send_embed", new_callable=AsyncMock, return_value=True) as mock:
            result = await service.send_budget_alert(
                indexer_name="NZBgeek",
                queries_used=85,
                query_limit=100,
                percent_used=85,
            )
            assert result is True
            embed = mock.call_args[0][0]
            assert "NZBgeek" in embed["title"]
            assert embed["color"] == 0xE74C3C  # COLOR_RED
            assert "85" in embed["description"]
            assert "100" in embed["description"]

    @pytest.mark.asyncio
    async def test_embed_includes_percentage(self):
        service = DiscordNotificationService("https://discord.com/api/webhooks/test")
        with patch.object(service, "_send_embed", new_callable=AsyncMock, return_value=True) as mock:
            await service.send_budget_alert(
                indexer_name="NZBgeek",
                queries_used=90,
                query_limit=100,
                percent_used=90,
            )
            embed = mock.call_args[0][0]
            assert "90%" in embed["description"]
