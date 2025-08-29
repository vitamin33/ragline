"""
RAGline Worker Configuration

Configuration management for Celery workers, pools, and reliability settings.
Supports both IO-bound and CPU-bound task execution pools.
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PoolType(str, Enum):
    """Celery worker pool types"""

    PREFORK = "prefork"  # CPU-bound tasks (multiprocessing)
    GEVENT = "gevent"  # IO-bound tasks (async)
    EVENTLET = "eventlet"  # IO-bound tasks (async alternative)
    SOLO = "solo"  # Single-threaded (development/debugging)
    THREADS = "threads"  # Thread-based pool


@dataclass
class WorkerConfig:
    """Worker configuration with reliability and performance settings"""

    # Redis configuration
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_password: Optional[str] = os.getenv("REDIS_PASSWORD")

    @property
    def redis_url(self) -> str:
        """Build Redis connection URL"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # Pool configuration
    worker_pool: PoolType = PoolType(os.getenv("WORKER_POOL", "gevent"))
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "100"))
    worker_prefetch_multiplier: int = int(os.getenv("WORKER_PREFETCH", "4"))

    # Reliability settings
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    task_always_eager: bool = os.getenv("TASK_ALWAYS_EAGER", "false").lower() == "true"

    # Outbox polling configuration
    outbox_poll_interval: float = float(os.getenv("OUTBOX_POLL_INTERVAL", "0.1"))  # 100ms
    outbox_batch_size: int = int(os.getenv("OUTBOX_BATCH_SIZE", "50"))

    # Circuit breaker settings
    circuit_breaker_failure_threshold: int = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
    circuit_breaker_recovery_timeout: int = int(os.getenv("CB_RECOVERY_TIMEOUT", "60"))
    circuit_breaker_expected_exception: str = os.getenv("CB_EXPECTED_EXCEPTION", "Exception")

    # Stream processing
    stream_block_time: int = int(os.getenv("STREAM_BLOCK_TIME", "100"))  # milliseconds
    stream_batch_size: int = int(os.getenv("STREAM_BATCH_SIZE", "10"))

    # Monitoring and metrics
    metrics_enabled: bool = os.getenv("METRICS_ENABLED", "true").lower() == "true"
    metrics_port: int = int(os.getenv("METRICS_PORT", "8080"))

    # Dead Letter Queue
    dlq_enabled: bool = os.getenv("DLQ_ENABLED", "true").lower() == "true"
    dlq_max_retries: int = int(os.getenv("DLQ_MAX_RETRIES", "3"))

    def get_pool_specific_settings(self) -> dict:
        """Get pool-specific configuration settings"""
        base_settings = {
            "worker_pool": self.worker_pool.value,
            "worker_concurrency": self.worker_concurrency,
            "worker_prefetch_multiplier": self.worker_prefetch_multiplier,
        }

        if self.worker_pool == PoolType.GEVENT:
            # IO-bound tasks with gevent
            return {
                **base_settings,
                "worker_pool_restarts": True,
                "worker_max_tasks_per_child": 1000,
                "worker_max_memory_per_child": 200000,  # 200MB in KB
                "task_soft_time_limit": 300,  # 5 minutes
                "task_time_limit": 600,  # 10 minutes
            }

        elif self.worker_pool == PoolType.PREFORK:
            # CPU-bound tasks with multiprocessing
            return {
                **base_settings,
                "worker_pool_restarts": True,
                "worker_max_tasks_per_child": 100,  # Lower for CPU tasks
                "worker_max_memory_per_child": 500000,  # 500MB in KB
                "task_soft_time_limit": 600,  # 10 minutes
                "task_time_limit": 1200,  # 20 minutes
            }

        elif self.worker_pool == PoolType.THREADS:
            # Thread-based pool
            return {
                **base_settings,
                "worker_pool_restarts": True,
                "worker_max_tasks_per_child": 500,
                "worker_max_memory_per_child": 300000,  # 300MB in KB
                "task_soft_time_limit": 300,  # 5 minutes
                "task_time_limit": 600,  # 10 minutes
            }

        else:  # SOLO or EVENTLET
            return base_settings


# Pool configuration presets
POOL_CONFIGS = {
    "io_intensive": WorkerConfig(
        worker_pool=PoolType.GEVENT,
        worker_concurrency=200,
        worker_prefetch_multiplier=1,
    ),
    "cpu_intensive": WorkerConfig(
        worker_pool=PoolType.PREFORK,
        worker_concurrency=4,  # Usually CPU cores
        worker_prefetch_multiplier=1,
    ),
    "mixed_workload": WorkerConfig(
        worker_pool=PoolType.GEVENT,
        worker_concurrency=100,
        worker_prefetch_multiplier=4,
    ),
    "development": WorkerConfig(
        worker_pool=PoolType.SOLO,
        worker_concurrency=1,
        worker_prefetch_multiplier=1,
        task_always_eager=True,
    ),
}


def get_config(profile: str = "mixed_workload") -> WorkerConfig:
    """Get worker configuration by profile"""
    return POOL_CONFIGS.get(profile, POOL_CONFIGS["mixed_workload"])


def get_optimal_concurrency(pool_type: PoolType) -> int:
    """Get optimal concurrency based on pool type and system"""
    import multiprocessing

    cpu_count = multiprocessing.cpu_count()

    if pool_type == PoolType.PREFORK:
        # CPU-bound: use CPU cores
        return cpu_count
    elif pool_type in [PoolType.GEVENT, PoolType.EVENTLET]:
        # IO-bound: can handle many more concurrent tasks
        return min(cpu_count * 25, 200)
    elif pool_type == PoolType.THREADS:
        # Thread-based: moderate concurrency
        return cpu_count * 4
    else:  # SOLO
        return 1


# Environment-specific configurations
def get_environment_config() -> WorkerConfig:
    """Get configuration based on environment"""
    env = os.getenv("ENVIRONMENT", "development").lower()

    if env == "production":
        return WorkerConfig(
            worker_pool=PoolType.GEVENT,
            worker_concurrency=get_optimal_concurrency(PoolType.GEVENT),
            worker_prefetch_multiplier=1,
            task_always_eager=False,
            outbox_poll_interval=0.1,  # 100ms
            metrics_enabled=True,
        )

    elif env == "staging":
        return WorkerConfig(
            worker_pool=PoolType.GEVENT,
            worker_concurrency=50,
            worker_prefetch_multiplier=2,
            task_always_eager=False,
            outbox_poll_interval=0.1,
            metrics_enabled=True,
        )

    else:  # development
        return WorkerConfig(
            worker_pool=PoolType.SOLO,
            worker_concurrency=1,
            worker_prefetch_multiplier=1,
            task_always_eager=True,
            outbox_poll_interval=1.0,  # 1 second for easier debugging
            metrics_enabled=False,
        )
