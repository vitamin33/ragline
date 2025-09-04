"""
RAGline Tool-Specific Prometheus Metrics

Comprehensive metrics collection for LLM tool execution tracking, performance monitoring,
and cost optimization. Provides detailed observability for AI/ML operations.
"""

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import psutil
from celery.utils.log import get_task_logger
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
)

from services.worker.config import WorkerConfig

logger = get_task_logger(__name__)


class ToolMetrics:
    """
    Tool-specific Prometheus metrics for LLM orchestration monitoring.

    Tracks tool execution performance, costs, usage patterns, and resource consumption
    for production AI/ML systems observability.
    """

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or CollectorRegistry()
        self.config = WorkerConfig()

        # Metric name prefix
        self.prefix = "ragline_tool_"

        # Initialize all tool metrics
        self._init_execution_metrics()
        self._init_performance_metrics()
        self._init_usage_metrics()
        self._init_cost_metrics()
        self._init_resource_metrics()
        self._init_error_metrics()

        # Track tool registry
        self.registered_tools: Set[str] = set()

        logger.info("Tool metrics initialized with comprehensive observability")

    def _init_execution_metrics(self):
        """Initialize tool execution tracking metrics"""

        # Tool execution latency histogram with percentiles
        self.tool_execution_duration = Histogram(
            name=f"{self.prefix}execution_duration_seconds",
            documentation="Tool execution duration in seconds by tool name and status",
            labelnames=["tool_name", "status", "tenant_id"],
            buckets=(
                0.001,
                0.005,
                0.01,
                0.025,
                0.05,
                0.075,
                0.1,
                0.25,
                0.5,
                0.75,
                1.0,
                2.5,
                5.0,
                7.5,
                10.0,
                float("inf"),
            ),
            registry=self.registry,
        )

        # Tool execution counter for total executions
        self.tool_executions_total = Counter(
            name=f"{self.prefix}executions_total",
            documentation="Total number of tool executions by tool name and status",
            labelnames=["tool_name", "status", "tenant_id", "user_id"],
            registry=self.registry,
        )

        # Currently executing tools gauge
        self.tool_executions_active = Gauge(
            name=f"{self.prefix}executions_active",
            documentation="Number of currently executing tools by tool name",
            labelnames=["tool_name", "tenant_id"],
            registry=self.registry,
        )

    def _init_performance_metrics(self):
        """Initialize performance-specific metrics"""

        # Success rate gauge (calculated periodically)
        self.tool_success_rate = Gauge(
            name=f"{self.prefix}success_rate",
            documentation="Tool success rate percentage by tool name",
            labelnames=["tool_name", "tenant_id"],
            registry=self.registry,
        )

        # Cache hit rate for tool results
        self.tool_cache_hit_rate = Gauge(
            name=f"{self.prefix}cache_hit_rate",
            documentation="Cache hit rate for tool results by tool name",
            labelnames=["tool_name", "tenant_id"],
            registry=self.registry,
        )

        # Cache operations counter
        self.tool_cache_operations = Counter(
            name=f"{self.prefix}cache_operations_total",
            documentation="Tool cache operations (hit/miss/set) by tool name",
            labelnames=["tool_name", "operation", "tenant_id"],
            registry=self.registry,
        )

        # External API calls made by tools
        self.tool_external_api_calls = Counter(
            name=f"{self.prefix}external_api_calls_total",
            documentation="External API calls made by tools",
            labelnames=["tool_name", "api_provider", "status", "tenant_id"],
            registry=self.registry,
        )

    def _init_usage_metrics(self):
        """Initialize usage pattern metrics"""

        # Unique users per tool (gauge updated periodically)
        self.tool_unique_users = Gauge(
            name=f"{self.prefix}unique_users",
            documentation="Number of unique users per tool in current window",
            labelnames=["tool_name", "tenant_id"],
            registry=self.registry,
        )

        # Tool queue length
        self.tool_queue_length = Gauge(
            name=f"{self.prefix}queue_length",
            documentation="Number of pending tool executions in queue",
            labelnames=["tool_name", "queue_type"],
            registry=self.registry,
        )

        # Concurrent tool sessions
        self.tool_concurrent_sessions = Gauge(
            name=f"{self.prefix}concurrent_sessions",
            documentation="Number of concurrent tool execution sessions",
            labelnames=["tool_name", "tenant_id"],
            registry=self.registry,
        )

    def _init_cost_metrics(self):
        """Initialize cost tracking metrics"""

        # Token usage histogram
        self.tool_tokens_processed = Histogram(
            name=f"{self.prefix}tokens_processed",
            documentation="Number of tokens processed by tool executions",
            labelnames=["tool_name", "token_type", "tenant_id"],  # token_type: input/output
            buckets=(
                10,
                50,
                100,
                250,
                500,
                750,
                1000,
                2500,
                5000,
                7500,
                10000,
                15000,
                20000,
                30000,
                50000,
                float("inf"),
            ),
            registry=self.registry,
        )

        # Cost tracking in USD (histogram for cost distribution)
        self.tool_cost_usd = Histogram(
            name=f"{self.prefix}cost_usd",
            documentation="Tool execution cost in USD",
            labelnames=["tool_name", "tenant_id", "model"],
            buckets=(
                0.0001,
                0.0005,
                0.001,
                0.005,
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1.0,
                2.0,
                5.0,
                10.0,
                float("inf"),
            ),
            registry=self.registry,
        )

        # Total cost counter for budget tracking
        self.tool_cost_total = Counter(
            name=f"{self.prefix}cost_total_usd",
            documentation="Total tool execution cost in USD",
            labelnames=["tool_name", "tenant_id", "model"],
            registry=self.registry,
        )

    def _init_resource_metrics(self):
        """Initialize resource consumption metrics"""

        # Memory usage during tool execution
        self.tool_memory_usage = Histogram(
            name=f"{self.prefix}memory_usage_mb",
            documentation="Memory usage during tool execution in MB",
            labelnames=["tool_name", "tenant_id"],
            buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000, 4000, float("inf")),
            registry=self.registry,
        )

        # CPU usage percentage during execution
        self.tool_cpu_usage = Histogram(
            name=f"{self.prefix}cpu_usage_percent",
            documentation="CPU usage percentage during tool execution",
            labelnames=["tool_name", "tenant_id"],
            buckets=(1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, float("inf")),
            registry=self.registry,
        )

        # Database queries per tool execution
        self.tool_db_queries = Counter(
            name=f"{self.prefix}database_queries_total",
            documentation="Number of database queries by tool executions",
            labelnames=["tool_name", "query_type", "tenant_id"],
            registry=self.registry,
        )

    def _init_error_metrics(self):
        """Initialize error tracking metrics"""

        # Error counter by error type
        self.tool_errors = Counter(
            name=f"{self.prefix}errors_total",
            documentation="Tool execution errors by type",
            labelnames=["tool_name", "error_type", "error_code", "tenant_id"],
            registry=self.registry,
        )

        # Timeout counter
        self.tool_timeouts = Counter(
            name=f"{self.prefix}timeouts_total",
            documentation="Tool execution timeouts",
            labelnames=["tool_name", "tenant_id"],
            registry=self.registry,
        )

        # Circuit breaker state gauge
        self.tool_circuit_breaker_state = Gauge(
            name=f"{self.prefix}circuit_breaker_state",
            documentation="Circuit breaker state (0=closed, 1=open, 2=half_open)",
            labelnames=["tool_name", "tenant_id"],
            registry=self.registry,
        )

        # Retry counter
        self.tool_retries = Counter(
            name=f"{self.prefix}retries_total",
            documentation="Tool execution retry attempts",
            labelnames=["tool_name", "retry_reason", "tenant_id"],
            registry=self.registry,
        )

    def record_tool_execution_start(
        self,
        tool_name: str,
        tenant_id: str,
        user_id: Optional[str] = None,
    ):
        """Record tool execution start"""
        try:
            # Increment active executions
            self.tool_executions_active.labels(
                tool_name=tool_name,
                tenant_id=tenant_id,
            ).inc()

            # Register tool if new
            if tool_name not in self.registered_tools:
                self.registered_tools.add(tool_name)
                logger.debug(f"Registered new tool for metrics: {tool_name}")

        except Exception as e:
            logger.error(f"Failed to record tool execution start: {e}")

    def record_tool_execution_complete(
        self,
        tool_name: str,
        tenant_id: str,
        status: str,
        duration_seconds: float,
        user_id: Optional[str] = None,
        execution_data: Optional[Dict[str, Any]] = None,
        result_metadata: Optional[Dict[str, Any]] = None,
    ):
        """Record tool execution completion with comprehensive metrics"""
        try:
            # Record duration
            self.tool_execution_duration.labels(
                tool_name=tool_name,
                status=status,
                tenant_id=tenant_id,
            ).observe(duration_seconds)

            # Increment execution counter
            self.tool_executions_total.labels(
                tool_name=tool_name,
                status=status,
                tenant_id=tenant_id,
                user_id=user_id or "anonymous",
            ).inc()

            # Decrement active executions
            self.tool_executions_active.labels(
                tool_name=tool_name,
                tenant_id=tenant_id,
            ).dec()

            # Record execution data if available
            if execution_data:
                self._record_execution_data(tool_name, tenant_id, execution_data)

            # Record result metadata if available
            if result_metadata:
                self._record_result_metadata(tool_name, tenant_id, result_metadata)

        except Exception as e:
            logger.error(f"Failed to record tool execution completion: {e}")

    def _record_execution_data(
        self,
        tool_name: str,
        tenant_id: str,
        execution_data: Dict[str, Any],
    ):
        """Record detailed execution data metrics"""
        try:
            # Token usage
            if "input_tokens" in execution_data:
                self.tool_tokens_processed.labels(
                    tool_name=tool_name,
                    token_type="input",
                    tenant_id=tenant_id,
                ).observe(execution_data["input_tokens"])

            if "output_tokens" in execution_data:
                self.tool_tokens_processed.labels(
                    tool_name=tool_name,
                    token_type="output",
                    tenant_id=tenant_id,
                ).observe(execution_data["output_tokens"])

            # Cost tracking
            if "cost_usd" in execution_data:
                cost = execution_data["cost_usd"]
                model = execution_data.get("model", "unknown")

                self.tool_cost_usd.labels(
                    tool_name=tool_name,
                    tenant_id=tenant_id,
                    model=model,
                ).observe(cost)

                self.tool_cost_total.labels(
                    tool_name=tool_name,
                    tenant_id=tenant_id,
                    model=model,
                ).inc(cost)

            # Resource usage
            if "memory_usage_mb" in execution_data:
                self.tool_memory_usage.labels(
                    tool_name=tool_name,
                    tenant_id=tenant_id,
                ).observe(execution_data["memory_usage_mb"])

            # Cache usage
            if "cache_hit" in execution_data:
                cache_op = "hit" if execution_data["cache_hit"] else "miss"
                self.tool_cache_operations.labels(
                    tool_name=tool_name,
                    operation=cache_op,
                    tenant_id=tenant_id,
                ).inc()

            # External API calls
            if "external_api_calls" in execution_data:
                api_calls = execution_data["external_api_calls"]
                if api_calls > 0:
                    self.tool_external_api_calls.labels(
                        tool_name=tool_name,
                        api_provider=execution_data.get("api_provider", "unknown"),
                        status="success",
                        tenant_id=tenant_id,
                    ).inc(api_calls)

        except Exception as e:
            logger.error(f"Failed to record execution data: {e}")

    def _record_result_metadata(
        self,
        tool_name: str,
        tenant_id: str,
        result_metadata: Dict[str, Any],
    ):
        """Record result metadata metrics"""
        try:
            # Database queries if tracked
            if "db_queries" in result_metadata:
                query_count = result_metadata["db_queries"]
                query_type = result_metadata.get("query_type", "select")

                self.tool_db_queries.labels(
                    tool_name=tool_name,
                    query_type=query_type,
                    tenant_id=tenant_id,
                ).inc(query_count)

        except Exception as e:
            logger.error(f"Failed to record result metadata: {e}")

    def record_tool_error(
        self,
        tool_name: str,
        tenant_id: str,
        error_type: str,
        error_code: str = "unknown",
        is_timeout: bool = False,
    ):
        """Record tool execution error"""
        try:
            # Record error
            self.tool_errors.labels(
                tool_name=tool_name,
                error_type=error_type,
                error_code=error_code,
                tenant_id=tenant_id,
            ).inc()

            # Record timeout specifically
            if is_timeout:
                self.tool_timeouts.labels(
                    tool_name=tool_name,
                    tenant_id=tenant_id,
                ).inc()

            # Decrement active executions on error
            self.tool_executions_active.labels(
                tool_name=tool_name,
                tenant_id=tenant_id,
            ).dec()

        except Exception as e:
            logger.error(f"Failed to record tool error: {e}")

    def record_tool_retry(
        self,
        tool_name: str,
        tenant_id: str,
        retry_reason: str,
    ):
        """Record tool execution retry"""
        try:
            self.tool_retries.labels(
                tool_name=tool_name,
                retry_reason=retry_reason,
                tenant_id=tenant_id,
            ).inc()

        except Exception as e:
            logger.error(f"Failed to record tool retry: {e}")

    def update_circuit_breaker_state(
        self,
        tool_name: str,
        tenant_id: str,
        state: str,  # closed, open, half_open
    ):
        """Update circuit breaker state gauge"""
        try:
            state_value = {"closed": 0, "open": 1, "half_open": 2}.get(state, 0)

            self.tool_circuit_breaker_state.labels(
                tool_name=tool_name,
                tenant_id=tenant_id,
            ).set(state_value)

        except Exception as e:
            logger.error(f"Failed to update circuit breaker state: {e}")

    def update_success_rates(self, analytics_data: Dict[str, Any]):
        """Update success rate gauges from analytics data"""
        try:
            if "tools" in analytics_data:
                for tool_name, tool_data in analytics_data["tools"].items():
                    success_rate = tool_data.get("success_rate", 0.0)
                    tenant_count = tool_data.get("unique_tenants_count", 1)

                    # Set success rate for each tenant (simplified for now)
                    self.tool_success_rate.labels(
                        tool_name=tool_name,
                        tenant_id="aggregate",
                    ).set(success_rate)

        except Exception as e:
            logger.error(f"Failed to update success rates: {e}")

    def update_cache_hit_rates(self, tool_name: str, tenant_id: str, hit_rate: float):
        """Update cache hit rate gauge"""
        try:
            self.tool_cache_hit_rate.labels(
                tool_name=tool_name,
                tenant_id=tenant_id,
            ).set(hit_rate)

        except Exception as e:
            logger.error(f"Failed to update cache hit rate: {e}")

    def record_system_resources(self):
        """Record current system resource usage"""
        try:
            # Get current CPU and memory usage
            cpu_percent = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            memory_mb = memory.used / 1024 / 1024

            # Record as system-wide metrics (can be tool-specific if needed)
            for tool_name in self.registered_tools:
                self.tool_cpu_usage.labels(
                    tool_name="system",
                    tenant_id="system",
                ).observe(cpu_percent)

                self.tool_memory_usage.labels(
                    tool_name="system",
                    tenant_id="system",
                ).observe(memory_mb)

        except Exception as e:
            logger.error(f"Failed to record system resources: {e}")

    def get_registry(self) -> CollectorRegistry:
        """Get the metrics registry"""
        return self.registry

    def get_registered_tools(self) -> List[str]:
        """Get list of registered tools"""
        return list(self.registered_tools)


# Global tool metrics instance
_tool_metrics: Optional[ToolMetrics] = None


def get_tool_metrics() -> ToolMetrics:
    """Get or create tool metrics instance"""
    global _tool_metrics

    if not _tool_metrics:
        _tool_metrics = ToolMetrics()

    return _tool_metrics


def record_tool_execution_from_event(event_data: Dict[str, Any]):
    """Helper function to record metrics from tool execution event"""
    try:
        metrics = get_tool_metrics()

        tool_name = event_data.get("tool_name")
        tenant_id = event_data.get("tenant_id")
        status = event_data.get("status")
        user_id = event_data.get("user_id")

        if not all([tool_name, tenant_id, status]):
            logger.warning("Missing required fields in tool execution event")
            return

        execution_data = event_data.get("execution_data", {})
        result_metadata = event_data.get("result_metadata", {})
        error_details = event_data.get("error_details", {})

        if status == "started":
            metrics.record_tool_execution_start(
                tool_name=tool_name,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        elif status in ["completed", "cached"]:
            duration_ms = execution_data.get("duration_ms", 0)
            duration_seconds = duration_ms / 1000.0

            metrics.record_tool_execution_complete(
                tool_name=tool_name,
                tenant_id=tenant_id,
                status=status,
                duration_seconds=duration_seconds,
                user_id=user_id,
                execution_data=execution_data,
                result_metadata=result_metadata,
            )
        elif status == "failed":
            error_type = error_details.get("error_type", "unknown")
            error_code = error_details.get("error_code", "unknown")
            is_timeout = error_type == "timeout"

            metrics.record_tool_error(
                tool_name=tool_name,
                tenant_id=tenant_id,
                error_type=error_type,
                error_code=error_code,
                is_timeout=is_timeout,
            )

        # Record retries if present
        retry_count = error_details.get("retry_count", 0)
        if retry_count > 0:
            metrics.record_tool_retry(
                tool_name=tool_name,
                tenant_id=tenant_id,
                retry_reason=error_details.get("retry_reason", "unknown"),
            )

        # Update circuit breaker state if present
        cb_state = error_details.get("circuit_breaker_state")
        if cb_state:
            metrics.update_circuit_breaker_state(
                tool_name=tool_name,
                tenant_id=tenant_id,
                state=cb_state,
            )

    except Exception as e:
        logger.error(f"Failed to record tool metrics from event: {e}")
