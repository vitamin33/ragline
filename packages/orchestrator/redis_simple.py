"""
Simplified Redis Client for Streams

Simplified Redis client that works reliably with async operations
without complex connection pooling configurations.
"""

from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from celery.utils.log import get_task_logger
from redis.exceptions import ResponseError

from services.worker.config import WorkerConfig

logger = get_task_logger(__name__)


class SimpleRedisClient:
    """
    Simplified Redis client for streams operations.
    Reliable async operations without complex pooling.
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.client: Optional[redis.Redis] = None
        self._initialized = False

        # Metrics
        self.operations_count = 0
        self.errors_count = 0

    async def initialize(self):
        """Initialize Redis client"""
        if self._initialized:
            return

        try:
            # Simple client creation
            self.client = redis.from_url(
                self.config.redis_url, retry_on_timeout=True, health_check_interval=30
            )

            # Test connection
            await self.client.ping()

            self._initialized = True
            logger.info("Simple Redis client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Redis client: {e}")
            raise

    async def close(self):
        """Close Redis client"""
        if self.client:
            await self.client.aclose()

        self._initialized = False
        logger.info("Simple Redis client closed")

    async def ensure_initialized(self):
        """Ensure client is initialized"""
        if not self._initialized:
            await self.initialize()

    async def add_to_stream(
        self,
        stream_name: str,
        fields: Dict[str, str],
        max_len: Optional[int] = None,
        message_id: str = "*",
    ) -> str:
        """Add message to Redis stream"""
        await self.ensure_initialized()

        try:
            self.operations_count += 1

            result = await self.client.xadd(
                stream_name, fields, id=message_id, maxlen=max_len
            )

            logger.debug(f"Added message {result} to stream {stream_name}")
            return result

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Failed to add to stream {stream_name}: {e}")
            raise

    async def read_from_stream(
        self,
        stream_name: str,
        consumer_group: str,
        consumer_name: str,
        from_id: str = ">",
        count: int = 10,
        block: int = 1000,
    ) -> List[Dict]:
        """Read from stream with consumer group"""
        await self.ensure_initialized()

        try:
            self.operations_count += 1

            # Ensure consumer group exists
            try:
                await self.client.xgroup_create(
                    stream_name, consumer_group, id="0", mkstream=True
                )
            except ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

            # Read messages
            result = await self.client.xreadgroup(
                consumer_group,
                consumer_name,
                {stream_name: from_id},
                count=count,
                block=block,
            )

            messages = []
            for stream, msgs in result:
                for msg_id, fields in msgs:
                    # Convert bytes to strings
                    string_fields = {
                        k.decode() if isinstance(k, bytes) else k: v.decode()
                        if isinstance(v, bytes)
                        else v
                        for k, v in fields.items()
                    }

                    messages.append(
                        {
                            "id": msg_id.decode()
                            if isinstance(msg_id, bytes)
                            else msg_id,
                            "fields": string_fields,
                            "stream": stream.decode()
                            if isinstance(stream, bytes)
                            else stream,
                        }
                    )

            return messages

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Failed to read from stream {stream_name}: {e}")
            raise

    async def acknowledge_message(
        self, stream_name: str, consumer_group: str, message_id: str
    ):
        """Acknowledge message"""
        await self.ensure_initialized()

        try:
            self.operations_count += 1
            return await self.client.xack(stream_name, consumer_group, message_id)
        except Exception as e:
            self.errors_count += 1
            logger.error(f"Failed to acknowledge message {message_id}: {e}")
            raise

    async def get_stream_info(self, stream_name: str) -> Dict[str, Any]:
        """Get stream information"""
        await self.ensure_initialized()

        try:
            self.operations_count += 1
            return await self.client.xinfo_stream(stream_name)
        except ResponseError:
            return {}
        except Exception as e:
            self.errors_count += 1
            logger.error(f"Failed to get stream info {stream_name}: {e}")
            return {}

    async def get_metrics(self) -> Dict[str, Any]:
        """Get client metrics"""
        return {
            "operations_count": self.operations_count,
            "errors_count": self.errors_count,
            "success_rate": (
                (self.operations_count - self.errors_count)
                / max(1, self.operations_count)
                * 100
            ),
            "initialized": self._initialized,
        }


# Global instance
_simple_redis_client: Optional[SimpleRedisClient] = None


async def get_simple_redis_client() -> SimpleRedisClient:
    """Get or create simple Redis client"""
    global _simple_redis_client

    if not _simple_redis_client:
        config = WorkerConfig()
        _simple_redis_client = SimpleRedisClient(config)

    return _simple_redis_client
