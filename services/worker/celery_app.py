"""
RAGline Worker - Celery Application Configuration

Celery app configuration for event processing, outbox consumption,
and background task execution with reliability patterns.
"""

import os

from celery import Celery
from kombu import Exchange, Queue

from .config import WorkerConfig

config = WorkerConfig()

app = Celery(
    "ragline_worker",
    broker=config.redis_url,
    backend=config.redis_url,
    include=[
        "services.worker.tasks.outbox",
        "services.worker.tasks.notifications",
        "services.worker.tasks.processing",
        "services.worker.tasks.health",
        "services.worker.tasks.tool_tracking",
        "services.worker.tasks.tool_cache",
    ],
)

# Celery Configuration
app.conf.update(
    # Task routing
    task_routes={
        "services.worker.tasks.outbox.*": {"queue": "outbox"},
        "services.worker.tasks.notifications.*": {"queue": "notifications"},
        "services.worker.tasks.processing.*": {"queue": "processing"},
        "services.worker.tasks.health.*": {"queue": "health"},
        "services.worker.tasks.tool_tracking.*": {"queue": "tool_tracking"},
        "services.worker.tasks.tool_cache.*": {"queue": "tool_cache"},
    },
    # Queue configuration
    task_queues=(
        Queue("outbox", Exchange("outbox"), routing_key="outbox"),
        Queue("notifications", Exchange("notifications"), routing_key="notifications"),
        Queue("processing", Exchange("processing"), routing_key="processing"),
        Queue("health", Exchange("health"), routing_key="health"),
        Queue("tool_tracking", Exchange("tool_tracking"), routing_key="tool_tracking"),
        Queue("tool_cache", Exchange("tool_cache"), routing_key="tool_cache"),
    ),
    task_default_queue="processing",
    task_default_exchange="processing",
    task_default_routing_key="processing",
    # Worker configuration
    worker_prefetch_multiplier=config.worker_prefetch_multiplier,
    task_acks_late=True,
    worker_disable_rate_limits=False,
    # Reliability settings
    task_reject_on_worker_lost=True,
    task_always_eager=config.task_always_eager,
    task_eager_propagates=True,
    # Retry configuration
    task_retry_delay=1.0,
    task_max_retries=config.max_retries,
    task_retry_jitter=True,
    task_retry_backoff=True,
    task_retry_backoff_max=300,
    # Result backend configuration
    result_backend=config.redis_url,
    result_expires=3600,  # 1 hour
    result_persistent=True,
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
    # Pool configuration
    worker_pool=config.worker_pool,
    worker_concurrency=config.worker_concurrency,
    # Beat configuration (for periodic tasks)
    beat_schedule={
        "outbox-consumer": {
            "task": "services.worker.tasks.outbox.consume_outbox",
            "schedule": config.outbox_poll_interval,
            "options": {"queue": "outbox"},
        },
        "health-check": {
            "task": "services.worker.tasks.health.health_check",
            "schedule": 300.0,  # 5 minutes
            "options": {"queue": "health"},
        },
        "tool-analytics-cleanup": {
            "task": "services.worker.tasks.tool_tracking.cleanup_old_tool_stats",
            "schedule": 3600.0,  # 1 hour
            "options": {"queue": "tool_tracking"},
        },
        "tool-cache-cleanup": {
            "task": "services.worker.tasks.tool_cache.cleanup_expired_cache",
            "schedule": 1800.0,  # 30 minutes
            "options": {"queue": "tool_cache"},
        },
    },
)

# Redis Streams configuration for event processing
app.conf.ragline_redis_streams = {
    "orders": {
        "stream_name": "ragline:stream:orders",
        "consumer_group": "ragline_workers",
        "consumer_name": f"worker_{os.getpid()}",
        "max_len": 10000,
        "block_time": 100,  # 100ms blocking read
    },
    "notifications": {
        "stream_name": "ragline:stream:notifications",
        "consumer_group": "ragline_notifiers",
        "consumer_name": f"notifier_{os.getpid()}",
        "max_len": 5000,
        "block_time": 100,
    },
    "tool_executions": {
        "stream_name": "ragline:stream:tool_executions",
        "consumer_group": "ragline_tool_trackers",
        "consumer_name": f"tool_tracker_{os.getpid()}",
        "max_len": 10000,
        "block_time": 100,
    },
}

# Prometheus metrics configuration
app.conf.ragline_metrics = {
    "enabled": config.metrics_enabled,
    "port": config.metrics_port,
    "prefix": "ragline_worker_",
}

if __name__ == "__main__":
    app.start()
