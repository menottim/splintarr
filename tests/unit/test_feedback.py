"""
Unit tests for FeedbackCheckService (splintarr.services.feedback).

Tests the search-result feedback loop that polls Sonarr/Radarr command
statuses to detect whether content was actually grabbed.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from splintarr.models.instance import Instance
from splintarr.models.library import LibraryItem
from splintarr.models.search_history import SearchHistory
from splintarr.services.feedback import FeedbackCheckService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_history(
    db,
    instance_id: int = 1,
    search_metadata: str | None = None,
) -> SearchHistory:
    """Create and persist a SearchHistory record."""
    history = SearchHistory(
        instance_id=instance_id,
        search_queue_id=None,
        search_name="Test Search",
        strategy="missing",
        started_at=datetime.utcnow(),
        status="success",
        items_searched=1,
        items_found=1,
        searches_triggered=1,
        errors_encountered=0,
        search_metadata=search_metadata,
    )
    db.add(history)
    db.commit()
    db.refresh(history)
    return history


def _make_instance(
    db,
    instance_type: str = "sonarr",
    user_id: int = 1,
) -> Instance:
    """Create and persist an Instance record."""
    inst = Instance(
        user_id=user_id,
        name="Test Instance",
        instance_type=instance_type,
        url="http://localhost:8989",
        api_key="encrypted_api_key_placeholder",
        is_active=True,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _make_library_item(
    db,
    instance_id: int,
    external_id: int,
    content_type: str = "series",
    title: str = "Test Series",
) -> LibraryItem:
    """Create and persist a LibraryItem record."""
    item = LibraryItem(
        instance_id=instance_id,
        content_type=content_type,
        external_id=external_id,
        title=title,
        episode_count=10,
        episode_have=5,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _make_user(db) -> int:
    """Create a minimal user and return its id."""
    from splintarr.models.user import User

    user = User(
        username="testuser",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$fakesaltfakesalt$fakehashfakehash",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


# ---------------------------------------------------------------------------
# Test: no history record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_history_record(db_session):
    """Missing history record returns {checked: 0, grabs: 0}."""
    service = FeedbackCheckService(db_session)
    result = await service.check_search_results(history_id=9999, instance_id=1)
    assert result == {"checked": 0, "grabs": 0}


# ---------------------------------------------------------------------------
# Test: no searchable commands in metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_searchable_commands(db_session):
    """Metadata with only skipped entries returns {checked: 0, grabs: 0}."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, user_id=user_id)
    metadata = json.dumps(
        [
            {"item": "Some Show S01E01", "action": "skipped", "reason": "cooldown"},
            {"item": "Some Show S01E02", "action": "skipped", "reason": "excluded"},
        ]
    )
    history = _make_history(db_session, instance_id=instance.id, search_metadata=metadata)

    service = FeedbackCheckService(db_session)
    result = await service.check_search_results(history_id=history.id, instance_id=instance.id)
    assert result == {"checked": 0, "grabs": 0}


# ---------------------------------------------------------------------------
# Test: command completed + episode has file -> grab confirmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sonarr_grab_confirmed(db_session):
    """Completed Sonarr command with hasFile=True records a grab."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, instance_type="sonarr", user_id=user_id)
    lib_item = _make_library_item(
        db_session,
        instance_id=instance.id,
        external_id=42,
        content_type="series",
        title="Breaking Bad",
    )
    assert lib_item.grabs_confirmed == 0

    metadata = json.dumps(
        [
            {
                "item": "Breaking Bad S01E01",
                "action": "EpisodeSearch",
                "item_id": 123,
                "series_id": 42,
                "command_id": 555,
                "result": "sent",
            },
        ]
    )
    history = _make_history(db_session, instance_id=instance.id, search_metadata=metadata)

    with patch("splintarr.services.feedback.decrypt_api_key", return_value="a" * 32):
        with patch("splintarr.services.feedback.SonarrClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get_command_status.return_value = {"status": "completed"}
            mock_client.get_episodes.return_value = [
                {"id": 123, "hasFile": True},
                {"id": 124, "hasFile": False},
            ]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            service = FeedbackCheckService(db_session)
            result = await service.check_search_results(
                history_id=history.id, instance_id=instance.id
            )

    assert result == {"checked": 1, "grabs": 1}

    # LibraryItem should have been updated
    db_session.refresh(lib_item)
    assert lib_item.grabs_confirmed == 1
    assert lib_item.last_grab_at is not None

    # Metadata should be enriched
    db_session.refresh(history)
    enriched = json.loads(history.search_metadata)
    assert enriched[0]["grab_confirmed"] is True


# ---------------------------------------------------------------------------
# Test: command completed + no file -> grab_confirmed = False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sonarr_no_grab(db_session):
    """Completed command but episode still missing -> grab_confirmed=False."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, instance_type="sonarr", user_id=user_id)

    metadata = json.dumps(
        [
            {
                "item": "Lost S02E03",
                "action": "EpisodeSearch",
                "item_id": 200,
                "series_id": 10,
                "command_id": 600,
                "result": "sent",
            },
        ]
    )
    history = _make_history(db_session, instance_id=instance.id, search_metadata=metadata)

    with patch("splintarr.services.feedback.decrypt_api_key", return_value="a" * 32):
        with patch("splintarr.services.feedback.SonarrClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get_command_status.return_value = {"status": "completed"}
            mock_client.get_episodes.return_value = [
                {"id": 200, "hasFile": False},
            ]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            service = FeedbackCheckService(db_session)
            result = await service.check_search_results(
                history_id=history.id, instance_id=instance.id
            )

    assert result == {"checked": 1, "grabs": 0}

    db_session.refresh(history)
    enriched = json.loads(history.search_metadata)
    assert enriched[0]["grab_confirmed"] is False


# ---------------------------------------------------------------------------
# Test: command not completed -> grab_confirmed = False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_not_completed(db_session):
    """Command still queued/running -> grab_confirmed=False."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, instance_type="sonarr", user_id=user_id)

    metadata = json.dumps(
        [
            {
                "item": "Dexter S01E01",
                "action": "EpisodeSearch",
                "item_id": 300,
                "series_id": 20,
                "command_id": 700,
                "result": "sent",
            },
        ]
    )
    history = _make_history(db_session, instance_id=instance.id, search_metadata=metadata)

    with patch("splintarr.services.feedback.decrypt_api_key", return_value="a" * 32):
        with patch("splintarr.services.feedback.SonarrClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get_command_status.return_value = {"status": "queued"}
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            service = FeedbackCheckService(db_session)
            result = await service.check_search_results(
                history_id=history.id, instance_id=instance.id
            )

    assert result == {"checked": 1, "grabs": 0}

    db_session.refresh(history)
    enriched = json.loads(history.search_metadata)
    assert enriched[0]["grab_confirmed"] is False


# ---------------------------------------------------------------------------
# Test: Radarr grab confirmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_radarr_grab_confirmed(db_session):
    """Radarr completed command with hasFile=True -> grab confirmed."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, instance_type="radarr", user_id=user_id)
    lib_item = _make_library_item(
        db_session,
        instance_id=instance.id,
        external_id=50,
        content_type="movie",
        title="Inception",
    )

    metadata = json.dumps(
        [
            {
                "item": "Inception (2010)",
                "action": "MoviesSearch",
                "item_id": 50,
                "series_id": None,
                "command_id": 800,
                "result": "sent",
            },
        ]
    )
    history = _make_history(db_session, instance_id=instance.id, search_metadata=metadata)

    with patch("splintarr.services.feedback.decrypt_api_key", return_value="a" * 32):
        with patch("splintarr.services.feedback.RadarrClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get_command_status.return_value = {"status": "completed"}
            mock_client.get_movies.return_value = {"id": 50, "hasFile": True}
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            service = FeedbackCheckService(db_session)
            result = await service.check_search_results(
                history_id=history.id, instance_id=instance.id
            )

    assert result == {"checked": 1, "grabs": 1}

    db_session.refresh(lib_item)
    assert lib_item.grabs_confirmed == 1


# ---------------------------------------------------------------------------
# Test: client exception -> caught gracefully, partial results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_exception_partial_results(db_session):
    """Client-level error during command check is caught; partial results returned."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, instance_type="sonarr", user_id=user_id)

    metadata = json.dumps(
        [
            {
                "item": "Show A S01E01",
                "action": "EpisodeSearch",
                "item_id": 1,
                "series_id": 1,
                "command_id": 901,
                "result": "sent",
            },
            {
                "item": "Show B S01E01",
                "action": "EpisodeSearch",
                "item_id": 2,
                "series_id": 2,
                "command_id": 902,
                "result": "sent",
            },
        ]
    )
    history = _make_history(db_session, instance_id=instance.id, search_metadata=metadata)

    with patch("splintarr.services.feedback.decrypt_api_key", return_value="a" * 32):
        with patch("splintarr.services.feedback.SonarrClient") as MockClient:
            mock_client = AsyncMock()
            # First command succeeds (completed, file found)
            # Second command raises an exception
            mock_client.get_command_status.side_effect = [
                {"status": "completed"},
                Exception("API timeout"),
            ]
            mock_client.get_episodes.return_value = [{"id": 1, "hasFile": True}]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            service = FeedbackCheckService(db_session)
            result = await service.check_search_results(
                history_id=history.id, instance_id=instance.id
            )

    # First command was checked successfully (grab), second had an error (unknown)
    assert result["checked"] == 2
    assert result["grabs"] == 1

    db_session.refresh(history)
    enriched = json.loads(history.search_metadata)
    assert enriched[0]["grab_confirmed"] is True
    assert enriched[1]["grab_confirmed"] is None  # unknown due to error


# ---------------------------------------------------------------------------
# Test: invalid JSON in search_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_metadata_json(db_session):
    """Invalid JSON in search_metadata returns {checked: 0, grabs: 0}."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, user_id=user_id)
    history = _make_history(
        db_session,
        instance_id=instance.id,
        search_metadata="this is not json!",
    )

    service = FeedbackCheckService(db_session)
    result = await service.check_search_results(history_id=history.id, instance_id=instance.id)
    assert result == {"checked": 0, "grabs": 0}


# ---------------------------------------------------------------------------
# Test: no instance record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_instance_record(db_session):
    """Missing instance returns {checked: 0, grabs: 0}."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, user_id=user_id)

    metadata = json.dumps(
        [
            {
                "item": "Show S01E01",
                "action": "EpisodeSearch",
                "item_id": 1,
                "series_id": 1,
                "command_id": 100,
                "result": "sent",
            },
        ]
    )
    history = _make_history(db_session, instance_id=instance.id, search_metadata=metadata)

    service = FeedbackCheckService(db_session)
    # Use a non-existent instance_id
    result = await service.check_search_results(history_id=history.id, instance_id=9999)
    assert result == {"checked": 0, "grabs": 0}


# ---------------------------------------------------------------------------
# Test: metadata is a dict instead of a list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_not_a_list(db_session):
    """search_metadata that is valid JSON but not a list returns empty."""
    user_id = _make_user(db_session)
    instance = _make_instance(db_session, user_id=user_id)
    history = _make_history(
        db_session,
        instance_id=instance.id,
        search_metadata=json.dumps({"not": "a list"}),
    )

    service = FeedbackCheckService(db_session)
    result = await service.check_search_results(history_id=history.id, instance_id=instance.id)
    assert result == {"checked": 0, "grabs": 0}
