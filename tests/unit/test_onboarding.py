"""
Unit tests for onboarding state helper.

Tests verify correct behavior for:
- Fresh user with no data (step 1)
- User with instances but no library (step 2)
- User with library but no queues (step 3)
- Fully onboarded user (all steps done)
- Notification and Prowlarr flag detection
"""

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from splintarr.api.onboarding import get_onboarding_state
from splintarr.models.instance import Instance
from splintarr.models.library import LibraryItem
from splintarr.models.notification import NotificationConfig
from splintarr.models.prowlarr import ProwlarrConfig
from splintarr.models.search_history import SearchHistory
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User


@pytest.fixture
def user(db_session: Session) -> User:
    """Create a test user."""
    user = User(
        username="testuser",
        password_hash="hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def other_user(db_session: Session) -> User:
    """Create a second user to verify ownership isolation."""
    other = User(
        username="otheruser",
        password_hash="hash",
        is_active=True,
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    return other


@pytest.fixture
def instance(db_session: Session, user: User) -> Instance:
    """Create a test instance for the user."""
    inst = Instance(
        user_id=user.id,
        name="Test Sonarr",
        instance_type="sonarr",
        url="https://sonarr.example.com",
        api_key="encrypted-key",
        is_active=True,
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)
    return inst


class TestNoInstances:
    """Fresh user with no data should be at step 1."""

    def test_no_instances(self, db_session: Session, user: User):
        """Fresh user should have everything at 0 and current_step=1."""
        state = get_onboarding_state(db_session, user.id)

        assert state["has_instances"] is False
        assert state["has_library"] is False
        assert state["has_queues"] is False
        assert state["has_searches"] is False
        assert state["has_notifications"] is False
        assert state["has_prowlarr"] is False
        assert state["instance_count"] == 0
        assert state["library_count"] == 0
        assert state["queue_count"] == 0
        assert state["search_count"] == 0
        assert state["current_step"] == 1

    def test_first_step_is_current(self, db_session: Session, user: User):
        """First step should have status 'current' for a fresh user."""
        state = get_onboarding_state(db_session, user.id)
        steps = state["steps"]

        assert steps[0]["name"] == "Add Instance"
        assert steps[0]["status"] == "current"
        assert steps[1]["status"] == "future"
        assert steps[2]["status"] == "future"
        assert steps[3]["status"] == "future"

    def test_steps_have_required_keys(self, db_session: Session, user: User):
        """Each step should have name, status, url, and action keys."""
        state = get_onboarding_state(db_session, user.id)
        for step in state["steps"]:
            assert "name" in step
            assert "status" in step
            assert "url" in step
            assert "action" in step

    def test_other_user_data_not_counted(
        self, db_session: Session, user: User, other_user: User
    ):
        """Data from another user should not affect this user's onboarding state."""
        # Create instance for other user
        other_inst = Instance(
            user_id=other_user.id,
            name="Other Sonarr",
            instance_type="sonarr",
            url="https://other.example.com",
            api_key="other-key",
            is_active=True,
        )
        db_session.add(other_inst)
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)
        assert state["has_instances"] is False
        assert state["instance_count"] == 0
        assert state["current_step"] == 1


class TestHasInstancesNoLibrary:
    """User with instances but no library should be at step 2."""

    def test_has_instances_no_library(
        self, db_session: Session, user: User, instance: Instance
    ):
        """User with 1 instance and no library should be at step 2."""
        state = get_onboarding_state(db_session, user.id)

        assert state["has_instances"] is True
        assert state["has_library"] is False
        assert state["instance_count"] == 1
        assert state["library_count"] == 0
        assert state["current_step"] == 2

    def test_step_statuses_at_step_2(
        self, db_session: Session, user: User, instance: Instance
    ):
        """At step 2, first step done, second current, rest future."""
        state = get_onboarding_state(db_session, user.id)
        steps = state["steps"]

        assert steps[0]["status"] == "done"
        assert steps[1]["status"] == "current"
        assert steps[2]["status"] == "future"
        assert steps[3]["status"] == "future"


class TestHasLibraryNoQueues:
    """User with instances + library but no queues should be at step 3."""

    def test_has_library_no_queues(
        self, db_session: Session, user: User, instance: Instance
    ):
        """User with instance + library items but no queues should be at step 3."""
        # Add library item
        item = LibraryItem(
            instance_id=instance.id,
            content_type="series",
            external_id=1,
            title="Test Show",
            episode_count=10,
            episode_have=5,
        )
        db_session.add(item)
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)

        assert state["has_instances"] is True
        assert state["has_library"] is True
        assert state["has_queues"] is False
        assert state["library_count"] == 1
        assert state["queue_count"] == 0
        assert state["current_step"] == 3

    def test_step_statuses_at_step_3(
        self, db_session: Session, user: User, instance: Instance
    ):
        """At step 3, first two done, third current, last future."""
        item = LibraryItem(
            instance_id=instance.id,
            content_type="movie",
            external_id=42,
            title="Test Movie",
            episode_count=1,
            episode_have=0,
        )
        db_session.add(item)
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)
        steps = state["steps"]

        assert steps[0]["status"] == "done"
        assert steps[1]["status"] == "done"
        assert steps[2]["status"] == "current"
        assert steps[3]["status"] == "future"


class TestFullyOnboarded:
    """User with all 4 steps done should have all steps 'done'."""

    def test_fully_onboarded(
        self, db_session: Session, user: User, instance: Instance
    ):
        """User with instances, library, queues, and searches should be fully onboarded."""
        # Add library item
        item = LibraryItem(
            instance_id=instance.id,
            content_type="series",
            external_id=1,
            title="Test Show",
            episode_count=10,
            episode_have=5,
        )
        db_session.add(item)

        # Add search queue
        queue = SearchQueue(
            instance_id=instance.id,
            name="Test Queue",
            strategy="missing",
            status="pending",
            is_active=True,
        )
        db_session.add(queue)

        # Add search history
        history = SearchHistory(
            instance_id=instance.id,
            search_name="Test Search",
            strategy="missing",
            status="success",
            started_at=datetime.utcnow(),
            items_searched=10,
            items_found=5,
        )
        db_session.add(history)
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)

        assert state["has_instances"] is True
        assert state["has_library"] is True
        assert state["has_queues"] is True
        assert state["has_searches"] is True
        assert state["current_step"] == 4

    def test_all_steps_done(
        self, db_session: Session, user: User, instance: Instance
    ):
        """When fully onboarded, all steps should have status 'done'."""
        item = LibraryItem(
            instance_id=instance.id,
            content_type="series",
            external_id=1,
            title="Test Show",
            episode_count=10,
            episode_have=5,
        )
        queue = SearchQueue(
            instance_id=instance.id,
            name="Test Queue",
            strategy="missing",
            status="pending",
            is_active=True,
        )
        history = SearchHistory(
            instance_id=instance.id,
            search_name="Test Search",
            strategy="missing",
            status="success",
            started_at=datetime.utcnow(),
            items_searched=10,
            items_found=5,
        )
        db_session.add_all([item, queue, history])
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)
        steps = state["steps"]

        assert all(s["status"] == "done" for s in steps)

    def test_has_queues_no_searches_is_step_4(
        self, db_session: Session, user: User, instance: Instance
    ):
        """User with queues but no search history should be at step 4 (current)."""
        item = LibraryItem(
            instance_id=instance.id,
            content_type="series",
            external_id=1,
            title="Test Show",
            episode_count=10,
            episode_have=5,
        )
        queue = SearchQueue(
            instance_id=instance.id,
            name="Test Queue",
            strategy="missing",
            status="pending",
            is_active=True,
        )
        db_session.add_all([item, queue])
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)

        assert state["has_queues"] is True
        assert state["has_searches"] is False
        assert state["current_step"] == 4

        steps = state["steps"]
        assert steps[0]["status"] == "done"
        assert steps[1]["status"] == "done"
        assert steps[2]["status"] == "done"
        assert steps[3]["status"] == "current"


class TestNotificationsAndProwlarrFlags:
    """Verify has_notifications and has_prowlarr boolean flags."""

    def test_no_notifications_no_prowlarr(self, db_session: Session, user: User):
        """Fresh user should have both flags False."""
        state = get_onboarding_state(db_session, user.id)

        assert state["has_notifications"] is False
        assert state["has_prowlarr"] is False

    def test_has_notifications(self, db_session: Session, user: User):
        """User with NotificationConfig should have has_notifications=True."""
        config = NotificationConfig(
            user_id=user.id,
            webhook_url="encrypted-webhook-url",
            is_active=True,
        )
        db_session.add(config)
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)
        assert state["has_notifications"] is True

    def test_has_prowlarr(self, db_session: Session, user: User):
        """User with ProwlarrConfig should have has_prowlarr=True."""
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr:9696",
            encrypted_api_key="encrypted-key",
            is_active=True,
        )
        db_session.add(config)
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)
        assert state["has_prowlarr"] is True

    def test_has_both_notifications_and_prowlarr(
        self, db_session: Session, user: User
    ):
        """User with both configs should have both flags True."""
        notif = NotificationConfig(
            user_id=user.id,
            webhook_url="encrypted-webhook-url",
            is_active=True,
        )
        prowlarr = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr:9696",
            encrypted_api_key="encrypted-key",
            is_active=True,
        )
        db_session.add_all([notif, prowlarr])
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)
        assert state["has_notifications"] is True
        assert state["has_prowlarr"] is True

    def test_other_user_configs_not_counted(
        self, db_session: Session, user: User, other_user: User
    ):
        """Notification/Prowlarr configs from other users should not affect this user."""
        notif = NotificationConfig(
            user_id=other_user.id,
            webhook_url="other-webhook",
            is_active=True,
        )
        prowlarr = ProwlarrConfig(
            user_id=other_user.id,
            url="http://other-prowlarr:9696",
            encrypted_api_key="other-key",
            is_active=True,
        )
        db_session.add_all([notif, prowlarr])
        db_session.commit()

        state = get_onboarding_state(db_session, user.id)
        assert state["has_notifications"] is False
        assert state["has_prowlarr"] is False
