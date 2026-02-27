"""
Unit tests for dashboard bug fixes.

Tests verify correct behavior for:
- Bug 1: active_queues count uses correct status value (in_progress, not running)
- Bug 2: successful_searches uses correct status values (success/partial_success, not completed)
- Bug 3: Dashboard pagination validates page/per_page query params
- Bug 4: dashboard_add_instance validates instance_type
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from splintarr.api.dashboard import get_dashboard_stats
from splintarr.models.instance import Instance
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
def instance(db_session: Session, user: User) -> Instance:
    """Create a test instance."""
    inst = Instance(
        user_id=user.id,
        name="Test Sonarr",
        instance_type="sonarr",
        url="https://sonarr.example.com",
        api_key="key",
        is_active=True,
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)
    return inst


class TestBug1ActiveQueuesStatus:
    """Bug 1: active_queues should count queues with status 'in_progress', not 'running'."""

    async def test_active_queues_counts_in_progress(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Queues with status 'in_progress' should be counted as active."""
        queue = SearchQueue(
            instance_id=instance.id,
            name="In Progress Search",
            strategy="missing",
            status="in_progress",
            is_active=True,
        )
        db_session.add(queue)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["search_queues"]["active"] == 1

    async def test_active_queues_counts_pending(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Queues with status 'pending' should be counted as active."""
        queue = SearchQueue(
            instance_id=instance.id,
            name="Pending Search",
            strategy="missing",
            status="pending",
            is_active=True,
        )
        db_session.add(queue)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["search_queues"]["active"] == 1

    async def test_active_queues_excludes_completed(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Queues with status 'completed' should not be counted as active."""
        queue = SearchQueue(
            instance_id=instance.id,
            name="Completed Search",
            strategy="missing",
            status="completed",
            is_active=True,
        )
        db_session.add(queue)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["search_queues"]["active"] == 0

    async def test_active_queues_excludes_failed(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Queues with status 'failed' should not be counted as active."""
        queue = SearchQueue(
            instance_id=instance.id,
            name="Failed Search",
            strategy="missing",
            status="failed",
            is_active=True,
        )
        db_session.add(queue)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["search_queues"]["active"] == 0

    async def test_active_queues_excludes_inactive_pending(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Queues with is_active=False should not be counted as active even if pending."""
        queue = SearchQueue(
            instance_id=instance.id,
            name="Inactive Pending Search",
            strategy="missing",
            status="pending",
            is_active=False,
        )
        db_session.add(queue)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["search_queues"]["active"] == 0

    async def test_active_queues_counts_both_pending_and_in_progress(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Both pending and in_progress active queues should be counted."""
        q1 = SearchQueue(
            instance_id=instance.id,
            name="Pending Search",
            strategy="missing",
            status="pending",
            is_active=True,
        )
        q2 = SearchQueue(
            instance_id=instance.id,
            name="In Progress Search",
            strategy="recent",
            status="in_progress",
            is_active=True,
        )
        db_session.add_all([q1, q2])
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["search_queues"]["active"] == 2


class TestBug2SuccessfulSearchesStatus:
    """Bug 2: successful_searches should use 'success'/'partial_success', not 'completed'."""

    async def test_success_rate_counts_success(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Searches with status 'success' should count toward success rate."""
        now = datetime.utcnow()
        history = SearchHistory(
            instance_id=instance.id,
            search_name="Successful Search",
            strategy="missing",
            status="success",
            started_at=now,
            items_searched=10,
            items_found=5,
        )
        db_session.add(history)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["searches"]["success_rate"] == 100.0

    async def test_success_rate_counts_partial_success(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Searches with status 'partial_success' should count toward success rate."""
        now = datetime.utcnow()
        history = SearchHistory(
            instance_id=instance.id,
            search_name="Partial Success Search",
            strategy="missing",
            status="partial_success",
            started_at=now,
            items_searched=10,
            items_found=3,
        )
        db_session.add(history)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["searches"]["success_rate"] == 100.0

    async def test_success_rate_excludes_failed(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Searches with status 'failed' should not count toward success rate."""
        now = datetime.utcnow()
        history = SearchHistory(
            instance_id=instance.id,
            search_name="Failed Search",
            strategy="missing",
            status="failed",
            started_at=now,
            items_searched=10,
            items_found=0,
        )
        db_session.add(history)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        assert stats["searches"]["success_rate"] == 0.0

    async def test_success_rate_mixed_statuses(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Success rate should correctly calculate with mixed success/failed searches."""
        now = datetime.utcnow()
        for i, s in enumerate(["success", "partial_success", "failed", "failed"]):
            history = SearchHistory(
                instance_id=instance.id,
                search_name=f"Search {i}",
                strategy="missing",
                status=s,
                started_at=now,
                items_searched=10,
                items_found=5 if s != "failed" else 0,
            )
            db_session.add(history)
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        # 2 successful out of 4 total = 50%
        assert stats["searches"]["success_rate"] == 50.0

    async def test_success_rate_old_searches_excluded(
        self, db_session: Session, user: User, instance: Instance
    ):
        """Searches older than a week should not affect the success rate."""
        old_time = datetime.utcnow() - timedelta(days=10)
        now = datetime.utcnow()

        # Old successful search (should NOT count)
        old_history = SearchHistory(
            instance_id=instance.id,
            search_name="Old Success",
            strategy="missing",
            status="success",
            started_at=old_time,
            items_searched=10,
            items_found=5,
        )
        # Recent failed search (should count)
        new_history = SearchHistory(
            instance_id=instance.id,
            search_name="Recent Failed",
            strategy="missing",
            status="failed",
            started_at=now,
            items_searched=10,
            items_found=0,
        )
        db_session.add_all([old_history, new_history])
        db_session.commit()

        stats = await get_dashboard_stats(db_session, user)
        # Only the recent failed search counts -> 0% success rate
        assert stats["searches"]["success_rate"] == 0.0


class TestBug3PaginationValidation:
    """Bug 3: page and per_page should be validated with Query constraints.

    We verify the route signature uses FastAPI Query() with ge/le constraints
    by inspecting the route parameters directly.
    """

    def test_page_has_ge_constraint(self):
        """The page parameter should have ge=1 constraint."""
        from splintarr.api.dashboard import router

        route = None
        for r in router.routes:
            if hasattr(r, "path") and r.path == "/dashboard/search-history":
                route = r
                break

        assert route is not None, "Route /dashboard/search-history not found"

        page_param = None
        for param in route.dependant.query_params:
            if param.name == "page":
                page_param = param
                break

        assert page_param is not None, "page parameter not found"
        # Check that ge=1 is enforced
        ge_found = False
        for meta in page_param.field_info.metadata:
            if hasattr(meta, "ge") and meta.ge == 1:
                ge_found = True
                break
        assert ge_found, "page parameter must have ge=1 constraint"

    def test_per_page_has_ge_and_le_constraints(self):
        """The per_page parameter should have ge=1 and le=100 constraints."""
        from splintarr.api.dashboard import router

        route = None
        for r in router.routes:
            if hasattr(r, "path") and r.path == "/dashboard/search-history":
                route = r
                break

        assert route is not None, "Route /dashboard/search-history not found"

        per_page_param = None
        for param in route.dependant.query_params:
            if param.name == "per_page":
                per_page_param = param
                break

        assert per_page_param is not None, "per_page parameter not found"

        ge_found = False
        le_found = False
        for meta in per_page_param.field_info.metadata:
            if hasattr(meta, "ge") and meta.ge == 1:
                ge_found = True
            if hasattr(meta, "le") and meta.le == 100:
                le_found = True

        assert ge_found, "per_page parameter must have ge=1 constraint"
        assert le_found, "per_page parameter must have le=100 constraint"

    def test_page_default_is_1(self):
        """The page parameter should default to 1."""
        from splintarr.api.dashboard import router

        route = None
        for r in router.routes:
            if hasattr(r, "path") and r.path == "/dashboard/search-history":
                route = r
                break

        assert route is not None

        page_param = None
        for param in route.dependant.query_params:
            if param.name == "page":
                page_param = param
                break

        assert page_param is not None
        assert page_param.field_info.default == 1

    def test_per_page_default_is_20(self):
        """The per_page parameter should default to 20."""
        from splintarr.api.dashboard import router

        route = None
        for r in router.routes:
            if hasattr(r, "path") and r.path == "/dashboard/search-history":
                route = r
                break

        assert route is not None

        per_page_param = None
        for param in route.dependant.query_params:
            if param.name == "per_page":
                per_page_param = param
                break

        assert per_page_param is not None
        assert per_page_param.field_info.default == 20


class TestBug4InstanceTypeValidation:
    """Bug 4: dashboard_add_instance should validate instance_type.

    We verify by inspecting the source code of the endpoint to confirm
    the validation is present.
    """

    def test_dashboard_add_instance_has_type_validation(self):
        """The dashboard_add_instance endpoint should validate instance_type."""
        import inspect

        from splintarr.api.dashboard import dashboard_add_instance

        source = inspect.getsource(dashboard_add_instance)
        assert 'instance_type not in ("sonarr", "radarr")' in source

    def test_dashboard_add_instance_returns_error_for_invalid_type(self):
        """The validation should return a 400 error with descriptive message."""
        import inspect

        from splintarr.api.dashboard import dashboard_add_instance

        source = inspect.getsource(dashboard_add_instance)
        assert "Invalid instance type" in source
        assert "HTTP_400_BAD_REQUEST" in source

    def test_setup_instance_also_validates_type(self):
        """The setup_instance_create endpoint should also validate instance_type."""
        import inspect

        from splintarr.api.dashboard import setup_instance_create

        source = inspect.getsource(setup_instance_create)
        assert 'instance_type not in ["sonarr", "radarr"]' in source

    def test_valid_instance_types_are_sonarr_and_radarr(self):
        """Only 'sonarr' and 'radarr' should be valid instance types."""
        import inspect

        from splintarr.api.dashboard import dashboard_add_instance

        source = inspect.getsource(dashboard_add_instance)
        assert '"sonarr"' in source
        assert '"radarr"' in source
