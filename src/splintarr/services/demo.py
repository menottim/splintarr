"""
Synthetic demo data simulation for Splintarr.

Provides synthetic data generators and a background simulation loop so
the dashboard looks alive before the user connects real instances.
Demo mode auto-disables when the user has both an instance AND a queue.

All synthetic payloads include ``"demo": True`` so consumers can
distinguish them from real data if needed.
"""

import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session, sessionmaker

from splintarr.api.onboarding import get_onboarding_state
from splintarr.core.events import event_bus

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module state — managed by start_simulation / stop_simulation
# ---------------------------------------------------------------------------
_simulation_task: asyncio.Task[None] | None = None


# ---------------------------------------------------------------------------
# Demo mode detection
# ---------------------------------------------------------------------------

def is_demo_active(db: Session, user_id: int) -> bool:
    """Return True when the user has NOT yet created both an instance and a queue."""
    state = get_onboarding_state(db, user_id)
    return not (state["has_instances"] and state["has_queues"])


# ---------------------------------------------------------------------------
# Synthetic data generators
# ---------------------------------------------------------------------------

_DEMO_SERIES = [
    "Breaking Bad",
    "The Wire",
    "Severance",
    "Dark",
    "Better Call Saul",
    "Arcane",
    "Shogun",
    "The Bear",
    "Andor",
    "Fargo",
]


def _time_offset(**kwargs: int) -> str:
    """Return an ISO timestamp offset from now (e.g. minutes=5, hours=1)."""
    return (datetime.now(UTC) - timedelta(**kwargs)).isoformat()


def get_demo_stats() -> dict[str, Any]:
    """Synthetic dashboard stats matching ``/api/dashboard/stats`` shape."""
    return {
        "instances": {"total": 2, "active": 2, "inactive": 0},
        "search_queues": {"total": 2, "active": 1, "paused": 1},
        "searches": {
            "today": 8,
            "this_week": 34,
            "success_rate": 91.5,
            "grab_rate": 12.3,
        },
        "demo": True,
    }


_DEMO_ACTIVITY_ENTRIES = [
    # (name, strategy, status, items_searched, items_found, searches_triggered, offset_min)
    ("Demo Missing Search", "missing", "success", 12, 4, 4, 5),
    ("Demo Cutoff Unmet", "cutoff_unmet", "success", 8, 2, 2, 25),
    ("Demo Missing Search", "missing", "partial_success", 5, 1, 1, 60),
    ("Demo Recent Additions", "recent", "success", 3, 1, 1, 120),
    ("Demo Missing Search", "missing", "failed", 10, 0, 0, 180),
]


def get_demo_activity() -> dict[str, Any]:
    """Synthetic activity matching ``/api/dashboard/activity`` shape."""
    activity = []
    for i, (name, strategy, act_status, searched, found, triggered, offset) in enumerate(
        _DEMO_ACTIVITY_ENTRIES
    ):
        started = datetime.now(UTC) - timedelta(minutes=offset)
        completed = started + timedelta(seconds=random.randint(30, 90))  # noqa: S311
        activity.append({
            "id": 9000 + i,
            "instance_name": "Demo Sonarr",
            "strategy": strategy,
            "status": act_status,
            "items_searched": searched,
            "items_found": found,
            "searches_triggered": triggered,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "search_queue_id": 9000,
            "search_name": name,
        })

    return {"activity": activity, "demo": True}


def get_demo_system_status() -> dict[str, Any]:
    """Synthetic system status matching ``/api/dashboard/system-status`` shape."""
    return {
        "instances": [
            {
                "id": 9001,
                "name": "Demo Sonarr",
                "instance_type": "sonarr",
                "url": "http://sonarr.local:8989",
                "connection_status": "healthy",
                "last_connection_test": _time_offset(minutes=2),
                "consecutive_failures": 0,
                "response_time_ms": 142,
                "connection_error": None,
            },
        ],
        "integrations": {
            "discord": {
                "configured": True,
                "active": True,
                "last_sent_at": _time_offset(hours=1),
            },
            "prowlarr": {
                "configured": True,
                "active": True,
                "last_sync_at": _time_offset(minutes=15),
            },
        },
        "services": {
            "database": {"status": "healthy"},
            "scheduler": {"status": "running", "jobs_count": 3},
        },
        "demo": True,
    }


def get_demo_library_stats() -> dict[str, Any]:
    """Synthetic library stats matching ``/api/library/stats`` shape."""
    return {
        "total_items": 47,
        "complete_count": 28,
        "missing_count": 19,
        "series_count": 47,
        "movie_count": 0,
        "cutoff_unmet_count": 3,
        "demo": True,
    }


def get_demo_indexer_health() -> dict[str, Any]:
    """Synthetic indexer health matching ``/api/dashboard/indexer-health`` shape."""
    return {
        "configured": True,
        "indexers": [
            {
                "name": "NZBgeek",
                "query_limit": 50,
                "queries_used": 12,
                "limits_unit": "day",
                "is_disabled": False,
            },
            {
                "name": "DrunkenSlug",
                "query_limit": 100,
                "queries_used": 34,
                "limits_unit": "day",
                "is_disabled": False,
            },
            {
                "name": "Torznab - 1337x",
                "query_limit": None,
                "queries_used": 8,
                "limits_unit": None,
                "is_disabled": False,
            },
            {
                "name": "NZBFinder",
                "query_limit": 25,
                "queries_used": 24,
                "limits_unit": "day",
                "is_disabled": True,
            },
        ],
        "demo": True,
    }


def get_demo_analytics() -> dict[str, Any]:
    """Synthetic analytics matching ``/api/dashboard/analytics`` shape."""
    return {
        "current": {"searches": 34, "items_found": 12, "grabs": 5},
        "previous": {"searches": 22, "items_found": 8, "grabs": 3},
        "trends": {"searches": 54.5, "items_found": 50.0, "grabs": 66.7},
        "top_series": [
            {"title": "Breaking Bad", "search_count": 8},
            {"title": "The Wire", "search_count": 5},
            {"title": "Severance", "search_count": 3},
        ],
        "demo": True,
    }


# ---------------------------------------------------------------------------
# Simulation loop
# ---------------------------------------------------------------------------

async def _run_simulation_cycle() -> None:
    """Emit a sequence of WS events that make the dashboard feel alive.

    Timeline (~70 s):
        T+0s   stats.updated
        T+10s  search.started
        T+15s  search.item_result  (item 1)
        T+20s  search.item_result  (item 2)
        T+25s  search.item_result  (item 3)
        T+30s  search.completed
        T+35s  activity.updated
        T+40s  status.updated
        T+50s  sync.progress       (45%)
        T+55s  sync.progress       (78%)
        T+60s  sync.completed
        T+65s  stats.updated       (final refresh)
        T+70s  indexer_health.updated
    """
    series_sample = random.sample(_DEMO_SERIES, k=min(3, len(_DEMO_SERIES)))  # noqa: S311

    events: list[tuple[float, str, dict[str, Any]]] = [
        (0, "stats.updated", {"demo": True}),
        (10, "search.started", {
            "queue_id": 9000,
            "queue_name": "Demo Missing Search",
            "strategy": "missing",
            "max_items": 10,
            "demo": True,
        }),
        (15, "search.item_result", {
            "queue_id": 9000,
            "item_name": f"{series_sample[0]} S01E01",
            "result": "found",
            "score": round(random.uniform(70, 95), 1),  # noqa: S311
            "score_reason": "missing + high priority",
            "item_index": 1,
            "total_items": 3,
            "demo": True,
        }),
        (20, "search.item_result", {
            "queue_id": 9000,
            "item_name": f"{series_sample[1]} S02E05",
            "result": random.choice(["found", "not_found"]),  # noqa: S311
            "score": round(random.uniform(50, 80), 1),  # noqa: S311
            "score_reason": "missing + medium priority",
            "item_index": 2,
            "total_items": 3,
            "demo": True,
        }),
        (25, "search.item_result", {
            "queue_id": 9000,
            "item_name": f"{series_sample[2]} S01E03",
            "result": "found",
            "score": round(random.uniform(60, 90), 1),  # noqa: S311
            "score_reason": "missing + low priority",
            "item_index": 3,
            "total_items": 3,
            "demo": True,
        }),
        (30, "search.completed", {
            "queue_id": 9000,
            "queue_name": "Demo Missing Search",
            "status": "success",
            "items_searched": 3,
            "items_found": 2,
            "demo": True,
        }),
        # Signal events — empty dicts trigger AJAX poll on the client,
        # which will hit our demo-intercepted endpoints.
        (35, "activity.updated", {"demo": True}),
        (40, "status.updated", {"demo": True}),
        (50, "sync.progress", {
            "syncing": True,
            "current_instance": "Demo Sonarr",
            "stage": "Fetching episodes",
            "items_synced": 21,
            "items_total": 47,
            "total_instances": 1,
            "instances_done": 0,
            "errors": [],
            "started_at": _time_offset(),
            "demo": True,
        }),
        (55, "sync.progress", {
            "syncing": True,
            "current_instance": "Demo Sonarr",
            "stage": "Updating library",
            "items_synced": 37,
            "items_total": 47,
            "total_instances": 1,
            "instances_done": 0,
            "errors": [],
            "started_at": _time_offset(),
            "demo": True,
        }),
        (60, "sync.completed", {"total_items": 47, "demo": True}),
        (65, "stats.updated", {"demo": True}),
        (70, "indexer_health.updated", {"demo": True}),
    ]

    prev_offset = 0.0
    for offset_s, event_type, data in events:
        await asyncio.sleep(offset_s - prev_offset)
        prev_offset = offset_s
        await event_bus.emit(event_type, data)
        logger.debug("demo_event_emitted", event_type=event_type)


async def _simulation_loop(session_factory: sessionmaker[Session]) -> None:
    """Repeating loop: run a simulation cycle every ~2 minutes.

    Checks ``is_demo_active`` at the start of each cycle and exits
    cleanly when the user has both an instance and a queue.
    """
    logger.info("demo_simulation_loop_started")

    try:
        # Brief initial delay so the app finishes starting up
        await asyncio.sleep(5)

        while True:
            # Check whether demo mode is still active
            try:
                db = session_factory()
                try:
                    from splintarr.models.user import User

                    user = db.query(User).first()
                    if user is None:
                        logger.info("demo_simulation_waiting_for_user")
                        await asyncio.sleep(10)
                        continue
                    if not is_demo_active(db, user.id):
                        logger.info("demo_simulation_auto_disabled")
                        return
                finally:
                    db.close()
            except Exception as e:
                logger.warning("demo_simulation_check_failed", error=str(e))
                await asyncio.sleep(30)
                continue

            logger.info("demo_simulation_cycle_starting")
            try:
                await _run_simulation_cycle()
            except Exception as e:
                logger.warning("demo_simulation_cycle_failed", error=str(e))

            # Wait before the next cycle (~50 s gap after a ~70 s cycle ≈ 2 min)
            await asyncio.sleep(50)
    except asyncio.CancelledError:
        logger.info("demo_simulation_cancelled")
        raise


# ---------------------------------------------------------------------------
# Lifecycle management
# ---------------------------------------------------------------------------

def start_simulation(session_factory: sessionmaker[Session]) -> None:
    """Start the background simulation loop (non-blocking)."""
    global _simulation_task
    if _simulation_task is not None and not _simulation_task.done():
        logger.debug("demo_simulation_already_running")
        return

    _simulation_task = asyncio.create_task(_simulation_loop(session_factory))
    logger.info("demo_simulation_started")


async def stop_simulation() -> None:
    """Cancel the simulation loop and wait for clean exit."""
    global _simulation_task
    if _simulation_task is None or _simulation_task.done():
        return

    _simulation_task.cancel()
    try:
        await _simulation_task
    except asyncio.CancelledError:
        pass
    _simulation_task = None
    logger.info("demo_simulation_stopped")
