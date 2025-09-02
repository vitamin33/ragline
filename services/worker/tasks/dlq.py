"""
RAGline Dead Letter Queue Tasks

Celery tasks for DLQ management, reprocessing, alerting, and monitoring.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from celery import Task
from celery.utils.log import get_task_logger

from packages.orchestrator.dlq_manager import get_dlq_manager

from ..celery_app import app
from ..config import WorkerConfig

logger = get_task_logger(__name__)


class DLQTask(Task):
    """Base DLQ task with error handling"""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"DLQ task failed: {exc}", exc_info=einfo)

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"DLQ task completed: {retval}")


@app.task(bind=True, base=DLQTask, name="services.worker.tasks.dlq.batch_reprocess_dlq")
def batch_reprocess_dlq(self, aggregate_type: str = "order", limit: int = 10) -> Dict[str, Any]:
    """
    Batch reprocess events from DLQ with exponential backoff.

    Args:
        aggregate_type: Type of aggregate to reprocess (order, user, product, etc.)
        limit: Maximum number of events to reprocess
    """

    async def _batch_reprocess():
        try:
            dlq_manager = await get_dlq_manager()

            results = await dlq_manager.batch_reprocess(aggregate_type, limit)

            logger.info(
                f"DLQ batch reprocessing completed for {aggregate_type}: "
                f"{results['succeeded']} succeeded, {results['failed']} failed"
            )

            return {
                "status": "success",
                "aggregate_type": aggregate_type,
                "results": results,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"DLQ batch reprocessing failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "aggregate_type": aggregate_type,
                "timestamp": datetime.utcnow().isoformat(),
            }

    try:
        result = asyncio.run(_batch_reprocess())
        return result
    except Exception as e:
        logger.error(f"Failed to run DLQ batch reprocessing: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "aggregate_type": aggregate_type,
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.task(bind=True, base=DLQTask, name="services.worker.tasks.dlq.get_dlq_stats")
def get_dlq_stats(self) -> Dict[str, Any]:
    """Get comprehensive DLQ statistics"""

    async def _get_stats():
        try:
            dlq_manager = await get_dlq_manager()
            stats = await dlq_manager.get_dlq_stats()

            stats["timestamp"] = datetime.utcnow().isoformat()

            logger.debug(f"Retrieved DLQ stats: {stats['total_events']} total events")

            return {"status": "success", "stats": stats}

        except Exception as e:
            logger.error(f"Failed to get DLQ stats: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}

    try:
        result = asyncio.run(_get_stats())
        return result
    except Exception as e:
        logger.error(f"Failed to run DLQ stats retrieval: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@app.task(bind=True, base=DLQTask, name="services.worker.tasks.dlq.get_dlq_alerts")
def get_dlq_alerts(self) -> Dict[str, Any]:
    """Get current DLQ alerts"""

    async def _get_alerts():
        try:
            dlq_manager = await get_dlq_manager()
            alerts = await dlq_manager.get_alerts()

            logger.info(f"Retrieved {len(alerts)} DLQ alerts")

            return {
                "status": "success",
                "alerts": alerts,
                "alert_count": len(alerts),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get DLQ alerts: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}

    try:
        result = asyncio.run(_get_alerts())
        return result
    except Exception as e:
        logger.error(f"Failed to run DLQ alerts retrieval: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@app.task(bind=True, base=DLQTask, name="services.worker.tasks.dlq.get_manual_intervention_events")
def get_manual_intervention_events(self) -> Dict[str, Any]:
    """Get events requiring manual intervention"""

    async def _get_manual_events():
        try:
            dlq_manager = await get_dlq_manager()
            events = await dlq_manager.get_events_requiring_manual_intervention()

            # Convert events to serializable format
            event_data = []
            for event in events:
                event_data.append(
                    {
                        "event_id": event.event_id,
                        "aggregate_id": event.aggregate_id,
                        "aggregate_type": event.aggregate_type,
                        "event_type": event.event_type,
                        "failed_at": event.failed_at.isoformat(),
                        "retry_count": event.retry_count,
                        "failure_reason": event.failure_reason,
                        "status": event.status.value,
                    }
                )

            logger.info(f"Found {len(event_data)} events requiring manual intervention")

            return {
                "status": "success",
                "events": event_data,
                "event_count": len(event_data),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get manual intervention events: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}

    try:
        result = asyncio.run(_get_manual_events())
        return result
    except Exception as e:
        logger.error(f"Failed to run manual intervention events retrieval: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@app.task(bind=True, base=DLQTask, name="services.worker.tasks.dlq.mark_event_resolved")
def mark_event_resolved(self, event_id: str, aggregate_type: str) -> Dict[str, Any]:
    """
    Manually mark an event as resolved

    Args:
        event_id: ID of the event to resolve
        aggregate_type: Aggregate type (order, user, etc.)
    """

    async def _mark_resolved():
        try:
            dlq_manager = await get_dlq_manager()
            success = await dlq_manager.mark_event_resolved(event_id, aggregate_type)

            if success:
                logger.info(f"Manually resolved event {event_id} of type {aggregate_type}")
                return {
                    "status": "success",
                    "event_id": event_id,
                    "aggregate_type": aggregate_type,
                    "resolved": True,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            else:
                logger.warning(f"Event {event_id} not found for manual resolution")
                return {
                    "status": "success",
                    "event_id": event_id,
                    "aggregate_type": aggregate_type,
                    "resolved": False,
                    "message": "Event not found",
                    "timestamp": datetime.utcnow().isoformat(),
                }

        except Exception as e:
            logger.error(f"Failed to mark event {event_id} as resolved: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "event_id": event_id,
                "aggregate_type": aggregate_type,
                "timestamp": datetime.utcnow().isoformat(),
            }

    try:
        result = asyncio.run(_mark_resolved())
        return result
    except Exception as e:
        logger.error(f"Failed to run manual event resolution: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "event_id": event_id,
            "aggregate_type": aggregate_type,
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.task(bind=True, base=DLQTask, name="services.worker.tasks.dlq.cleanup_expired_events")
def cleanup_expired_events(self, days_to_keep: int = 30) -> Dict[str, Any]:
    """
    Clean up old expired and resolved events

    Args:
        days_to_keep: Number of days to keep expired/resolved events
    """

    async def _cleanup():
        try:
            dlq_manager = await get_dlq_manager()
            cleaned_count = await dlq_manager.cleanup_expired_events(days_to_keep)

            logger.info(f"Cleaned up {cleaned_count} old DLQ events (kept {days_to_keep} days)")

            return {
                "status": "success",
                "cleaned_count": cleaned_count,
                "days_to_keep": days_to_keep,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to cleanup expired events: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "days_to_keep": days_to_keep,
                "timestamp": datetime.utcnow().isoformat(),
            }

    try:
        result = asyncio.run(_cleanup())
        return result
    except Exception as e:
        logger.error(f"Failed to run DLQ cleanup: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "days_to_keep": days_to_keep,
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.task(bind=True, base=DLQTask, name="services.worker.tasks.dlq.periodic_dlq_monitoring")
def periodic_dlq_monitoring(self) -> Dict[str, Any]:
    """
    Periodic task for DLQ monitoring and automated maintenance.
    Should be scheduled to run every 5-10 minutes.
    """

    async def _monitor():
        try:
            dlq_manager = await get_dlq_manager()

            # Get stats and alerts
            stats = await dlq_manager.get_dlq_stats()
            alerts = await dlq_manager.get_alerts()

            # Log key metrics
            logger.info(f"DLQ Monitoring - Total events: {stats['total_events']}, " f"Active alerts: {len(alerts)}")

            # Perform automated reprocessing for events ready for retry
            reprocess_results = {}
            for aggregate_type in stats["by_aggregate_type"].keys():
                if stats["by_aggregate_type"][aggregate_type]["count"] > 0:
                    # Reprocess up to 5 events per type per monitoring cycle
                    results = await dlq_manager.batch_reprocess(aggregate_type, limit=5)
                    reprocess_results[aggregate_type] = results

            monitoring_result = {
                "status": "success",
                "stats_summary": {
                    "total_events": stats["total_events"],
                    "oldest_event_hours": stats["oldest_event_hours"],
                    "reprocessed_count": stats["reprocessed_count"],
                    "failed_reprocess_count": stats["failed_reprocess_count"],
                },
                "alerts": alerts,
                "automated_reprocessing": reprocess_results,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Log alerts if any
            if alerts:
                for alert in alerts:
                    logger.warning(f"DLQ Alert [{alert['type']}]: {alert['message']}")

            return monitoring_result

        except Exception as e:
            logger.error(f"DLQ monitoring failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}

    try:
        result = asyncio.run(_monitor())
        return result
    except Exception as e:
        logger.error(f"Failed to run DLQ monitoring: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@app.task(bind=True, base=DLQTask, name="services.worker.tasks.dlq.health_check_dlq")
def health_check_dlq(self) -> Dict[str, Any]:
    """Health check specifically for DLQ system"""

    async def _health_check():
        try:
            import redis.asyncio as redis

            config = WorkerConfig()
            health_data = {"timestamp": datetime.utcnow().isoformat(), "status": "healthy", "checks": {}}

            # Check DLQ manager initialization
            try:
                dlq_manager = await get_dlq_manager()
                stats = await dlq_manager.get_dlq_stats()

                health_data["checks"]["dlq_manager"] = {
                    "status": "healthy",
                    "total_events": stats["total_events"],
                    "reprocessed_count": stats["reprocessed_count"],
                    "failed_reprocess_count": stats["failed_reprocess_count"],
                }

            except Exception as e:
                health_data["checks"]["dlq_manager"] = {"status": "unhealthy", "error": str(e)}
                health_data["status"] = "degraded"

            # Check Redis connectivity for DLQ keys
            try:
                redis_client = redis.from_url(config.redis_url)
                await redis_client.ping()

                # Check DLQ key counts
                dlq_keys = await redis_client.keys("ragline:dlq:*")
                dlq_info = {}

                for key in dlq_keys:
                    key_str = key.decode("utf-8")
                    length = await redis_client.llen(key)
                    dlq_info[key_str] = length

                await redis_client.close()

                health_data["checks"]["redis_dlq"] = {"status": "healthy", "dlq_keys": dlq_info}

            except Exception as e:
                health_data["checks"]["redis_dlq"] = {"status": "unhealthy", "error": str(e)}
                health_data["status"] = "degraded"

            return health_data

        except Exception as e:
            return {"timestamp": datetime.utcnow().isoformat(), "status": "unhealthy", "error": str(e)}

    try:
        result = asyncio.run(_health_check())
        return result
    except Exception as e:
        logger.error(f"DLQ health check failed: {e}", exc_info=True)
        return {"timestamp": datetime.utcnow().isoformat(), "status": "unhealthy", "error": str(e)}
