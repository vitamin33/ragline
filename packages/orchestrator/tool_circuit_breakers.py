"""
RAGline Tool-Specific Circuit Breakers

Specialized circuit breakers for protecting external API calls made by LLM tools.
Provides tool-aware failure detection, recovery strategies, and cost protection.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Type

from celery.utils.log import get_task_logger

from services.worker.config import WorkerConfig

from .circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState

logger = get_task_logger(__name__)


@dataclass
class ToolApiCallMetrics:
    """Metrics for tool API calls"""

    tool_name: str
    api_provider: str = "unknown"
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: float = 0.0
    last_call_time: Optional[datetime] = None

    # Rate limiting
    calls_per_minute: float = 0.0
    cost_per_minute_usd: float = 0.0

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_calls == 0:
            return 100.0
        return (self.successful_calls / self.total_calls) * 100

    @property
    def average_duration_ms(self) -> float:
        """Calculate average call duration"""
        if self.successful_calls == 0:
            return 0.0
        return self.total_duration_ms / self.successful_calls

    @property
    def average_cost_usd(self) -> float:
        """Calculate average call cost"""
        if self.total_calls == 0:
            return 0.0
        return self.total_cost_usd / self.total_calls


class ToolCircuitBreaker:
    """
    Circuit breaker specifically designed for LLM tool external API calls.

    Provides tool-aware failure detection, cost-based protection, and
    intelligent recovery strategies for different types of AI/ML services.
    """

    def __init__(
        self,
        tool_name: str,
        api_provider: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        cost_threshold_usd: Optional[float] = None,
        rate_limit_per_minute: Optional[int] = None,
        config: Optional[WorkerConfig] = None,
    ):
        self.tool_name = tool_name
        self.api_provider = api_provider
        self.cost_threshold_usd = cost_threshold_usd
        self.rate_limit_per_minute = rate_limit_per_minute
        self.config = config or WorkerConfig()

        # Create underlying circuit breaker
        self.circuit_breaker = CircuitBreaker(
            name=f"tool_{tool_name}_{api_provider}",
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            config=config,
        )

        # Tool-specific metrics
        self.api_metrics = ToolApiCallMetrics(
            tool_name=tool_name,
            api_provider=api_provider,
        )

        # Rate limiting tracking
        self.minute_window_start = time.time()
        self.minute_call_count = 0
        self.minute_cost_usd = 0.0

        logger.info(
            f"Tool circuit breaker initialized for {tool_name} -> {api_provider}",
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            cost_threshold=cost_threshold_usd,
            rate_limit=rate_limit_per_minute,
        )

    async def call_external_api(
        self,
        api_func: Callable,
        *args,
        expected_cost_usd: float = 0.0,
        **kwargs,
    ) -> Any:
        """
        Execute external API call with circuit breaker and cost protection.

        Args:
            api_func: The API function to call
            expected_cost_usd: Expected cost of this API call
            *args, **kwargs: Arguments to pass to the API function

        Returns:
            API call result

        Raises:
            CircuitBreakerError: If circuit is open
            RateLimitExceededError: If rate limits exceeded
            CostThresholdExceededError: If cost thresholds exceeded
        """

        # Check rate limiting
        await self._check_rate_limits(expected_cost_usd)

        # Check cost thresholds
        await self._check_cost_thresholds(expected_cost_usd)

        # Execute with circuit breaker protection
        start_time = time.time()
        try:
            result = await self.circuit_breaker.call(api_func, *args, **kwargs)

            # Record successful call
            duration_ms = (time.time() - start_time) * 1000
            await self._record_api_success(duration_ms, expected_cost_usd)

            return result

        except Exception as e:
            # Record failed call
            duration_ms = (time.time() - start_time) * 1000
            await self._record_api_failure(duration_ms, expected_cost_usd, e)
            raise

    async def _check_rate_limits(self, expected_cost_usd: float):
        """Check if rate limits would be exceeded"""
        current_time = time.time()

        # Reset minute window if needed
        if current_time - self.minute_window_start >= 60:
            self.minute_window_start = current_time
            self.minute_call_count = 0
            self.minute_cost_usd = 0.0

        # Check call rate limit
        if self.rate_limit_per_minute:
            if self.minute_call_count >= self.rate_limit_per_minute:
                raise RateLimitExceededError(
                    f"Rate limit exceeded: {self.minute_call_count}/{self.rate_limit_per_minute} calls per minute"
                )

        # Update tracking
        self.minute_call_count += 1
        self.minute_cost_usd += expected_cost_usd

    async def _check_cost_thresholds(self, expected_cost_usd: float):
        """Check if cost thresholds would be exceeded"""
        if self.cost_threshold_usd:
            if self.minute_cost_usd + expected_cost_usd > self.cost_threshold_usd:
                raise CostThresholdExceededError(
                    f"Cost threshold exceeded: ${self.minute_cost_usd + expected_cost_usd:.4f} > ${self.cost_threshold_usd:.4f}"
                )

    async def _record_api_success(self, duration_ms: float, cost_usd: float):
        """Record successful API call"""
        self.api_metrics.total_calls += 1
        self.api_metrics.successful_calls += 1
        self.api_metrics.total_duration_ms += duration_ms
        self.api_metrics.total_cost_usd += cost_usd
        self.api_metrics.last_call_time = datetime.now(timezone.utc)

        # Calculate rates (simple moving average)
        if self.api_metrics.total_calls > 0:
            time_window_minutes = max(1, (time.time() - self.minute_window_start) / 60)
            self.api_metrics.calls_per_minute = self.minute_call_count / time_window_minutes
            self.api_metrics.cost_per_minute_usd = self.minute_cost_usd / time_window_minutes

        logger.debug(
            "Tool API call successful",
            tool_name=self.tool_name,
            api_provider=self.api_provider,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
        )

    async def _record_api_failure(self, duration_ms: float, cost_usd: float, exception: Exception):
        """Record failed API call"""
        self.api_metrics.total_calls += 1
        self.api_metrics.failed_calls += 1
        self.api_metrics.total_duration_ms += duration_ms
        self.api_metrics.total_cost_usd += cost_usd
        self.api_metrics.last_call_time = datetime.now(timezone.utc)

        logger.warning(
            "Tool API call failed",
            tool_name=self.tool_name,
            api_provider=self.api_provider,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            error=str(exception),
            success_rate=self.api_metrics.success_rate,
        )

    async def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive metrics for this tool circuit breaker"""
        circuit_metrics = await self.circuit_breaker.get_metrics()

        return {
            "tool_name": self.tool_name,
            "api_provider": self.api_provider,
            "circuit_breaker": circuit_metrics,
            "api_metrics": {
                "total_calls": self.api_metrics.total_calls,
                "successful_calls": self.api_metrics.successful_calls,
                "failed_calls": self.api_metrics.failed_calls,
                "success_rate": self.api_metrics.success_rate,
                "total_cost_usd": self.api_metrics.total_cost_usd,
                "average_cost_usd": self.api_metrics.average_cost_usd,
                "total_duration_ms": self.api_metrics.total_duration_ms,
                "average_duration_ms": self.api_metrics.average_duration_ms,
                "last_call_time": self.api_metrics.last_call_time.isoformat()
                if self.api_metrics.last_call_time
                else None,
            },
            "rate_limiting": {
                "calls_per_minute": self.api_metrics.calls_per_minute,
                "cost_per_minute_usd": self.api_metrics.cost_per_minute_usd,
                "rate_limit_per_minute": self.rate_limit_per_minute,
                "cost_threshold_usd": self.cost_threshold_usd,
            },
        }

    async def reset(self):
        """Reset circuit breaker and metrics"""
        await self.circuit_breaker.reset()
        self.api_metrics = ToolApiCallMetrics(
            tool_name=self.tool_name,
            api_provider=self.api_provider,
        )

        # Reset rate limiting
        self.minute_window_start = time.time()
        self.minute_call_count = 0
        self.minute_cost_usd = 0.0

        logger.info(f"Tool circuit breaker reset: {self.tool_name} -> {self.api_provider}")


class ToolCircuitBreakerRegistry:
    """Registry for managing tool-specific circuit breakers"""

    def __init__(self, config: Optional[WorkerConfig] = None):
        self.config = config or WorkerConfig()
        self._tool_breakers: Dict[str, ToolCircuitBreaker] = {}

        # Default configurations for common API providers
        self.provider_defaults = {
            "openai": {
                "failure_threshold": 3,
                "recovery_timeout": 30,
                "cost_threshold_usd": 1.0,  # $1 per minute
                "rate_limit_per_minute": 60,
            },
            "anthropic": {
                "failure_threshold": 3,
                "recovery_timeout": 30,
                "cost_threshold_usd": 0.5,  # $0.50 per minute
                "rate_limit_per_minute": 50,
            },
            "local": {
                "failure_threshold": 5,
                "recovery_timeout": 10,
                "cost_threshold_usd": None,  # No cost limits for local
                "rate_limit_per_minute": 120,
            },
            "database": {
                "failure_threshold": 10,
                "recovery_timeout": 5,
                "cost_threshold_usd": None,
                "rate_limit_per_minute": 1000,
            },
        }

    def get_or_create_tool_breaker(
        self,
        tool_name: str,
        api_provider: str,
        **override_config,
    ) -> ToolCircuitBreaker:
        """Get or create tool-specific circuit breaker"""

        breaker_key = f"{tool_name}_{api_provider}"

        if breaker_key not in self._tool_breakers:
            # Get provider defaults and apply overrides
            provider_config = self.provider_defaults.get(api_provider, self.provider_defaults["openai"])
            config = {**provider_config, **override_config}

            self._tool_breakers[breaker_key] = ToolCircuitBreaker(
                tool_name=tool_name,
                api_provider=api_provider,
                failure_threshold=config["failure_threshold"],
                recovery_timeout=config["recovery_timeout"],
                cost_threshold_usd=config["cost_threshold_usd"],
                rate_limit_per_minute=config["rate_limit_per_minute"],
                config=self.config,
            )

        return self._tool_breakers[breaker_key]

    async def get_all_tool_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all tool circuit breakers"""
        metrics = {}
        for breaker_key, breaker in self._tool_breakers.items():
            metrics[breaker_key] = await breaker.get_metrics()
        return metrics

    async def reset_all_tool_breakers(self):
        """Reset all tool circuit breakers"""
        for breaker in self._tool_breakers.values():
            await breaker.reset()

    def get_tool_breakers_by_provider(self, api_provider: str) -> List[ToolCircuitBreaker]:
        """Get all circuit breakers for a specific API provider"""
        return [breaker for breaker in self._tool_breakers.values() if breaker.api_provider == api_provider]

    def get_tool_breakers_by_tool(self, tool_name: str) -> List[ToolCircuitBreaker]:
        """Get all circuit breakers for a specific tool"""
        return [breaker for breaker in self._tool_breakers.values() if breaker.tool_name == tool_name]


# Custom exceptions for tool circuit breakers


class RateLimitExceededError(Exception):
    """Raised when tool API rate limits are exceeded"""

    pass


class CostThresholdExceededError(Exception):
    """Raised when tool API cost thresholds are exceeded"""

    pass


# Global registry instance
_tool_breaker_registry = ToolCircuitBreakerRegistry()


def get_tool_circuit_breaker(
    tool_name: str,
    api_provider: str,
    **config_overrides,
) -> ToolCircuitBreaker:
    """Get or create a tool-specific circuit breaker"""
    return _tool_breaker_registry.get_or_create_tool_breaker(
        tool_name=tool_name,
        api_provider=api_provider,
        **config_overrides,
    )


def tool_circuit_breaker(
    tool_name: str,
    api_provider: str,
    expected_cost_usd: float = 0.0,
    **config_overrides,
):
    """Decorator to add tool circuit breaker protection to API calls"""

    def decorator(func: Callable):
        breaker = get_tool_circuit_breaker(
            tool_name=tool_name,
            api_provider=api_provider,
            **config_overrides,
        )

        async def wrapper(*args, **kwargs):
            return await breaker.call_external_api(func, *args, expected_cost_usd=expected_cost_usd, **kwargs)

        return wrapper

    return decorator


# Helper functions for common tool integrations


async def protected_openai_call(
    tool_name: str,
    api_func: Callable,
    expected_cost_usd: float,
    *args,
    **kwargs,
) -> Any:
    """Helper for OpenAI API calls with circuit breaker protection"""
    breaker = get_tool_circuit_breaker(
        tool_name=tool_name,
        api_provider="openai",
    )

    return await breaker.call_external_api(
        api_func,
        *args,
        expected_cost_usd=expected_cost_usd,
        **kwargs,
    )


async def protected_database_call(
    tool_name: str,
    db_func: Callable,
    *args,
    **kwargs,
) -> Any:
    """Helper for database calls with circuit breaker protection"""
    breaker = get_tool_circuit_breaker(
        tool_name=tool_name,
        api_provider="database",
        failure_threshold=10,  # Higher threshold for DB
        recovery_timeout=5,  # Faster recovery for DB
    )

    return await breaker.call_external_api(
        db_func,
        *args,
        expected_cost_usd=0.0,
        **kwargs,
    )


async def protected_local_model_call(
    tool_name: str,
    model_func: Callable,
    *args,
    **kwargs,
) -> Any:
    """Helper for local model calls with circuit breaker protection"""
    breaker = get_tool_circuit_breaker(
        tool_name=tool_name,
        api_provider="local",
        failure_threshold=8,
        recovery_timeout=15,
    )

    return await breaker.call_external_api(
        model_func,
        *args,
        expected_cost_usd=0.0,
        **kwargs,
    )


async def get_all_tool_breaker_metrics() -> Dict[str, Dict[str, Any]]:
    """Get metrics for all tool circuit breakers"""
    return await _tool_breaker_registry.get_all_tool_metrics()


async def reset_all_tool_breakers():
    """Reset all tool circuit breakers"""
    await _tool_breaker_registry.reset_all_tool_breakers()


# Integration with tool metrics system
async def update_tool_metrics_from_breaker(breaker: ToolCircuitBreaker):
    """Update tool metrics from circuit breaker data"""
    try:
        # Import here to avoid circular imports
        from .tool_metrics import get_tool_metrics

        tool_metrics = get_tool_metrics()

        # Update circuit breaker state
        cb_metrics = await breaker.circuit_breaker.get_metrics()
        tool_metrics.update_circuit_breaker_state(
            tool_name=breaker.tool_name,
            tenant_id="aggregate",  # Tool-level aggregation
            state=cb_metrics["state"],
        )

        # Update external API call metrics
        if breaker.api_metrics.total_calls > 0:
            status = "success" if breaker.api_metrics.success_rate > 50 else "degraded"

            tool_metrics.tool_external_api_calls.labels(
                tool_name=breaker.tool_name,
                api_provider=breaker.api_provider,
                status=status,
                tenant_id="aggregate",
            ).inc(breaker.api_metrics.successful_calls)

    except Exception as e:
        logger.error(f"Failed to update tool metrics from breaker: {e}")
