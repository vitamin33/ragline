"""
RAGline Worker Health Check Tasks

Health monitoring and diagnostics for the worker service.
Provides system status, connectivity checks, and performance metrics.
"""

import time
from datetime import datetime
from typing import Any, Dict

import psutil
import redis
from celery import Task
from celery.utils.log import get_task_logger

from ..celery_app import app
from ..config import WorkerConfig

logger = get_task_logger(__name__)
config = WorkerConfig()


class HealthCheckTask(Task):
    """Base health check task with error handling"""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Health check failed: {exc}", exc_info=einfo)

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"Health check completed successfully: {retval}")


@app.task(
    bind=True, base=HealthCheckTask, name="services.worker.tasks.health.health_check"
)
def health_check(self) -> Dict[str, Any]:
    """
    Comprehensive health check for the worker service.

    Returns:
        Dict containing health status and metrics
    """
    start_time = time.time()

    try:
        health_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "healthy",
            "checks": {},
            "metrics": {},
            "errors": [],
        }

        # System resources check
        try:
            health_data["checks"]["system"] = _check_system_resources()
        except Exception as e:
            health_data["errors"].append(f"System check failed: {str(e)}")
            health_data["checks"]["system"] = {"status": "unhealthy"}

        # Redis connectivity check
        try:
            health_data["checks"]["redis"] = _check_redis_connectivity()
        except Exception as e:
            health_data["errors"].append(f"Redis check failed: {str(e)}")
            health_data["checks"]["redis"] = {"status": "unhealthy"}

        # Worker queue status
        try:
            health_data["checks"]["queues"] = _check_queue_status()
        except Exception as e:
            health_data["errors"].append(f"Queue check failed: {str(e)}")
            health_data["checks"]["queues"] = {"status": "unhealthy"}

        # Performance metrics
        health_data["metrics"] = {
            "check_duration_ms": round((time.time() - start_time) * 1000, 2),
            "worker_pid": self.request.id if hasattr(self.request, "id") else None,
            "task_retries": self.request.retries
            if hasattr(self.request, "retries")
            else 0,
        }

        # Determine overall health status
        failed_checks = [
            name
            for name, check in health_data["checks"].items()
            if check.get("status") != "healthy"
        ]

        if failed_checks:
            health_data["status"] = (
                "degraded"
                if len(failed_checks) < len(health_data["checks"])
                else "unhealthy"
            )
            logger.warning(f"Health check found issues in: {', '.join(failed_checks)}")
        else:
            logger.info("Health check passed all checks")

        return health_data

    except Exception as e:
        logger.error(f"Health check failed completely: {str(e)}", exc_info=True)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "unhealthy",
            "error": str(e),
            "metrics": {
                "check_duration_ms": round((time.time() - start_time) * 1000, 2)
            },
        }


def _check_system_resources() -> Dict[str, Any]:
    """Check system resource usage"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Define thresholds
    cpu_warning_threshold = 80
    memory_warning_threshold = 85
    disk_warning_threshold = 90

    status = "healthy"
    warnings = []

    if cpu_percent > cpu_warning_threshold:
        warnings.append(f"High CPU usage: {cpu_percent}%")
        status = "degraded"

    if memory.percent > memory_warning_threshold:
        warnings.append(f"High memory usage: {memory.percent}%")
        status = "degraded"

    if disk.percent > disk_warning_threshold:
        warnings.append(f"High disk usage: {disk.percent}%")
        status = "degraded"

    return {
        "status": status,
        "cpu_percent": cpu_percent,
        "memory_percent": memory.percent,
        "memory_available_gb": round(memory.available / (1024**3), 2),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "warnings": warnings,
    }


def _check_redis_connectivity() -> Dict[str, Any]:
    """Check Redis connection and basic operations"""
    try:
        # Create Redis connection
        redis_client = redis.from_url(config.redis_url)

        # Test basic operations
        test_key = "ragline:health:test"
        test_value = f"health_check_{int(time.time())}"

        # Set and get test
        redis_client.set(test_key, test_value, ex=60)  # Expire in 60 seconds
        retrieved_value = redis_client.get(test_key)

        # Clean up
        redis_client.delete(test_key)

        if retrieved_value.decode() != test_value:
            raise ValueError("Redis set/get test failed")

        # Get Redis info
        redis_info = redis_client.info()

        return {
            "status": "healthy",
            "connected": True,
            "redis_version": redis_info.get("redis_version"),
            "used_memory_mb": round(redis_info.get("used_memory", 0) / (1024**2), 2),
            "connected_clients": redis_info.get("connected_clients"),
            "total_commands_processed": redis_info.get("total_commands_processed"),
        }

    except redis.ConnectionError as e:
        return {
            "status": "unhealthy",
            "connected": False,
            "error": f"Connection failed: {str(e)}",
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "connected": False,
            "error": f"Redis check failed: {str(e)}",
        }


def _check_queue_status() -> Dict[str, Any]:
    """Check Celery queue status"""
    try:
        # Get queue lengths (requires redis connection)
        redis_client = redis.from_url(config.redis_url)

        queues = ["outbox", "notifications", "processing", "health"]
        queue_status = {}

        for queue in queues:
            queue_key = f"celery:{queue}"
            length = redis_client.llen(queue_key)
            queue_status[queue] = {
                "length": length,
                "status": "healthy" if length < 1000 else "degraded",
            }

        overall_status = "healthy"
        if any(q["status"] != "healthy" for q in queue_status.values()):
            overall_status = "degraded"

        return {
            "status": overall_status,
            "queues": queue_status,
            "total_pending": sum(q["length"] for q in queue_status.values()),
        }

    except Exception as e:
        return {"status": "unhealthy", "error": f"Queue status check failed: {str(e)}"}


@app.task(bind=True, name="services.worker.tasks.health.ping")
def ping(self) -> Dict[str, Any]:
    """Simple ping task for basic connectivity testing"""
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "status": "pong",
        "worker_id": self.request.id if hasattr(self.request, "id") else None,
        "hostname": self.request.hostname
        if hasattr(self.request, "hostname")
        else None,
    }


@app.task(bind=True, name="services.worker.tasks.health.stress_test")
def stress_test(self, duration: int = 10, task_type: str = "cpu") -> Dict[str, Any]:
    """
    Stress test task for performance validation.

    Args:
        duration: Test duration in seconds
        task_type: Type of stress test ('cpu', 'memory', 'io')
    """
    start_time = time.time()

    if task_type == "cpu":
        # CPU stress test
        end_time = start_time + duration
        iterations = 0
        while time.time() < end_time:
            # Simple CPU-intensive calculation
            _ = sum(i * i for i in range(1000))
            iterations += 1

        return {
            "task_type": "cpu",
            "duration": duration,
            "iterations": iterations,
            "iterations_per_second": round(iterations / duration, 2),
        }

    elif task_type == "memory":
        # Memory allocation test
        data_blocks = []
        block_size = 1024 * 1024  # 1MB blocks

        end_time = start_time + duration
        while time.time() < end_time:
            data_blocks.append(b"x" * block_size)
            if len(data_blocks) > 100:  # Limit to prevent OOM
                data_blocks.pop(0)

        return {
            "task_type": "memory",
            "duration": duration,
            "peak_blocks": len(data_blocks),
            "peak_memory_mb": len(data_blocks) * (block_size / (1024**2)),
        }

    else:
        return {
            "error": f"Unknown task_type: {task_type}",
            "supported_types": ["cpu", "memory"],
        }
