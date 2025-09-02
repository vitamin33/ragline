"""
RAGline Prometheus Metrics

Comprehensive Prometheus metrics for worker services, outbox processing,
DLQ management, circuit breakers, and custom business metrics.
"""

import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from celery.utils.log import get_task_logger
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    start_http_server,
)

from services.worker.config import WorkerConfig

logger = get_task_logger(__name__)


class MetricType(str, Enum):
    """Metric type enumeration"""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    INFO = "info"


class RAGlineMetrics:
    """
    Comprehensive Prometheus metrics for RAGline worker services.

    Provides metrics for:
    - Worker execution (task times, queue lengths, error rates)
    - Outbox processing (events/sec, lag, errors)
    - DLQ management (queue sizes, retry rates, manual interventions)
    - Circuit breakers (state, failure rates, response times)
    - Custom business metrics (orders processed, user activity, etc.)
    """

    def __init__(self, config: WorkerConfig, registry: Optional[CollectorRegistry] = None):
        self.config = config
        self.registry = registry or CollectorRegistry()

        # Initialize all metrics
        self._init_worker_metrics()
        self._init_outbox_metrics()
        self._init_dlq_metrics()
        self._init_circuit_breaker_metrics()
        self._init_business_metrics()
        self._init_system_info()

        logger.info("RAGline Prometheus metrics initialized")

    def _init_worker_metrics(self):
        """Initialize worker-specific metrics"""
        # Task execution metrics
        self.task_duration = Histogram(
            "ragline_task_duration_seconds",
            "Time spent executing Celery tasks",
            ["task_name", "status"],
            registry=self.registry,
            buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf")],
        )

        self.task_counter = Counter(
            "ragline_tasks_total",
            "Total number of Celery tasks executed",
            ["task_name", "status"],
            registry=self.registry,
        )

        # Queue metrics
        self.queue_length = Gauge(
            "ragline_queue_length", "Current length of Celery queues", ["queue_name"], registry=self.registry
        )

        self.worker_active_tasks = Gauge(
            "ragline_worker_active_tasks", "Number of currently executing tasks", ["worker_id"], registry=self.registry
        )

        # Error tracking
        self.error_rate = Counter(
            "ragline_errors_total",
            "Total number of errors by component",
            ["component", "error_type"],
            registry=self.registry,
        )

    def _init_outbox_metrics(self):
        """Initialize outbox processing metrics"""
        # Outbox processing
        self.outbox_events_processed = Counter(
            "ragline_outbox_events_processed_total",
            "Total outbox events processed successfully",
            ["aggregate_type"],
            registry=self.registry,
        )

        self.outbox_processing_duration = Histogram(
            "ragline_outbox_processing_duration_seconds",
            "Time to process outbox events",
            ["aggregate_type"],
            registry=self.registry,
        )

        self.outbox_lag = Gauge(
            "ragline_outbox_lag_seconds", "Lag between event creation and processing", registry=self.registry
        )

        self.outbox_unprocessed_events = Gauge(
            "ragline_outbox_unprocessed_events", "Number of unprocessed events in outbox", registry=self.registry
        )

        # Stream processing
        self.stream_events_published = Counter(
            "ragline_stream_events_published_total",
            "Total events published to Redis streams",
            ["stream_name", "status"],
            registry=self.registry,
        )

        self.stream_consumer_lag = Gauge(
            "ragline_stream_consumer_lag_seconds",
            "Consumer lag for Redis streams",
            ["stream_name", "consumer_group"],
            registry=self.registry,
        )

    def _init_dlq_metrics(self):
        """Initialize Dead Letter Queue metrics"""
        self.dlq_events_total = Gauge(
            "ragline_dlq_events_total",
            "Total events in Dead Letter Queue",
            ["aggregate_type", "status"],
            registry=self.registry,
        )

        self.dlq_reprocess_attempts = Counter(
            "ragline_dlq_reprocess_attempts_total",
            "Total DLQ reprocessing attempts",
            ["aggregate_type", "result"],
            registry=self.registry,
        )

        self.dlq_manual_interventions = Counter(
            "ragline_dlq_manual_interventions_total",
            "Total manual interventions in DLQ",
            ["aggregate_type", "action"],
            registry=self.registry,
        )

        self.dlq_oldest_event_age = Gauge(
            "ragline_dlq_oldest_event_age_hours",
            "Age of oldest event in DLQ (hours)",
            ["aggregate_type"],
            registry=self.registry,
        )

        self.dlq_alerts_active = Gauge(
            "ragline_dlq_alerts_active", "Number of active DLQ alerts", ["alert_type"], registry=self.registry
        )

    def _init_circuit_breaker_metrics(self):
        """Initialize circuit breaker metrics"""
        self.circuit_breaker_state = Gauge(
            "ragline_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=open, 2=half_open)",
            ["breaker_name"],
            registry=self.registry,
        )

        self.circuit_breaker_failures = Counter(
            "ragline_circuit_breaker_failures_total",
            "Total circuit breaker failures",
            ["breaker_name"],
            registry=self.registry,
        )

        self.circuit_breaker_successes = Counter(
            "ragline_circuit_breaker_successes_total",
            "Total circuit breaker successes",
            ["breaker_name"],
            registry=self.registry,
        )

        self.circuit_breaker_response_time = Histogram(
            "ragline_circuit_breaker_response_duration_seconds",
            "Response time for circuit breaker protected calls",
            ["breaker_name", "result"],
            registry=self.registry,
        )

    def _init_business_metrics(self):
        """Initialize business-specific metrics"""
        # Events processed per second
        self.events_per_second = Gauge(
            "ragline_events_per_second", "Events processed per second", ["event_type"], registry=self.registry
        )

        # Order processing metrics
        self.orders_processed = Counter(
            "ragline_orders_processed_total", "Total orders processed", ["status", "tenant_id"], registry=self.registry
        )

        self.order_processing_duration = Histogram(
            "ragline_order_processing_duration_seconds",
            "End-to-end order processing time",
            ["tenant_id"],
            registry=self.registry,
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
        )

        # User activity metrics
        self.user_sessions = Gauge(
            "ragline_user_sessions_active", "Active user sessions", ["tenant_id"], registry=self.registry
        )

        # Cache metrics
        self.cache_hits = Counter(
            "ragline_cache_hits_total", "Total cache hits", ["cache_type"], registry=self.registry
        )

        self.cache_misses = Counter(
            "ragline_cache_misses_total", "Total cache misses", ["cache_type"], registry=self.registry
        )

    def _init_system_info(self):
        """Initialize system information metrics"""
        self.system_info = Info("ragline_system", "RAGline system information", registry=self.registry)

        # Set system info
        import os
        import platform

        self.system_info.info(
            {
                "version": "1.0.0",
                "service": "ragline_worker",
                "python_version": platform.python_version(),
                "platform": platform.system(),
                "environment": os.getenv("ENVIRONMENT", "development"),
                "worker_pool": self.config.worker_pool.value,
                "concurrency": str(self.config.worker_concurrency),
            }
        )

    # Worker metrics methods
    def record_task_execution(self, task_name: str, duration: float, status: str = "success"):
        """Record task execution metrics"""
        self.task_duration.labels(task_name=task_name, status=status).observe(duration)
        self.task_counter.labels(task_name=task_name, status=status).inc()

    def update_queue_length(self, queue_name: str, length: int):
        """Update queue length gauge"""
        self.queue_length.labels(queue_name=queue_name).set(length)

    def update_worker_active_tasks(self, worker_id: str, count: int):
        """Update active tasks for worker"""
        self.worker_active_tasks.labels(worker_id=worker_id).set(count)

    def record_error(self, component: str, error_type: str):
        """Record error occurrence"""
        self.error_rate.labels(component=component, error_type=error_type).inc()

    # Outbox metrics methods
    def record_outbox_event_processed(self, aggregate_type: str, duration: float):
        """Record outbox event processing"""
        self.outbox_events_processed.labels(aggregate_type=aggregate_type).inc()
        self.outbox_processing_duration.labels(aggregate_type=aggregate_type).observe(duration)

    def update_outbox_lag(self, lag_seconds: float):
        """Update outbox processing lag"""
        self.outbox_lag.set(lag_seconds)

    def update_outbox_unprocessed_count(self, count: int):
        """Update unprocessed events count"""
        self.outbox_unprocessed_events.set(count)

    def record_stream_event_published(self, stream_name: str, status: str = "success"):
        """Record stream event publication"""
        self.stream_events_published.labels(stream_name=stream_name, status=status).inc()

    def update_stream_consumer_lag(self, stream_name: str, consumer_group: str, lag_seconds: float):
        """Update stream consumer lag"""
        self.stream_consumer_lag.labels(stream_name=stream_name, consumer_group=consumer_group).set(lag_seconds)

    # DLQ metrics methods
    def update_dlq_events(self, aggregate_type: str, status: str, count: int):
        """Update DLQ event counts"""
        self.dlq_events_total.labels(aggregate_type=aggregate_type, status=status).set(count)

    def record_dlq_reprocess_attempt(self, aggregate_type: str, result: str):
        """Record DLQ reprocessing attempt"""
        self.dlq_reprocess_attempts.labels(aggregate_type=aggregate_type, result=result).inc()

    def record_dlq_manual_intervention(self, aggregate_type: str, action: str):
        """Record DLQ manual intervention"""
        self.dlq_manual_interventions.labels(aggregate_type=aggregate_type, action=action).inc()

    def update_dlq_oldest_event_age(self, aggregate_type: str, age_hours: float):
        """Update oldest event age in DLQ"""
        self.dlq_oldest_event_age.labels(aggregate_type=aggregate_type).set(age_hours)

    def update_dlq_alerts(self, alert_type: str, count: int):
        """Update active DLQ alerts count"""
        self.dlq_alerts_active.labels(alert_type=alert_type).set(count)

    # Circuit breaker metrics methods
    def update_circuit_breaker_state(self, breaker_name: str, state: str):
        """Update circuit breaker state (closed=0, open=1, half_open=2)"""
        state_value = {"closed": 0, "open": 1, "half_open": 2}.get(state, 0)
        self.circuit_breaker_state.labels(breaker_name=breaker_name).set(state_value)

    def record_circuit_breaker_call(self, breaker_name: str, result: str, duration: float):
        """Record circuit breaker call"""
        if result == "success":
            self.circuit_breaker_successes.labels(breaker_name=breaker_name).inc()
        else:
            self.circuit_breaker_failures.labels(breaker_name=breaker_name).inc()

        self.circuit_breaker_response_time.labels(breaker_name=breaker_name, result=result).observe(duration)

    # Business metrics methods
    def update_events_per_second(self, event_type: str, rate: float):
        """Update events per second rate"""
        self.events_per_second.labels(event_type=event_type).set(rate)

    def record_order_processed(self, status: str, tenant_id: str, duration: float):
        """Record order processing"""
        self.orders_processed.labels(status=status, tenant_id=tenant_id).inc()
        self.order_processing_duration.labels(tenant_id=tenant_id).observe(duration)

    def update_user_sessions(self, tenant_id: str, count: int):
        """Update active user sessions"""
        self.user_sessions.labels(tenant_id=tenant_id).set(count)

    def record_cache_hit(self, cache_type: str):
        """Record cache hit"""
        self.cache_hits.labels(cache_type=cache_type).inc()

    def record_cache_miss(self, cache_type: str):
        """Record cache miss"""
        self.cache_misses.labels(cache_type=cache_type).inc()

    # Utility methods
    def export_metrics(self) -> bytes:
        """Export metrics in Prometheus format"""
        return generate_latest(self.registry)

    def start_metrics_server(self, port: Optional[int] = None) -> int:
        """Start HTTP metrics server for Prometheus scraping"""
        metrics_port = port or self.config.metrics_port

        # Use custom registry
        start_http_server(metrics_port, registry=self.registry)

        logger.info(f"Prometheus metrics server started on port {metrics_port}")
        return metrics_port

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of current metrics for debugging"""
        try:
            metrics_text = self.export_metrics().decode("utf-8")

            # Count different metric types
            lines = metrics_text.split("\n")
            metric_counts = {
                "total_lines": len(lines),
                "help_lines": len([line for line in lines if line.startswith("# HELP")]),
                "type_lines": len([line for line in lines if line.startswith("# TYPE")]),
                "value_lines": len([line for line in lines if line and not line.startswith("#")]),
            }

            return {
                "status": "active",
                "registry_size": len(self.registry._collector_to_names),
                "metric_counts": metric_counts,
                "port": self.config.metrics_port,
                "enabled": self.config.metrics_enabled,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get metrics summary: {e}")
            return {"status": "error", "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


class MetricsCollector:
    """
    Automated metrics collector that gathers metrics from various sources
    and updates Prometheus metrics.
    """

    def __init__(self, metrics: RAGlineMetrics):
        self.metrics = metrics
        self.last_collection_time = time.time()

        # Tracking for rate calculations
        self.last_counts = {"outbox_processed": 0, "stream_published": 0, "tasks_executed": 0}

    async def collect_worker_metrics(self, worker_stats: Dict[str, Any]):
        """Collect and update worker metrics"""
        try:
            # Update active tasks
            for worker_id, active_count in worker_stats.get("active_tasks", {}).items():
                self.metrics.update_worker_active_tasks(worker_id, active_count)

            # Update queue lengths
            for queue_name, length in worker_stats.get("queue_lengths", {}).items():
                self.metrics.update_queue_length(queue_name, length)

        except Exception as e:
            logger.error(f"Failed to collect worker metrics: {e}")
            self.metrics.record_error("metrics_collector", "worker_metrics_error")

    async def collect_outbox_metrics(self, outbox_stats: Dict[str, Any]):
        """Collect and update outbox metrics"""
        try:
            # Update unprocessed count
            unprocessed = outbox_stats.get("unprocessed_events", 0)
            self.metrics.update_outbox_unprocessed_count(unprocessed)

            # Calculate processing rate
            current_processed = outbox_stats.get("processed_count", 0)
            current_time = time.time()
            time_delta = current_time - self.last_collection_time

            if time_delta > 0:
                processed_delta = current_processed - self.last_counts["outbox_processed"]
                events_per_second = processed_delta / time_delta
                self.metrics.update_events_per_second("outbox", events_per_second)

                self.last_counts["outbox_processed"] = current_processed

            # Update lag if available
            if "processing_lag_seconds" in outbox_stats:
                self.metrics.update_outbox_lag(outbox_stats["processing_lag_seconds"])

        except Exception as e:
            logger.error(f"Failed to collect outbox metrics: {e}")
            self.metrics.record_error("metrics_collector", "outbox_metrics_error")

    async def collect_dlq_metrics(self, dlq_stats: Dict[str, Any]):
        """Collect and update DLQ metrics"""
        try:
            # Update DLQ event counts by status
            status_counts = dlq_stats.get("status_counts", {})
            for status, count in status_counts.items():
                # Aggregate across all types for overall status
                self.metrics.dlq_events_total.labels(aggregate_type="all", status=status).set(count)

            # Update by aggregate type
            for agg_type, agg_stats in dlq_stats.get("by_aggregate_type", {}).items():
                for status, count in agg_stats.get("status_breakdown", {}).items():
                    self.metrics.update_dlq_events(agg_type, status, count)

            # Update oldest event age
            oldest_hours = dlq_stats.get("oldest_event_hours", 0)
            if oldest_hours > 0:
                self.metrics.dlq_oldest_event_age.labels(aggregate_type="all").set(oldest_hours)

        except Exception as e:
            logger.error(f"Failed to collect DLQ metrics: {e}")
            self.metrics.record_error("metrics_collector", "dlq_metrics_error")

    async def collect_circuit_breaker_metrics(self, breaker_stats: List[Dict[str, Any]]):
        """Collect and update circuit breaker metrics"""
        try:
            for breaker_data in breaker_stats:
                breaker_name = breaker_data.get("name", "unknown")

                # Update state
                state = breaker_data.get("state", "closed")
                self.metrics.update_circuit_breaker_state(breaker_name, state)

                # Update counters (these are cumulative, so we just set the current values)
                success_count = breaker_data.get("success_count", 0)
                failure_count = breaker_data.get("failure_count", 0)

                # Note: Counter._value is internal, better to track increments
                # For now, we'll log the current counts
                logger.debug(f"Circuit breaker {breaker_name}: " f"{success_count} successes, {failure_count} failures")

        except Exception as e:
            logger.error(f"Failed to collect circuit breaker metrics: {e}")
            self.metrics.record_error("metrics_collector", "circuit_breaker_metrics_error")

    async def collect_all_metrics(self):
        """Collect metrics from all sources"""
        try:
            # This would be called periodically to gather metrics from:
            # - Outbox consumer
            # - DLQ manager
            # - Circuit breakers
            # - Worker stats
            # - Business logic

            current_time = time.time()
            self.last_collection_time = current_time

            logger.debug("Metrics collection cycle completed")

        except Exception as e:
            logger.error(f"Failed to collect all metrics: {e}")
            self.metrics.record_error("metrics_collector", "collection_error")


# Global metrics instance
_metrics_instance: Optional[RAGlineMetrics] = None
_collector_instance: Optional[MetricsCollector] = None


def get_metrics() -> RAGlineMetrics:
    """Get or create global metrics instance"""
    global _metrics_instance

    if not _metrics_instance:
        config = WorkerConfig()
        _metrics_instance = RAGlineMetrics(config)

    return _metrics_instance


def get_metrics_collector() -> MetricsCollector:
    """Get or create global metrics collector"""
    global _collector_instance

    if not _collector_instance:
        metrics = get_metrics()
        _collector_instance = MetricsCollector(metrics)

    return _collector_instance


def start_metrics_server(port: Optional[int] = None) -> int:
    """Start metrics server for Prometheus scraping"""
    metrics = get_metrics()
    return metrics.start_metrics_server(port)


def export_metrics() -> bytes:
    """Export metrics in Prometheus format"""
    metrics = get_metrics()
    return metrics.export_metrics()
