"""Onboarding state helper for workflow tracking."""

import structlog
from sqlalchemy.orm import Session

from splintarr.models.instance import Instance
from splintarr.models.library import LibraryItem
from splintarr.models.notification import NotificationConfig
from splintarr.models.prowlarr import ProwlarrConfig
from splintarr.models.search_history import SearchHistory
from splintarr.models.search_queue import SearchQueue

logger = structlog.get_logger()


def get_onboarding_state(db: Session, user_id: int) -> dict:
    """Compute onboarding progress for a user.

    Runs 6 lightweight COUNT queries to determine how far the user has
    progressed through the initial setup workflow.  The result dict is
    intended to be passed straight into Jinja2 templates.

    Returns dict with keys:
        has_instances: bool
        has_library: bool
        has_queues: bool
        has_searches: bool
        has_notifications: bool
        has_prowlarr: bool
        instance_count: int
        library_count: int
        queue_count: int
        search_count: int
        current_step: int (1-4)
        steps: list[dict] with {name, status, url, action}
    """
    logger.debug("onboarding_state_requested", user_id=user_id)

    # 1. Count instances owned by the user
    instance_count: int = db.query(Instance).filter(Instance.user_id == user_id).count()

    # 2. Count library items (join through Instance for user scoping)
    library_count: int = (
        db.query(LibraryItem)
        .join(Instance, LibraryItem.instance_id == Instance.id)
        .filter(Instance.user_id == user_id)
        .count()
    )

    # 3. Count search queues (join through Instance)
    queue_count: int = (
        db.query(SearchQueue)
        .join(Instance, SearchQueue.instance_id == Instance.id)
        .filter(Instance.user_id == user_id)
        .count()
    )

    # 4. Count search history entries (join through Instance)
    search_count: int = (
        db.query(SearchHistory)
        .join(Instance, SearchHistory.instance_id == Instance.id)
        .filter(Instance.user_id == user_id)
        .count()
    )

    # 5. Check for notification config
    has_notifications: bool = (
        db.query(NotificationConfig).filter(NotificationConfig.user_id == user_id).count() > 0
    )

    # 6. Check for Prowlarr config
    has_prowlarr: bool = (
        db.query(ProwlarrConfig).filter(ProwlarrConfig.user_id == user_id).count() > 0
    )

    # Derive boolean flags
    has_instances = instance_count > 0
    has_library = library_count > 0
    has_queues = queue_count > 0
    has_searches = search_count > 0

    # Determine current step (1-4)
    if not has_instances:
        current_step = 1
    elif not has_library:
        current_step = 2
    elif not has_queues:
        current_step = 3
    else:
        current_step = 4

    # Build steps list with status for each
    steps = [
        {
            "name": "Add Instance",
            "status": ("done" if has_instances else "current" if current_step == 1 else "future"),
            "url": "/dashboard/instances",
            "action": "Add now",
        },
        {
            "name": "Sync Library",
            "status": ("done" if has_library else "current" if current_step == 2 else "future"),
            "url": "/dashboard/library",
            "action": "Sync now",
        },
        {
            "name": "Create Queue",
            "status": ("done" if has_queues else "current" if current_step == 3 else "future"),
            "url": "/dashboard/search-queues",
            "action": "Create now",
        },
        {
            "name": "Run Searches",
            "status": ("done" if has_searches else "current" if current_step == 4 else "future"),
            "url": "/dashboard/search-queues",
            "action": "Run a search",
        },
    ]

    logger.debug(
        "onboarding_state_computed",
        user_id=user_id,
        current_step=current_step,
        instance_count=instance_count,
        library_count=library_count,
        queue_count=queue_count,
        search_count=search_count,
        has_notifications=has_notifications,
        has_prowlarr=has_prowlarr,
    )

    return {
        "has_instances": has_instances,
        "has_library": has_library,
        "has_queues": has_queues,
        "has_searches": has_searches,
        "has_notifications": has_notifications,
        "has_prowlarr": has_prowlarr,
        "instance_count": instance_count,
        "library_count": library_count,
        "queue_count": queue_count,
        "search_count": search_count,
        "current_step": current_step,
        "steps": steps,
    }
