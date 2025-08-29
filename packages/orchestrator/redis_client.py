"""
RAGline Redis Client with Connection Pooling and Streams

Provides Redis connection management, connection pooling, and Redis Streams
operations with retry logic and exponential backoff for reliable event processing.
"""

import asyncio
import json
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as redis
from celery.utils.log import get_task_logger
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import ConnectionError, ResponseError, TimeoutError

from services.worker.config import WorkerConfig

logger = get_task_logger(__name__)


class RetryStrategy(str, Enum):
    """Retry strategies for Redis operations"""

    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_DELAY = "fixed_delay"


@dataclass
class RetryConfig:
    """Configuration for retry logic"""

    max_retries: int = 3
    base_delay: float = 0.1  # Base delay in seconds
    max_delay: float = 30.0  # Maximum delay in seconds
    backoff_multiplier: float = 2.0
    jitter: bool = True  # Add random jitter to prevent thundering herd
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    retryable_exceptions: Tuple = (ConnectionError, TimeoutError, OSError)


@dataclass
class StreamConfig:
    """Configuration for Redis streams"""

    name: str
    max_len: int = 10000  # Maximum stream length
    consumer_group: Optional[str] = None
    consumer_name: Optional[str] = None
    block_time: int = 1000  # Block time in milliseconds
    count: int = 10  # Number of messages to read per batch
    auto_claim_min_idle: int = 300000  # Auto-claim messages idle for 5 minutes

    def __post_init__(self):
        """Set default consumer group and name if not provided"""
        if not self.consumer_group:
            self.consumer_group = f"{self.name.replace(':', '_')}_consumers"
        if not self.consumer_name:
            import os

            self.consumer_name = f"consumer_{os.getpid()}_{int(time.time())}"


@dataclass
class StreamMessage:
    """Represents a Redis stream message"""

    id: str
    fields: Dict[str, str]
    stream_name: str
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Parse timestamp from message ID"""
        if not self.timestamp and "-" in self.id:
            try:
                # Redis stream ID format: timestamp-sequence
                timestamp_ms = int(self.id.split("-")[0])
                self.timestamp = datetime.fromtimestamp(
                    timestamp_ms / 1000, tz=timezone.utc
                )
            except (ValueError, IndexError):
                self.timestamp = datetime.now(timezone.utc)

    def get_field(self, key: str, default: Any = None) -> Any:
        """Get a field value with optional type conversion"""
        value = self.fields.get(key, default)
        if value is None:
            return default

        # Try to parse JSON if it looks like JSON
        if isinstance(value, str) and value.startswith(("{", "[")):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass

        return value

    def get_event_type(self) -> str:
        """Get event type from message fields"""
        return self.fields.get("event_type", "unknown")

    def get_aggregate_id(self) -> str:
        """Get aggregate ID from message fields"""
        return self.fields.get("aggregate_id", "unknown")


class RedisStreamClient:
    """
    Redis client with connection pooling and streams support.
    Provides high-level operations for Redis Streams with retry logic.
    """

    def __init__(
        self, config: WorkerConfig, retry_config: Optional[RetryConfig] = None
    ):
        self.config = config
        self.retry_config = retry_config or RetryConfig()

        # Connection pool settings
        self.pool_settings = {
            "host": self._parse_host(),
            "port": self._parse_port(),
            "db": self._parse_db(),
            "password": self._parse_password(),
            "max_connections": 20,
            "retry_on_timeout": True,
            "health_check_interval": 30,
            "socket_keepalive": True,
        }

        self.pool: Optional[ConnectionPool] = None
        self.client: Optional[redis.Redis] = None
        self._initialized = False

        # Metrics
        self.connection_attempts = 0
        self.successful_operations = 0
        self.failed_operations = 0
        self.retry_attempts = 0

    def _parse_host(self) -> str:
        """Parse host from Redis URL"""
        try:
            # Simple parsing for redis://localhost:6379/0 format
            url = self.config.redis_url
            if "://" in url:
                url = url.split("://", 1)[1]
            if "@" in url:  # Handle password
                url = url.split("@", 1)[1]
            if "/" in url:  # Remove database part
                url = url.split("/", 1)[0]
            if ":" in url:  # Remove port
                return url.split(":", 1)[0]
            return url or "localhost"
        except:
            return "localhost"

    def _parse_port(self) -> int:
        """Parse port from Redis URL"""
        try:
            url = self.config.redis_url
            if "://" in url:
                url = url.split("://", 1)[1]
            if "@" in url:
                url = url.split("@", 1)[1]
            if "/" in url:
                url = url.split("/", 1)[0]
            if ":" in url:
                return int(url.split(":", 1)[1])
            return 6379
        except:
            return 6379

    def _parse_db(self) -> int:
        """Parse database number from Redis URL"""
        try:
            url = self.config.redis_url
            if "/" in url:
                db_part = url.split("/")[-1]
                return int(db_part) if db_part.isdigit() else 0
            return 0
        except:
            return 0

    def _parse_password(self) -> Optional[str]:
        """Parse password from Redis URL"""
        try:
            url = self.config.redis_url
            if "://" in url and "@" in url:
                auth_part = url.split("://", 1)[1].split("@", 1)[0]
                if ":" in auth_part:
                    return auth_part.split(":", 1)[1]
                return auth_part if auth_part else None
            return None
        except:
            return None

    async def initialize(self):
        """Initialize Redis connection pool and client"""
        if self._initialized:
            return

        logger.info(
            f"Initializing Redis connection pool to {self.pool_settings['host']}:{self.pool_settings['port']}"
        )

        try:
            self.pool = ConnectionPool(**self.pool_settings)
            self.client = redis.Redis(connection_pool=self.pool)

            # Test connection
            await self.client.ping()

            self._initialized = True
            logger.info("Redis connection pool initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Redis connection pool: {e}")
            raise

    async def close(self):
        """Close Redis connection pool"""
        if self.client:
            await self.client.aclose()
        if self.pool:
            await self.pool.disconnect()

        self._initialized = False
        logger.info("Redis connection pool closed")

    @asynccontextmanager
    async def get_client(self):
        """Get Redis client with automatic initialization"""
        if not self._initialized:
            await self.initialize()

        yield self.client

    async def _execute_with_retry(
        self, operation_name: str, operation, *args, **kwargs
    ):
        """Execute Redis operation with retry logic"""
        last_exception = None

        for attempt in range(self.retry_config.max_retries + 1):
            try:
                self.connection_attempts += 1

                async with self.get_client() as client:
                    result = await operation(client, *args, **kwargs)

                self.successful_operations += 1
                return result

            except self.retry_config.retryable_exceptions as e:
                last_exception = e
                self.failed_operations += 1

                if attempt == self.retry_config.max_retries:
                    logger.error(
                        f"Operation {operation_name} failed after {attempt + 1} attempts: {e}"
                    )
                    break

                # Calculate delay
                delay = self._calculate_delay(attempt)

                self.retry_attempts += 1
                logger.warning(
                    f"Operation {operation_name} failed (attempt {attempt + 1}), retrying in {delay:.2f}s: {e}"
                )

                await asyncio.sleep(delay)

            except Exception as e:
                # Non-retryable exception
                self.failed_operations += 1
                logger.error(
                    f"Operation {operation_name} failed with non-retryable error: {e}"
                )
                raise

        # All retries exhausted
        raise last_exception

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt"""
        if self.retry_config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = self.retry_config.base_delay * (
                self.retry_config.backoff_multiplier**attempt
            )
        elif self.retry_config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = self.retry_config.base_delay * (attempt + 1)
        else:  # FIXED_DELAY
            delay = self.retry_config.base_delay

        # Apply maximum delay
        delay = min(delay, self.retry_config.max_delay)

        # Add jitter
        if self.retry_config.jitter:
            jitter_range = delay * 0.1  # 10% jitter
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0.0, delay)

    # Stream Operations

    async def create_consumer_group(
        self, stream_config: StreamConfig, mkstream: bool = True
    ):
        """Create consumer group for a stream"""

        async def _create_group(client: redis.Redis):
            try:
                await client.xgroup_create(
                    stream_config.name,
                    stream_config.consumer_group,
                    id="0",
                    mkstream=mkstream,
                )
                logger.info(
                    f"Created consumer group {stream_config.consumer_group} for stream {stream_config.name}"
                )
                return True
            except ResponseError as e:
                if "BUSYGROUP" in str(e):
                    logger.debug(
                        f"Consumer group {stream_config.consumer_group} already exists"
                    )
                    return True
                raise

        return await self._execute_with_retry(
            f"create_consumer_group_{stream_config.name}", _create_group
        )

    async def add_to_stream(
        self,
        stream_name: str,
        fields: Dict[str, str],
        max_len: Optional[int] = None,
        message_id: str = "*",
    ) -> str:
        """Add message to Redis stream"""

        async def _add_message(client: redis.Redis):
            return await client.xadd(stream_name, fields, id=message_id, maxlen=max_len)

        result = await self._execute_with_retry(
            f"add_to_stream_{stream_name}", _add_message
        )

        logger.debug(f"Added message {result} to stream {stream_name}")
        return result

    async def read_from_stream(
        self, stream_config: StreamConfig, from_id: str = ">"
    ) -> List[StreamMessage]:
        """Read messages from stream using consumer group"""

        async def _read_messages(client: redis.Redis):
            # Ensure consumer group exists
            await self.create_consumer_group(stream_config)

            # Read messages
            result = await client.xreadgroup(
                stream_config.consumer_group,
                stream_config.consumer_name,
                {stream_config.name: from_id},
                count=stream_config.count,
                block=stream_config.block_time,
            )

            messages = []
            for stream_name, stream_messages in result:
                for msg_id, fields in stream_messages:
                    # Convert bytes to strings
                    string_fields = {
                        k.decode() if isinstance(k, bytes) else k: v.decode()
                        if isinstance(v, bytes)
                        else v
                        for k, v in fields.items()
                    }

                    message = StreamMessage(
                        id=msg_id.decode() if isinstance(msg_id, bytes) else msg_id,
                        fields=string_fields,
                        stream_name=stream_name.decode()
                        if isinstance(stream_name, bytes)
                        else stream_name,
                    )
                    messages.append(message)

            return messages

        return await self._execute_with_retry(
            f"read_from_stream_{stream_config.name}", _read_messages
        )

    async def acknowledge_message(
        self, stream_name: str, consumer_group: str, message_id: str
    ):
        """Acknowledge message processing"""

        async def _ack_message(client: redis.Redis):
            return await client.xack(stream_name, consumer_group, message_id)

        return await self._execute_with_retry(
            f"ack_message_{stream_name}_{message_id}", _ack_message
        )

    async def get_stream_info(self, stream_name: str) -> Dict[str, Any]:
        """Get stream information"""

        async def _get_info(client: redis.Redis):
            return await client.xinfo_stream(stream_name)

        try:
            return await self._execute_with_retry(
                f"get_stream_info_{stream_name}", _get_info
            )
        except ResponseError:
            # Stream doesn't exist
            return {}

    async def get_consumer_group_info(self, stream_name: str) -> List[Dict[str, Any]]:
        """Get consumer group information"""

        async def _get_group_info(client: redis.Redis):
            return await client.xinfo_groups(stream_name)

        try:
            return await self._execute_with_retry(
                f"get_consumer_group_info_{stream_name}", _get_group_info
            )
        except ResponseError:
            # Stream or groups don't exist
            return []

    async def claim_pending_messages(
        self, stream_config: StreamConfig, min_idle_time: Optional[int] = None
    ) -> List[StreamMessage]:
        """Claim pending messages that have been idle too long"""
        min_idle = min_idle_time or stream_config.auto_claim_min_idle

        async def _claim_messages(client: redis.Redis):
            # Auto-claim messages
            result = await client.xautoclaim(
                stream_config.name,
                stream_config.consumer_group,
                stream_config.consumer_name,
                min_idle_time=min_idle,
                start_id="0-0",
                count=stream_config.count,
            )

            # result format: [next_start_id, claimed_messages, deleted_message_ids]
            next_start_id, claimed_messages, _ = result

            messages = []
            for msg_id, fields in claimed_messages:
                string_fields = {
                    k.decode() if isinstance(k, bytes) else k: v.decode()
                    if isinstance(v, bytes)
                    else v
                    for k, v in fields.items()
                }

                message = StreamMessage(
                    id=msg_id.decode() if isinstance(msg_id, bytes) else msg_id,
                    fields=string_fields,
                    stream_name=stream_config.name,
                )
                messages.append(message)

            return messages

        return await self._execute_with_retry(
            f"claim_pending_{stream_config.name}", _claim_messages
        )

    async def delete_consumer(
        self, stream_name: str, consumer_group: str, consumer_name: str
    ):
        """Delete a consumer from consumer group"""

        async def _delete_consumer(client: redis.Redis):
            return await client.xgroup_delconsumer(
                stream_name, consumer_group, consumer_name
            )

        return await self._execute_with_retry(
            f"delete_consumer_{stream_name}_{consumer_name}", _delete_consumer
        )

    async def get_metrics(self) -> Dict[str, Any]:
        """Get client metrics"""
        return {
            "connection_attempts": self.connection_attempts,
            "successful_operations": self.successful_operations,
            "failed_operations": self.failed_operations,
            "retry_attempts": self.retry_attempts,
            "success_rate": (
                self.successful_operations / max(1, self.connection_attempts) * 100
            ),
            "initialized": self._initialized,
            "pool_settings": self.pool_settings,
        }


# Global client instance
_redis_client: Optional[RedisStreamClient] = None


async def get_redis_client() -> RedisStreamClient:
    """Get or create Redis stream client"""
    global _redis_client

    if not _redis_client:
        config = WorkerConfig()
        _redis_client = RedisStreamClient(config)

    return _redis_client
