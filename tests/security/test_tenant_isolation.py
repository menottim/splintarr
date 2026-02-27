"""
Tenant isolation tests for search history cleanup.

Verifies that cleanup_old_history correctly scopes deletions to only
the requesting user's instances, preventing cross-tenant data deletion.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from splintarr.models import Instance, SearchHistory, User
from splintarr.services.search_history import SearchHistoryService


@pytest.fixture
def user_a(db_session: Session) -> User:
    """Create User A in the database."""
    user = User(
        id=1,
        username="user_a",
        password_hash="hashed_a",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def user_b(db_session: Session) -> User:
    """Create User B in the database."""
    user = User(
        id=2,
        username="user_b",
        password_hash="hashed_b",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def instance_a(db_session: Session, user_a: User) -> Instance:
    """Create an instance owned by User A."""
    instance = Instance(
        id=10,
        user_id=user_a.id,
        name="User A Sonarr",
        instance_type="sonarr",
        url="http://sonarr-a.local:8989",
        api_key="encrypted_key_a",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)
    return instance


@pytest.fixture
def instance_b(db_session: Session, user_b: User) -> Instance:
    """Create an instance owned by User B."""
    instance = Instance(
        id=20,
        user_id=user_b.id,
        name="User B Radarr",
        instance_type="radarr",
        url="http://radarr-b.local:7878",
        api_key="encrypted_key_b",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)
    return instance


def _create_history_records(
    db_session: Session,
    instance_id: int,
    count: int,
    days_old: int,
) -> list[SearchHistory]:
    """Helper to create history records at a given age."""
    records = []
    for i in range(count):
        record = SearchHistory(
            instance_id=instance_id,
            search_name=f"search_{instance_id}_{i}",
            strategy="missing",
            started_at=datetime.utcnow() - timedelta(days=days_old, hours=i),
            completed_at=datetime.utcnow() - timedelta(days=days_old, hours=i - 1),
            duration_seconds=3600,
            status="success",
            items_searched=10,
            items_found=5,
            searches_triggered=5,
            errors_encountered=0,
        )
        db_session.add(record)
        records.append(record)
    db_session.commit()
    return records


class TestTenantIsolation:
    """Verify that cleanup_old_history respects tenant boundaries."""

    def test_user_a_cleanup_does_not_delete_user_b_history(
        self,
        db_session: Session,
        user_a: User,
        user_b: User,
        instance_a: Instance,
        instance_b: Instance,
    ) -> None:
        """User A's cleanup must not delete User B's history records."""
        # Eagerly capture IDs before cleanup expires session objects
        user_a_id = user_a.id
        inst_a_id = instance_a.id
        inst_b_id = instance_b.id

        # Create old records for both users (120 days old, cutoff is 90)
        _create_history_records(db_session, inst_a_id, 3, days_old=120)
        _create_history_records(db_session, inst_b_id, 4, days_old=120)

        service = SearchHistoryService(lambda: db_session)

        # User A triggers cleanup
        deleted = service.cleanup_old_history(days=90, user_id=user_a_id)

        # Only User A's 3 records should be deleted
        assert deleted == 3

        # User B's records must still exist
        remaining_b = (
            db_session.query(SearchHistory)
            .filter(SearchHistory.instance_id == inst_b_id)
            .all()
        )
        assert len(remaining_b) == 4

        # User A's records should be gone
        remaining_a = (
            db_session.query(SearchHistory)
            .filter(SearchHistory.instance_id == inst_a_id)
            .all()
        )
        assert len(remaining_a) == 0

    def test_user_b_cleanup_does_not_delete_user_a_history(
        self,
        db_session: Session,
        user_a: User,
        user_b: User,
        instance_a: Instance,
        instance_b: Instance,
    ) -> None:
        """User B's cleanup must not delete User A's history records."""
        user_b_id = user_b.id
        inst_a_id = instance_a.id
        inst_b_id = instance_b.id

        _create_history_records(db_session, inst_a_id, 5, days_old=100)
        _create_history_records(db_session, inst_b_id, 2, days_old=100)

        service = SearchHistoryService(lambda: db_session)

        # User B triggers cleanup
        deleted = service.cleanup_old_history(days=90, user_id=user_b_id)

        assert deleted == 2

        # User A's records must still exist
        remaining_a = (
            db_session.query(SearchHistory)
            .filter(SearchHistory.instance_id == inst_a_id)
            .all()
        )
        assert len(remaining_a) == 5

    def test_cleanup_without_user_id_deletes_all(
        self,
        db_session: Session,
        user_a: User,
        user_b: User,
        instance_a: Instance,
        instance_b: Instance,
    ) -> None:
        """System-level cleanup (no user_id) deletes history for all users."""
        _create_history_records(db_session, instance_a.id, 3, days_old=120)
        _create_history_records(db_session, instance_b.id, 4, days_old=120)

        service = SearchHistoryService(lambda: db_session)

        deleted = service.cleanup_old_history(days=90)

        assert deleted == 7

        remaining = db_session.query(SearchHistory).all()
        assert len(remaining) == 0

    def test_cleanup_only_deletes_old_records(
        self,
        db_session: Session,
        user_a: User,
        instance_a: Instance,
    ) -> None:
        """Cleanup must only delete records older than the cutoff, not recent ones."""
        user_a_id = user_a.id
        inst_a_id = instance_a.id

        # Old records (should be deleted)
        _create_history_records(db_session, inst_a_id, 2, days_old=120)
        # Recent records (should survive)
        _create_history_records(db_session, inst_a_id, 3, days_old=10)

        service = SearchHistoryService(lambda: db_session)

        deleted = service.cleanup_old_history(days=90, user_id=user_a_id)

        assert deleted == 2

        remaining = (
            db_session.query(SearchHistory)
            .filter(SearchHistory.instance_id == inst_a_id)
            .all()
        )
        assert len(remaining) == 3

    def test_cleanup_returns_correct_count(
        self,
        db_session: Session,
        user_a: User,
        user_b: User,
        instance_a: Instance,
        instance_b: Instance,
    ) -> None:
        """The returned count must accurately reflect only the user's deleted records."""
        user_a_id = user_a.id
        user_b_id = user_b.id
        inst_a_id = instance_a.id
        inst_b_id = instance_b.id

        _create_history_records(db_session, inst_a_id, 6, days_old=200)
        _create_history_records(db_session, inst_b_id, 8, days_old=200)

        service = SearchHistoryService(lambda: db_session)

        count_a = service.cleanup_old_history(days=90, user_id=user_a_id)
        assert count_a == 6

        count_b = service.cleanup_old_history(days=90, user_id=user_b_id)
        assert count_b == 8

    def test_cleanup_with_no_matching_records_returns_zero(
        self,
        db_session: Session,
        user_a: User,
        instance_a: Instance,
    ) -> None:
        """Cleanup returns 0 when user has no old records to delete."""
        # Only recent records
        _create_history_records(db_session, instance_a.id, 5, days_old=10)

        service = SearchHistoryService(lambda: db_session)

        deleted = service.cleanup_old_history(days=90, user_id=user_a.id)

        assert deleted == 0

        # All records should still exist
        remaining = db_session.query(SearchHistory).all()
        assert len(remaining) == 5

    def test_cleanup_user_with_no_instances_deletes_nothing(
        self,
        db_session: Session,
        user_a: User,
        user_b: User,
        instance_b: Instance,
    ) -> None:
        """A user with no instances should not delete any records."""
        # User B has old records, User A has no instances
        _create_history_records(db_session, instance_b.id, 3, days_old=120)

        service = SearchHistoryService(lambda: db_session)

        deleted = service.cleanup_old_history(days=90, user_id=user_a.id)

        assert deleted == 0

        remaining = db_session.query(SearchHistory).all()
        assert len(remaining) == 3
