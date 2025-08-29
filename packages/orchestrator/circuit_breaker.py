"""
RAGline Circuit Breaker Implementation

Implements the Circuit Breaker pattern to prevent cascade failures
when calling external services. Supports configurable failure thresholds,
recovery timeouts, and half-open state testing.
"""

import asyncio
import functools
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type, Union

from celery.utils.log import get_task_logger

from services.worker.config import WorkerConfig

logger = get_task_logger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states"""

    CLOSED = "closed"  # Normal operation, calls pass through
    OPEN = "open"  # Circuit is open, calls fail immediately
    HALF_OPEN = "half_open"  # Testing recovery, limited calls allowed


@dataclass
class CircuitBreakerMetrics:
    """Circuit breaker metrics and statistics"""

    # State tracking
    state: CircuitState = CircuitState.CLOSED
    last_state_change: float = field(default_factory=time.time)

    # Failure tracking
    failure_count: int = 0
    success_count: int = 0
    total_requests: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    # Timing metrics
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    average_response_time: float = 0.0
    response_times: List[float] = field(default_factory=list)

    # Rate calculations (moving window)
    failure_rate: float = 0.0
    success_rate: float = 0.0

    def update_response_time(self, response_time: float):
        """Update response time metrics"""
        self.response_times.append(response_time)

        # Keep only last 100 response times for moving average
        if len(self.response_times) > 100:
            self.response_times.pop(0)

        self.average_response_time = sum(self.response_times) / len(self.response_times)

    def calculate_rates(self):
        """Calculate failure and success rates"""
        if self.total_requests > 0:
            self.failure_rate = self.failure_count / self.total_requests
            self.success_rate = self.success_count / self.total_requests

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for monitoring"""
        return {
            "state": self.state.value,
            "last_state_change": self.last_state_change,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "total_requests": self.total_requests,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "average_response_time": self.average_response_time,
            "failure_rate": self.failure_rate,
            "success_rate": self.success_rate,
            "uptime_percentage": self.success_rate * 100,
        }


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open"""

    pass


class CircuitBreaker:
    """
    Circuit Breaker implementation for protecting external service calls.

    States:
    - CLOSED: Normal operation, all calls pass through
    - OPEN: Circuit is open, calls fail immediately with CircuitBreakerError
    - HALF_OPEN: Testing recovery, limited calls allowed to test service health
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Type[Exception] = Exception,
        half_open_max_calls: int = 3,
        config: Optional[WorkerConfig] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.half_open_max_calls = half_open_max_calls
        self.config = config or WorkerConfig()

        # Metrics and state
        self.metrics = CircuitBreakerMetrics()
        self.half_open_calls = 0

        # Lock for thread safety
        self._lock = asyncio.Lock()

        logger.info(
            f"Circuit breaker '{name}' initialized: "
            f"failure_threshold={failure_threshold}, "
            f"recovery_timeout={recovery_timeout}s"
        )

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        async with self._lock:
            # Check if circuit should change state
            await self._check_state_transition()

            # Handle open circuit
            if self.metrics.state == CircuitState.OPEN:
                logger.warning(f"Circuit breaker '{self.name}' is OPEN - rejecting call")
                raise CircuitBreakerError(f"Circuit breaker '{self.name}' is open")

            # Handle half-open circuit
            if self.metrics.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.half_open_max_calls:
                    logger.warning(f"Circuit breaker '{self.name}' half-open limit reached")
                    raise CircuitBreakerError(f"Circuit breaker '{self.name}' half-open limit exceeded")

                self.half_open_calls += 1

        # Execute the actual function call
        start_time = time.time()
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Record success
            response_time = time.time() - start_time
            await self._record_success(response_time)

            return result

        except self.expected_exception as e:
            # Record failure
            response_time = time.time() - start_time
            await self._record_failure(response_time, e)
            raise

    async def _check_state_transition(self):
        """Check if circuit breaker should transition states"""
        current_time = time.time()

        if self.metrics.state == CircuitState.CLOSED:
            # Check if we should open the circuit
            if self.metrics.consecutive_failures >= self.failure_threshold:
                await self._transition_to_open()

        elif self.metrics.state == CircuitState.OPEN:
            # Check if we should try half-open
            if current_time - self.metrics.last_state_change >= self.recovery_timeout:
                await self._transition_to_half_open()

        elif self.metrics.state == CircuitState.HALF_OPEN:
            # Check if we should close or re-open
            if self.metrics.consecutive_successes >= self.half_open_max_calls:
                await self._transition_to_closed()
            elif self.metrics.consecutive_failures > 0:
                await self._transition_to_open()

    async def _transition_to_open(self):
        """Transition circuit to OPEN state"""
        self.metrics.state = CircuitState.OPEN
        self.metrics.last_state_change = time.time()
        self.half_open_calls = 0

        logger.warning(
            f"Circuit breaker '{self.name}' opened due to {self.metrics.consecutive_failures} consecutive failures"
        )

    async def _transition_to_half_open(self):
        """Transition circuit to HALF_OPEN state"""
        self.metrics.state = CircuitState.HALF_OPEN
        self.metrics.last_state_change = time.time()
        self.half_open_calls = 0

        logger.info(f"Circuit breaker '{self.name}' transitioning to half-open for recovery testing")

    async def _transition_to_closed(self):
        """Transition circuit to CLOSED state"""
        self.metrics.state = CircuitState.CLOSED
        self.metrics.last_state_change = time.time()
        self.metrics.consecutive_failures = 0
        self.half_open_calls = 0

        logger.info(f"Circuit breaker '{self.name}' closed - service recovered")

    async def _record_success(self, response_time: float):
        """Record a successful call"""
        async with self._lock:
            self.metrics.success_count += 1
            self.metrics.total_requests += 1
            self.metrics.consecutive_successes += 1
            self.metrics.consecutive_failures = 0
            self.metrics.last_success_time = time.time()
            self.metrics.update_response_time(response_time)
            self.metrics.calculate_rates()

            logger.debug(f"Circuit breaker '{self.name}' recorded success " f"(response_time={response_time:.3f}s)")

    async def _record_failure(self, response_time: float, exception: Exception):
        """Record a failed call"""
        async with self._lock:
            self.metrics.failure_count += 1
            self.metrics.total_requests += 1
            self.metrics.consecutive_failures += 1
            self.metrics.consecutive_successes = 0
            self.metrics.last_failure_time = time.time()
            self.metrics.update_response_time(response_time)
            self.metrics.calculate_rates()

            logger.warning(
                f"Circuit breaker '{self.name}' recorded failure: {exception} "
                f"(consecutive_failures={self.metrics.consecutive_failures}, response_time={response_time:.3f}s)"
            )

    async def get_metrics(self) -> Dict[str, Any]:
        """Get current circuit breaker metrics"""
        async with self._lock:
            return {
                "name": self.name,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "half_open_max_calls": self.half_open_max_calls,
                **self.metrics.to_dict(),
            }

    async def reset(self):
        """Manually reset circuit breaker to closed state"""
        async with self._lock:
            self.metrics = CircuitBreakerMetrics()
            self.half_open_calls = 0

            logger.info(f"Circuit breaker '{self.name}' manually reset")

    async def force_open(self):
        """Manually force circuit breaker to open state"""
        async with self._lock:
            await self._transition_to_open()

            logger.warning(f"Circuit breaker '{self.name}' manually forced open")


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers"""

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._config = WorkerConfig()

    def get_or_create(
        self,
        name: str,
        failure_threshold: Optional[int] = None,
        recovery_timeout: Optional[int] = None,
        expected_exception: Type[Exception] = Exception,
    ) -> CircuitBreaker:
        """Get existing circuit breaker or create new one"""

        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold or self._config.circuit_breaker_failure_threshold,
                recovery_timeout=recovery_timeout or self._config.circuit_breaker_recovery_timeout,
                expected_exception=expected_exception,
                config=self._config,
            )

        return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name"""
        return self._breakers.get(name)

    async def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all circuit breakers"""
        metrics = {}
        for name, breaker in self._breakers.items():
            metrics[name] = await breaker.get_metrics()
        return metrics

    async def reset_all(self):
        """Reset all circuit breakers"""
        for breaker in self._breakers.values():
            await breaker.reset()

    def list_breakers(self) -> List[str]:
        """List all registered circuit breaker names"""
        return list(self._breakers.keys())


# Global registry instance
_registry = CircuitBreakerRegistry()


def get_circuit_breaker(
    name: str,
    failure_threshold: Optional[int] = None,
    recovery_timeout: Optional[int] = None,
    expected_exception: Type[Exception] = Exception,
) -> CircuitBreaker:
    """Get or create a circuit breaker from the global registry"""
    return _registry.get_or_create(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        expected_exception=expected_exception,
    )


def circuit_breaker(
    name: str,
    failure_threshold: Optional[int] = None,
    recovery_timeout: Optional[int] = None,
    expected_exception: Type[Exception] = Exception,
):
    """Decorator to add circuit breaker protection to functions"""

    def decorator(func: Callable):
        breaker = get_circuit_breaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception,
        )

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator


async def get_registry_metrics() -> Dict[str, Dict[str, Any]]:
    """Get metrics for all circuit breakers in the registry"""
    return await _registry.get_all_metrics()


async def reset_all_circuit_breakers():
    """Reset all circuit breakers in the registry"""
    await _registry.reset_all()
