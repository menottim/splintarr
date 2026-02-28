"""
Health Check Service for Splintarr.

This module implements automated instance health monitoring:
- Periodic connectivity checks against Sonarr/Radarr instances
- Automatic queue pause when an instance goes unhealthy
- Automatic queue resume when an instance recovers (with configurable threshold)
- Per-instance health status tracking with consecutive success/failure counters
"""

import structlog
from sqlalchemy.orm import Session

from splintarr.config import settings
from splintarr.core.security import decrypt_api_key
from splintarr.models.instance import Instance
from splintarr.models.search_queue import SearchQueue
from splintarr.services.radarr import RadarrClient
from splintarr.services.sonarr import SonarrClient

logger = structlog.get_logger()


class HealthCheckService:
    """
    Service for monitoring Sonarr/Radarr instance connectivity.

    Checks instance health via the /api/v3/system/status endpoint and
    automatically pauses or resumes search queues based on instance status.
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize HealthCheckService.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    async def check_instance(self, instance: Instance) -> dict:
        """
        Check a single instance's connectivity and manage queue state.

        Decrypts the API key, creates the appropriate client (Sonarr or Radarr),
        calls test_connection(), and updates health tracking fields. Pauses or
        resumes queues when the health status transitions.

        Args:
            instance: Instance model to check

        Returns:
            dict with keys: instance_id, instance_name, success, response_time_ms,
            error, status_changed, old_status, new_status, queues_paused,
            queues_resumed
        """
        old_status = instance.connection_status
        queues_paused = 0
        queues_resumed = 0
        status_changed = False

        logger.info(
            "instance_health_check_started",
            instance_id=instance.id,
            instance_name=instance.name,
            old_status=old_status,
        )

        try:
            api_key = decrypt_api_key(instance.api_key)

            if instance.instance_type == "sonarr":
                client_class = SonarrClient
            else:
                client_class = RadarrClient

            async with client_class(
                url=instance.url,
                api_key=api_key,
                verify_ssl=instance.verify_ssl,
                timeout=instance.timeout_seconds,
            ) as client:
                result = await client.test_connection()

        except Exception as e:
            # Client creation or connection entirely failed — treat as unhealthy
            logger.error(
                "instance_health_check_failed",
                instance_id=instance.id,
                instance_name=instance.name,
                error=str(e),
            )
            result = {
                "success": False,
                "error": str(e),
                "version": None,
                "response_time_ms": None,
            }

        success = result.get("success", False)
        error = result.get("error")
        response_time_ms = result.get("response_time_ms")

        if success:
            # Capture recovery state before mark_healthy mutates the counters.
            # An instance is "recovering" if it was unhealthy (old_status) OR
            # it is mid-recovery: consecutive_successes is between 1 and
            # (threshold - 1), meaning a prior check already flipped
            # last_connection_success to True but the recovery threshold
            # hasn't been met yet.  Stably-healthy instances have
            # consecutive_successes >= threshold and are NOT recovering.
            was_unhealthy = old_status == "unhealthy"
            prior_successes = instance.consecutive_successes or 0
            was_recovering = (
                not was_unhealthy and 0 < prior_successes < settings.health_check_recovery_threshold
            )

            instance.mark_healthy(response_time_ms=response_time_ms)

            if was_unhealthy or was_recovering:
                if instance.consecutive_successes >= settings.health_check_recovery_threshold:
                    status_changed = True
                    queues_resumed = self._resume_queues(instance)
                    logger.warning(
                        "instance_health_status_changed",
                        instance_id=instance.id,
                        instance_name=instance.name,
                        old_status=old_status,
                        new_status="healthy",
                        queues_resumed=queues_resumed,
                    )
                    logger.info(
                        "instance_health_recovered",
                        instance_id=instance.id,
                        instance_name=instance.name,
                        consecutive_successes=instance.consecutive_successes,
                    )
                else:
                    logger.debug(
                        "instance_health_recovering",
                        instance_id=instance.id,
                        instance_name=instance.name,
                        consecutive_successes=instance.consecutive_successes,
                        threshold=settings.health_check_recovery_threshold,
                    )

            logger.info(
                "instance_health_check_completed",
                instance_id=instance.id,
                instance_name=instance.name,
                success=True,
                response_time_ms=response_time_ms,
            )
        else:
            was_healthy = old_status in ("healthy", "untested")
            instance.mark_unhealthy(error or "Unknown error")

            if was_healthy:
                status_changed = True
                queues_paused = self._pause_queues(instance)
                logger.warning(
                    "instance_health_status_changed",
                    instance_id=instance.id,
                    instance_name=instance.name,
                    old_status=old_status,
                    new_status="unhealthy",
                    queues_paused=queues_paused,
                )
            else:
                logger.debug(
                    "instance_health_still_unhealthy",
                    instance_id=instance.id,
                    instance_name=instance.name,
                    consecutive_failures=instance.consecutive_failures,
                )

            logger.info(
                "instance_health_check_completed",
                instance_id=instance.id,
                instance_name=instance.name,
                success=False,
                error=error,
            )

        self.db.commit()

        new_status = instance.connection_status

        return {
            "instance_id": instance.id,
            "instance_name": instance.name,
            "success": success,
            "response_time_ms": response_time_ms,
            "error": error,
            "status_changed": status_changed,
            "old_status": old_status,
            "new_status": new_status,
            "queues_paused": queues_paused,
            "queues_resumed": queues_resumed,
        }

    async def check_all_instances(self) -> list[dict]:
        """
        Check connectivity for all active instances.

        Iterates all instances where is_active is True, calls check_instance()
        for each, and logs a summary.

        Returns:
            list of result dicts from check_instance()
        """
        instances = self.db.query(Instance).filter(Instance.is_active.is_(True)).all()

        if not instances:
            logger.info("instance_health_check_no_instances")
            return []

        results: list[dict] = []
        for instance in instances:
            result = await self.check_instance(instance)
            results.append(result)

        healthy_count = sum(1 for r in results if r["success"])
        unhealthy_count = len(results) - healthy_count

        logger.info(
            "instance_health_check_completed",
            total=len(results),
            healthy_count=healthy_count,
            unhealthy_count=unhealthy_count,
        )

        return results

    def _pause_queues(self, instance: Instance) -> int:
        """
        Pause all active queues for an unhealthy instance.

        Sets is_active to False and records the reason in error_message so
        _resume_queues can identify which queues were paused by health monitoring.

        Args:
            instance: Unhealthy Instance whose queues should be paused

        Returns:
            int: Number of queues paused
        """
        queues = (
            self.db.query(SearchQueue)
            .filter(
                SearchQueue.instance_id == instance.id,
                SearchQueue.is_active.is_(True),
            )
            .all()
        )

        for queue in queues:
            queue.is_active = False
            queue.error_message = f"Paused: instance '{instance.name}' unhealthy"
            logger.info(
                "search_queue_auto_paused",
                queue_id=queue.id,
                queue_name=queue.name,
                instance_id=instance.id,
                instance_name=instance.name,
            )

        return len(queues)

    def _resume_queues(self, instance: Instance) -> int:
        """
        Resume queues that were paused by health monitoring.

        Only resumes queues whose error_message matches the pattern set by
        _pause_queues, ensuring manually paused queues are not affected.

        Args:
            instance: Recovered Instance whose queues should be resumed

        Returns:
            int: Number of queues resumed
        """
        queues = (
            self.db.query(SearchQueue)
            .filter(
                SearchQueue.instance_id == instance.id,
                SearchQueue.is_active.is_(False),
                SearchQueue.error_message.like("%instance%unhealthy%"),
            )
            .all()
        )

        for queue in queues:
            queue.is_active = True
            queue.error_message = None
            queue.consecutive_failures = 0
            logger.info(
                "search_queue_auto_resumed",
                queue_id=queue.id,
                queue_name=queue.name,
                instance_id=instance.id,
                instance_name=instance.name,
            )

        return len(queues)
