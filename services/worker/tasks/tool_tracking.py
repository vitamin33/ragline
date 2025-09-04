"""
RAGline Tool Execution Event Tracking

Tracks LLM tool execution lifecycle, performance metrics, and usage analytics.
Provides event-driven monitoring for tool performance optimization and cost tracking.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from celery import Task
from celery.utils.log import get_task_logger

from packages.orchestrator.event_schemas import EventSerializer
from packages.orchestrator.redis_simple import get_simple_redis_client
from packages.orchestrator.stream_producer import StreamTopic, get_stream_producer

# Tool metrics integration
try:
    from packages.orchestrator.tool_metrics import record_tool_execution_from_event

    TOOL_METRICS_AVAILABLE = True
except ImportError:
    TOOL_METRICS_AVAILABLE = False
    logger.warning("Tool metrics not available")

# Tool cache integration
try:
    from packages.orchestrator.tool_cache import get_tool_cache_stats

    TOOL_CACHE_AVAILABLE = True
except ImportError:
    TOOL_CACHE_AVAILABLE = False
    logger.warning("Tool cache not available")

from ..celery_app import app
from ..config import WorkerConfig

logger = get_task_logger(__name__)


@dataclass
class ToolExecutionEvent:
    """Tool execution event data structure matching tool_execution_v1.json schema"""

    # Required fields
    event: str = "tool_execution"
    version: str = "1.0"
    tenant_id: str = ""
    tool_execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    status: str = ""  # started, completed, failed, cached, rate_limited
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Optional fields
    user_id: Optional[str] = None
    execution_data: Dict[str, Any] = field(default_factory=dict)
    tool_parameters: Dict[str, Any] = field(default_factory=dict)
    result_metadata: Dict[str, Any] = field(default_factory=dict)
    error_details: Optional[Dict[str, Any]] = None
    context: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for event streaming"""
        data = {
            "event": self.event,
            "version": self.version,
            "tenant_id": self.tenant_id,
            "tool_execution_id": self.tool_execution_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "ts": self.ts,
        }

        # Add optional fields if present
        if self.user_id:
            data["user_id"] = self.user_id
        if self.execution_data:
            data["execution_data"] = self.execution_data
        if self.tool_parameters:
            data["tool_parameters"] = self.tool_parameters
        if self.result_metadata:
            data["result_metadata"] = self.result_metadata
        if self.error_details:
            data["error_details"] = self.error_details
        if self.context:
            data["context"] = self.context
        if self.meta:
            data["meta"] = self.meta

        return data


@dataclass
class ToolUsageStats:
    """Tool usage statistics for analytics"""

    tool_name: str
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    cached_executions: int = 0
    rate_limited_executions: int = 0

    # Performance metrics
    total_duration_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Usage patterns
    unique_users: set = field(default_factory=set)
    unique_tenants: set = field(default_factory=set)
    hourly_usage: Dict[str, int] = field(default_factory=dict)

    # Window tracking
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_executions == 0:
            return 0.0
        return (self.successful_executions / self.total_executions) * 100

    @property
    def average_duration_ms(self) -> float:
        """Calculate average execution duration"""
        if self.successful_executions == 0:
            return 0.0
        return self.total_duration_ms / self.successful_executions

    @property
    def average_cost_usd(self) -> float:
        """Calculate average execution cost"""
        if self.total_executions == 0:
            return 0.0
        return self.total_cost_usd / self.total_executions

    def update_from_event(self, event: ToolExecutionEvent):
        """Update statistics from a tool execution event"""
        self.total_executions += 1
        self.last_updated = datetime.now(timezone.utc)

        # Update status counters
        if event.status == "completed":
            self.successful_executions += 1
        elif event.status == "failed":
            self.failed_executions += 1
        elif event.status == "cached":
            self.cached_executions += 1
        elif event.status == "rate_limited":
            self.rate_limited_executions += 1

        # Update performance metrics
        if event.execution_data:
            self.total_duration_ms += event.execution_data.get("duration_ms", 0)
            self.total_cost_usd += event.execution_data.get("cost_usd", 0)
            self.total_input_tokens += event.execution_data.get("input_tokens", 0)
            self.total_output_tokens += event.execution_data.get("output_tokens", 0)

        # Update usage patterns
        if event.user_id:
            self.unique_users.add(event.user_id)
        if event.tenant_id:
            self.unique_tenants.add(event.tenant_id)

        # Update hourly usage
        hour_key = datetime.fromisoformat(event.ts.replace("Z", "+00:00")).strftime("%Y-%m-%d-%H")
        self.hourly_usage[hour_key] = self.hourly_usage.get(hour_key, 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "tool_name": self.tool_name,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "cached_executions": self.cached_executions,
            "rate_limited_executions": self.rate_limited_executions,
            "success_rate": self.success_rate,
            "total_duration_ms": self.total_duration_ms,
            "average_duration_ms": self.average_duration_ms,
            "total_cost_usd": self.total_cost_usd,
            "average_cost_usd": self.average_cost_usd,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "unique_users_count": len(self.unique_users),
            "unique_tenants_count": len(self.unique_tenants),
            "hourly_usage": self.hourly_usage,
            "window_start": self.window_start.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }


class ToolExecutionTracker:
    """
    Tracks tool execution events and maintains usage analytics.
    Provides real-time metrics collection and aggregation.
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.redis_client: Optional[redis.Redis] = None
        self.serializer = EventSerializer()

        # In-memory statistics cache
        self.tool_stats: Dict[str, ToolUsageStats] = {}
        self.cache_duration = timedelta(hours=1)

        # Stream configuration
        self.stream_name = "ragline:stream:tool_executions"
        self.consumer_group = "ragline_tool_trackers"
        self.consumer_name = f"tool_tracker_{time.time()}"

    async def initialize(self):
        """Initialize Redis connection and create consumer group"""
        try:
            self.redis_client = await get_simple_redis_client()
            await self.redis_client.initialize()

            # Create consumer group if it doesn't exist
            try:
                await self.redis_client.xgroup_create(self.stream_name, self.consumer_group, "0", mkstream=True)
            except Exception as e:
                # Group already exists - this is expected
                logger.debug(f"Consumer group already exists: {e}")

            logger.info("Tool execution tracker initialized")

        except Exception as e:
            logger.error(f"Failed to initialize tool tracker: {e}")
            raise

    async def track_tool_execution(self, event: ToolExecutionEvent) -> bool:
        """
        Track a tool execution event and publish to stream.

        Args:
            event: Tool execution event to track

        Returns:
            bool: True if successfully tracked
        """
        try:
            # Validate event data
            event_dict = event.to_dict()

            # Publish to Redis stream
            if self.redis_client:
                await self.redis_client.xadd(self.stream_name, event_dict)
                logger.debug(f"Tool execution event published: {event.tool_execution_id}")

            # Update local statistics
            await self._update_tool_stats(event)

            # Update Prometheus metrics if available
            if TOOL_METRICS_AVAILABLE:
                record_tool_execution_from_event(event_dict)

            return True

        except Exception as e:
            logger.error(f"Failed to track tool execution: {e}")
            return False

    async def _update_tool_stats(self, event: ToolExecutionEvent):
        """Update local tool statistics cache"""
        tool_name = event.tool_name

        if tool_name not in self.tool_stats:
            self.tool_stats[tool_name] = ToolUsageStats(tool_name=tool_name)

        self.tool_stats[tool_name].update_from_event(event)

    async def get_tool_analytics(self, tool_name: Optional[str] = None, hours: int = 24) -> Dict[str, Any]:
        """
        Get tool usage analytics for specified time window.

        Args:
            tool_name: Specific tool name or None for all tools
            hours: Time window in hours

        Returns:
            Dict containing analytics data
        """
        try:
            analytics = {
                "time_window_hours": hours,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "tools": {},
                "summary": {
                    "total_executions": 0,
                    "total_tools": 0,
                    "avg_success_rate": 0.0,
                    "total_cost_usd": 0.0,
                },
            }

            # Get stats for specific tool or all tools
            if tool_name:
                if tool_name in self.tool_stats:
                    analytics["tools"][tool_name] = self.tool_stats[tool_name].to_dict()
            else:
                for name, stats in self.tool_stats.items():
                    analytics["tools"][name] = stats.to_dict()

            # Calculate summary statistics
            total_executions = 0
            total_success = 0
            total_cost = 0.0
            tool_count = len(analytics["tools"])

            for tool_data in analytics["tools"].values():
                total_executions += tool_data["total_executions"]
                total_success += tool_data["successful_executions"]
                total_cost += tool_data["total_cost_usd"]

            analytics["summary"]["total_executions"] = total_executions
            analytics["summary"]["total_tools"] = tool_count
            analytics["summary"]["avg_success_rate"] = (
                (total_success / total_executions * 100) if total_executions > 0 else 0.0
            )
            analytics["summary"]["total_cost_usd"] = total_cost

            # Add cache statistics if available
            if TOOL_CACHE_AVAILABLE:
                try:
                    cache_stats = await get_tool_cache_stats(tool_name=tool_name)
                    analytics["cache_performance"] = cache_stats
                except Exception as e:
                    logger.debug(f"Could not get cache stats: {e}")

            return analytics

        except Exception as e:
            logger.error(f"Failed to get tool analytics: {e}")
            return {"error": str(e)}

    async def get_tool_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary for all tools"""
        try:
            summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "performance_by_tool": {},
                "top_performers": {
                    "fastest_tools": [],
                    "most_used_tools": [],
                    "most_reliable_tools": [],
                    "most_expensive_tools": [],
                },
            }

            # Collect performance data
            tool_performance = []
            for tool_name, stats in self.tool_stats.items():
                perf_data = {
                    "tool_name": tool_name,
                    "avg_duration_ms": stats.average_duration_ms,
                    "success_rate": stats.success_rate,
                    "total_executions": stats.total_executions,
                    "avg_cost_usd": stats.average_cost_usd,
                }
                tool_performance.append(perf_data)
                summary["performance_by_tool"][tool_name] = perf_data

            # Sort and get top performers
            if tool_performance:
                # Fastest tools (lowest average duration)
                fastest = sorted(tool_performance, key=lambda x: x["avg_duration_ms"])[:5]
                summary["top_performers"]["fastest_tools"] = fastest

                # Most used tools
                most_used = sorted(tool_performance, key=lambda x: x["total_executions"], reverse=True)[:5]
                summary["top_performers"]["most_used_tools"] = most_used

                # Most reliable tools (highest success rate)
                most_reliable = sorted(tool_performance, key=lambda x: x["success_rate"], reverse=True)[:5]
                summary["top_performers"]["most_reliable_tools"] = most_reliable

                # Most expensive tools
                most_expensive = sorted(tool_performance, key=lambda x: x["avg_cost_usd"], reverse=True)[:5]
                summary["top_performers"]["most_expensive_tools"] = most_expensive

            return summary

        except Exception as e:
            logger.error(f"Failed to get performance summary: {e}")
            return {"error": str(e)}

    async def cleanup_old_stats(self, max_age_hours: int = 24):
        """Clean up old statistics to prevent memory leaks"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        removed_count = 0
        for tool_name in list(self.tool_stats.keys()):
            stats = self.tool_stats[tool_name]
            if stats.last_updated < cutoff_time:
                del self.tool_stats[tool_name]
                removed_count += 1

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} old tool statistics")

    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()


# Global tracker instance
_tool_tracker: Optional[ToolExecutionTracker] = None


async def get_tool_tracker() -> ToolExecutionTracker:
    """Get or create tool execution tracker instance"""
    global _tool_tracker

    if not _tool_tracker:
        config = WorkerConfig()
        _tool_tracker = ToolExecutionTracker(config)
        await _tool_tracker.initialize()

    return _tool_tracker


# Celery Tasks for Tool Tracking


class ToolTrackingTask(Task):
    """Base task for tool tracking with error handling"""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Tool tracking task failed: {exc}", exc_info=einfo)

    def on_success(self, retval, task_id, args, kwargs):
        logger.debug(f"Tool tracking task completed: {task_id}")


@app.task(
    bind=True,
    base=ToolTrackingTask,
    name="services.worker.tasks.tool_tracking.track_tool_execution",
)
def track_tool_execution(
    self,
    tenant_id: str,
    tool_name: str,
    status: str,
    user_id: Optional[str] = None,
    execution_data: Optional[Dict[str, Any]] = None,
    tool_parameters: Optional[Dict[str, Any]] = None,
    result_metadata: Optional[Dict[str, Any]] = None,
    error_details: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    tool_execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Track a tool execution event.

    Args:
        tenant_id: Tenant identifier
        tool_name: Name of the executed tool
        status: Execution status (started, completed, failed, etc.)
        user_id: User who executed the tool
        execution_data: Performance and execution metadata
        tool_parameters: Sanitized tool parameters
        result_metadata: Result statistics
        error_details: Error information for failed executions
        context: Additional execution context
        meta: Additional metadata and tags
        tool_execution_id: Unique execution identifier

    Returns:
        Dict with tracking result
    """

    async def _track():
        try:
            tracker = await get_tool_tracker()

            # Create tool execution event
            event = ToolExecutionEvent(
                tenant_id=tenant_id,
                tool_name=tool_name,
                status=status,
                user_id=user_id,
                execution_data=execution_data or {},
                tool_parameters=tool_parameters or {},
                result_metadata=result_metadata or {},
                error_details=error_details,
                context=context or {},
                meta=meta or {},
                tool_execution_id=tool_execution_id or str(uuid.uuid4()),
            )

            # Track the event
            success = await tracker.track_tool_execution(event)

            return {
                "status": "success" if success else "failed",
                "tool_execution_id": event.tool_execution_id,
                "tool_name": tool_name,
                "tracked_at": event.ts,
            }

        except Exception as e:
            logger.error(f"Failed to track tool execution: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    try:
        result = asyncio.run(_track())
        return result
    except Exception as e:
        logger.error(f"Failed to run tool tracking task: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(
    bind=True,
    base=ToolTrackingTask,
    name="services.worker.tasks.tool_tracking.get_tool_analytics",
)
def get_tool_analytics(self, tool_name: Optional[str] = None, hours: int = 24) -> Dict[str, Any]:
    """Get tool usage analytics"""

    async def _get_analytics():
        try:
            tracker = await get_tool_tracker()
            analytics = await tracker.get_tool_analytics(tool_name=tool_name, hours=hours)
            return analytics

        except Exception as e:
            logger.error(f"Failed to get tool analytics: {e}", exc_info=True)
            return {"error": str(e)}

    try:
        result = asyncio.run(_get_analytics())
        return result
    except Exception as e:
        logger.error(f"Failed to get tool analytics: {e}", exc_info=True)
        return {"error": str(e)}


@app.task(
    bind=True,
    base=ToolTrackingTask,
    name="services.worker.tasks.tool_tracking.get_tool_performance_summary",
)
def get_tool_performance_summary(self) -> Dict[str, Any]:
    """Get tool performance summary"""

    async def _get_summary():
        try:
            tracker = await get_tool_tracker()
            summary = await tracker.get_tool_performance_summary()
            return summary

        except Exception as e:
            logger.error(f"Failed to get tool performance summary: {e}", exc_info=True)
            return {"error": str(e)}

    try:
        result = asyncio.run(_get_summary())
        return result
    except Exception as e:
        logger.error(f"Failed to get tool performance summary: {e}", exc_info=True)
        return {"error": str(e)}


@app.task(
    bind=True,
    base=ToolTrackingTask,
    name="services.worker.tasks.tool_tracking.cleanup_old_tool_stats",
)
def cleanup_old_tool_stats(self, max_age_hours: int = 24) -> Dict[str, Any]:
    """Clean up old tool statistics"""

    async def _cleanup():
        try:
            tracker = await get_tool_tracker()
            await tracker.cleanup_old_stats(max_age_hours=max_age_hours)
            return {"status": "success", "max_age_hours": max_age_hours}

        except Exception as e:
            logger.error(f"Failed to cleanup tool stats: {e}", exc_info=True)
            return {"error": str(e)}

    try:
        result = asyncio.run(_cleanup())
        return result
    except Exception as e:
        logger.error(f"Failed to cleanup tool stats: {e}", exc_info=True)
        return {"error": str(e)}
