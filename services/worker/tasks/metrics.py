"""
RAGline Metrics Collection Tasks

Celery tasks for collecting and exporting Prometheus metrics.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict

from celery import Task
from celery.utils.log import get_task_logger

from packages.orchestrator.circuit_breaker import get_registry_metrics
from packages.orchestrator.dlq_manager import get_dlq_manager
from packages.orchestrator.metrics import get_metrics, get_metrics_collector
from packages.orchestrator.outbox import get_outbox_consumer

from ..celery_app import app
from ..config import WorkerConfig

logger = get_task_logger(__name__)


class MetricsTask(Task):
    """Base metrics task with error handling"""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Metrics task failed: {exc}", exc_info=einfo)

    def on_success(self, retval, task_id, args, kwargs):
        logger.debug(f"Metrics task completed: {retval}")


@app.task(bind=True, base=MetricsTask, name="services.worker.tasks.metrics.collect_all_metrics")
def collect_all_metrics(self) -> Dict[str, Any]:
    """
    Collect metrics from all RAGline components.
    Should be scheduled to run every 30-60 seconds.
    """

    async def _collect():
        try:
            config = WorkerConfig()

            if not config.metrics_enabled:
                return {"status": "disabled", "message": "Metrics collection disabled"}

            collector = get_metrics_collector()
            metrics = get_metrics()

            collection_results = {
                "status": "success",
                "collections": {},
                "errors": [],
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Collect outbox metrics
            try:
                consumer = await get_outbox_consumer()
                outbox_stats = await consumer.get_metrics()

                await collector.collect_outbox_metrics(
                    {
                        "processed_count": outbox_stats.get("processed_count", 0),
                        "error_count": outbox_stats.get("error_count", 0),
                        "processing_duration_ms": outbox_stats.get("processing_duration_ms", 0),
                        "unprocessed_events": 0,  # Would need additional query
                    }
                )

                collection_results["collections"]["outbox"] = "success"

            except Exception as e:
                error_msg = f"Outbox metrics collection failed: {e}"
                logger.error(error_msg)
                collection_results["errors"].append(error_msg)
                metrics.record_error("metrics_task", "outbox_collection_error")

            # Collect DLQ metrics
            try:
                dlq_manager = await get_dlq_manager()
                dlq_stats = await dlq_manager.get_dlq_stats()
                dlq_alerts = await dlq_manager.get_alerts()

                await collector.collect_dlq_metrics(dlq_stats)

                # Update alert counts
                alert_counts = {}
                for alert in dlq_alerts:
                    alert_type = alert.get("type", "unknown")
                    alert_counts[alert_type] = alert_counts.get(alert_type, 0) + 1

                for alert_type, count in alert_counts.items():
                    metrics.update_dlq_alerts(alert_type, count)

                collection_results["collections"]["dlq"] = "success"

            except Exception as e:
                error_msg = f"DLQ metrics collection failed: {e}"
                logger.error(error_msg)
                collection_results["errors"].append(error_msg)
                metrics.record_error("metrics_task", "dlq_collection_error")

            # Collect circuit breaker metrics
            try:
                breaker_stats = await get_registry_metrics()

                breaker_list = []
                for name, breaker_data in breaker_stats.items():
                    breaker_list.append({"name": name, **breaker_data})

                await collector.collect_circuit_breaker_metrics(breaker_list)

                collection_results["collections"]["circuit_breakers"] = "success"

            except Exception as e:
                error_msg = f"Circuit breaker metrics collection failed: {e}"
                logger.error(error_msg)
                collection_results["errors"].append(error_msg)
                metrics.record_error("metrics_task", "circuit_breaker_collection_error")

            # Update events per second calculations
            try:
                # Calculate events/sec from outbox processing
                if "outbox" in collection_results["collections"]:
                    consumer = await get_outbox_consumer()
                    consumer_stats = await consumer.get_metrics()

                    # Simple rate calculation (would be more sophisticated in production)
                    processing_duration_ms = consumer_stats.get("processing_duration_ms", 0)
                    if processing_duration_ms > 0:
                        events_per_sec = 1000 / processing_duration_ms  # Rough estimate
                        metrics.update_events_per_second("outbox", events_per_sec)

                collection_results["collections"]["business_metrics"] = "success"

            except Exception as e:
                error_msg = f"Business metrics calculation failed: {e}"
                logger.error(error_msg)
                collection_results["errors"].append(error_msg)

            logger.info(
                f"Metrics collection completed: {len(collection_results['collections'])} successful, {len(collection_results['errors'])} errors"
            )

            return collection_results

        except Exception as e:
            logger.error(f"Metrics collection task failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}

    try:
        result = asyncio.run(_collect())
        return result
    except Exception as e:
        logger.error(f"Failed to run metrics collection: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@app.task(bind=True, base=MetricsTask, name="services.worker.tasks.metrics.export_metrics")
def export_metrics(self) -> Dict[str, Any]:
    """
    Export current metrics in Prometheus format.
    Returns metrics as string for debugging/inspection.
    """

    try:
        config = WorkerConfig()

        if not config.metrics_enabled:
            return {"status": "disabled", "message": "Metrics export disabled"}

        metrics = get_metrics()
        metrics_data = metrics.export_metrics()

        # Parse metrics for summary
        metrics_text = metrics_data.decode("utf-8")
        lines = metrics_text.split("\n")

        summary = {
            "status": "success",
            "metrics_summary": {
                "total_lines": len(lines),
                "help_lines": len([line for line in lines if line.startswith("# HELP")]),
                "type_lines": len([line for line in lines if line.startswith("# TYPE")]),
                "value_lines": len([line for line in lines if line and not line.startswith("#")]),
            },
            "sample_metrics": lines[:10],  # First 10 lines as sample
            "timestamp": datetime.utcnow().isoformat(),
        }

        logger.info(f"Exported {summary['metrics_summary']['value_lines']} metric values")
        return summary

    except Exception as e:
        logger.error(f"Failed to export metrics: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@app.task(bind=True, base=MetricsTask, name="services.worker.tasks.metrics.get_metrics_summary")
def get_metrics_summary(self) -> Dict[str, Any]:
    """
    Get summary of metrics system status and health.
    """

    try:
        config = WorkerConfig()
        metrics = get_metrics()

        summary = metrics.get_metrics_summary()

        # Add additional status information
        summary.update(
            {
                "config": {"enabled": config.metrics_enabled, "port": config.metrics_port, "collection_interval": 30},
                "components": {
                    "outbox_consumer": "available",
                    "dlq_manager": "available",
                    "circuit_breakers": "available",
                    "prometheus_client": "available",
                },
            }
        )

        return summary

    except Exception as e:
        logger.error(f"Failed to get metrics summary: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@app.task(bind=True, base=MetricsTask, name="services.worker.tasks.metrics.health_check_metrics")
def health_check_metrics(self) -> Dict[str, Any]:
    """
    Health check for metrics system.
    """

    try:
        config = WorkerConfig()

        health_data = {"timestamp": datetime.utcnow().isoformat(), "status": "healthy", "checks": {}}

        # Check if metrics are enabled
        if not config.metrics_enabled:
            health_data["status"] = "disabled"
            health_data["checks"]["enabled"] = {"status": "disabled"}
            return health_data

        # Check metrics initialization
        try:
            metrics = get_metrics()
            summary = metrics.get_metrics_summary()

            health_data["checks"]["metrics_instance"] = {
                "status": "healthy",
                "registry_size": summary.get("registry_size", 0),
                "port": summary.get("port", config.metrics_port),
            }

        except Exception as e:
            health_data["checks"]["metrics_instance"] = {"status": "unhealthy", "error": str(e)}
            health_data["status"] = "degraded"

        # Check collector initialization
        try:
            collector = get_metrics_collector()

            health_data["checks"]["metrics_collector"] = {
                "status": "healthy",
                "last_collection": collector.last_collection_time,
            }

        except Exception as e:
            health_data["checks"]["metrics_collector"] = {"status": "unhealthy", "error": str(e)}
            health_data["status"] = "degraded"

        return health_data

    except Exception as e:
        logger.error(f"Metrics health check failed: {e}", exc_info=True)
        return {"timestamp": datetime.utcnow().isoformat(), "status": "unhealthy", "error": str(e)}
