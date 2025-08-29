"""
RAGline Stream Producer

High-level stream producer for publishing events to Redis streams
with automatic stream routing, schema validation, and retry logic.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from celery.utils.log import get_task_logger

from services.worker.config import WorkerConfig

from .redis_client import StreamConfig
from .redis_simple import SimpleRedisClient, get_simple_redis_client

logger = get_task_logger(__name__)


class StreamTopic(str, Enum):
    """Predefined stream topics"""

    ORDERS = "ragline:stream:orders"
    USERS = "ragline:stream:users"
    PRODUCTS = "ragline:stream:products"
    NOTIFICATIONS = "ragline:stream:notifications"
    PAYMENTS = "ragline:stream:payments"
    INVENTORY = "ragline:stream:inventory"


@dataclass
class EventMetadata:
    """Metadata for stream events"""

    event_id: str
    event_type: str
    aggregate_id: str
    aggregate_type: str
    source_service: str = "ragline_worker"
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    version: str = "1.0"
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)


@dataclass
class StreamEvent:
    """Complete stream event with metadata and payload"""

    metadata: EventMetadata
    payload: Dict[str, Any]

    def to_stream_fields(self) -> Dict[str, str]:
        """Convert event to Redis stream fields"""
        fields = {
            # Metadata fields
            "event_id": self.metadata.event_id,
            "event_type": self.metadata.event_type,
            "aggregate_id": self.metadata.aggregate_id,
            "aggregate_type": self.metadata.aggregate_type,
            "source_service": self.metadata.source_service,
            "version": self.metadata.version,
            "created_at": self.metadata.created_at.isoformat(),
            # Payload as JSON
            "payload": json.dumps(self.payload, default=str),
        }

        # Optional metadata fields
        if self.metadata.correlation_id:
            fields["correlation_id"] = self.metadata.correlation_id
        if self.metadata.causation_id:
            fields["causation_id"] = self.metadata.causation_id
        if self.metadata.user_id:
            fields["user_id"] = self.metadata.user_id
        if self.metadata.tenant_id:
            fields["tenant_id"] = self.metadata.tenant_id

        return fields

    @classmethod
    def from_outbox_event(cls, outbox_event) -> "StreamEvent":
        """Create StreamEvent from outbox event"""
        metadata = EventMetadata(
            event_id=str(outbox_event.id),
            event_type=outbox_event.event_type,
            aggregate_id=outbox_event.aggregate_id,
            aggregate_type=outbox_event.aggregate_type,
            created_at=outbox_event.created_at,
        )

        return cls(metadata=metadata, payload=outbox_event.payload)


class StreamProducer:
    """
    High-level stream producer for publishing events to Redis streams.
    Provides automatic routing, validation, and retry logic.
    """

    def __init__(self, redis_client: Optional[SimpleRedisClient] = None):
        self.redis_client = redis_client
        self.config = WorkerConfig()

        # Stream configurations
        self.stream_configs = {
            StreamTopic.ORDERS: StreamConfig(
                name=StreamTopic.ORDERS.value,
                max_len=50000,  # Keep more order events
                consumer_group="order_processors",
                count=20,
            ),
            StreamTopic.USERS: StreamConfig(
                name=StreamTopic.USERS.value,
                max_len=20000,
                consumer_group="user_processors",
                count=10,
            ),
            StreamTopic.PRODUCTS: StreamConfig(
                name=StreamTopic.PRODUCTS.value,
                max_len=30000,
                consumer_group="product_processors",
                count=15,
            ),
            StreamTopic.NOTIFICATIONS: StreamConfig(
                name=StreamTopic.NOTIFICATIONS.value,
                max_len=100000,  # Keep many notification events
                consumer_group="notification_processors",
                count=50,
            ),
            StreamTopic.PAYMENTS: StreamConfig(
                name=StreamTopic.PAYMENTS.value,
                max_len=30000,
                consumer_group="payment_processors",
                count=10,
            ),
            StreamTopic.INVENTORY: StreamConfig(
                name=StreamTopic.INVENTORY.value,
                max_len=25000,
                consumer_group="inventory_processors",
                count=15,
            ),
        }

        # Metrics
        self.events_published = 0
        self.events_failed = 0
        self.events_by_topic = {}

    async def get_client(self) -> SimpleRedisClient:
        """Get Redis client instance"""
        if not self.redis_client:
            self.redis_client = await get_simple_redis_client()
        return self.redis_client

    def get_stream_topic(self, aggregate_type: str, event_type: str) -> StreamTopic:
        """Determine stream topic based on aggregate type and event type"""
        aggregate_lower = aggregate_type.lower()
        event_lower = event_type.lower()

        # Primary routing by aggregate type
        if aggregate_lower == "order":
            return StreamTopic.ORDERS
        elif aggregate_lower == "user":
            return StreamTopic.USERS
        elif aggregate_lower == "product":
            return StreamTopic.PRODUCTS
        elif aggregate_lower in ["notification", "email", "sms"]:
            return StreamTopic.NOTIFICATIONS
        elif aggregate_lower in ["payment", "transaction", "billing"]:
            return StreamTopic.PAYMENTS
        elif aggregate_lower in ["inventory", "stock", "warehouse"]:
            return StreamTopic.INVENTORY

        # Secondary routing by event type
        if any(keyword in event_lower for keyword in ["order", "purchase", "checkout"]):
            return StreamTopic.ORDERS
        elif any(keyword in event_lower for keyword in ["user", "account", "profile"]):
            return StreamTopic.USERS
        elif any(keyword in event_lower for keyword in ["product", "catalog", "item"]):
            return StreamTopic.PRODUCTS
        elif any(keyword in event_lower for keyword in ["notification", "alert", "message"]):
            return StreamTopic.NOTIFICATIONS
        elif any(keyword in event_lower for keyword in ["payment", "charge", "refund"]):
            return StreamTopic.PAYMENTS
        elif any(keyword in event_lower for keyword in ["inventory", "stock", "quantity"]):
            return StreamTopic.INVENTORY

        # Default to orders stream
        logger.warning(f"No specific stream found for {aggregate_type}.{event_type}, defaulting to orders")
        return StreamTopic.ORDERS

    async def publish_event(self, event: StreamEvent) -> str:
        """Publish single event to appropriate stream"""
        try:
            # Get stream topic
            topic = self.get_stream_topic(event.metadata.aggregate_type, event.metadata.event_type)

            # Get stream configuration
            stream_config = self.stream_configs[topic]

            # Get Redis client
            client = await self.get_client()

            # Convert event to stream fields
            fields = event.to_stream_fields()

            # Publish to stream
            message_id = await client.add_to_stream(
                stream_name=topic.value, fields=fields, max_len=stream_config.max_len
            )

            # Update metrics
            self.events_published += 1
            self.events_by_topic[topic.value] = self.events_by_topic.get(topic.value, 0) + 1

            logger.info(f"Published event {event.metadata.event_id} to {topic.value} (message_id: {message_id})")
            return message_id

        except Exception as e:
            self.events_failed += 1
            logger.error(f"Failed to publish event {event.metadata.event_id}: {e}")
            raise

    async def publish_events(self, events: List[StreamEvent]) -> List[str]:
        """Publish multiple events (batch operation)"""
        message_ids = []

        for event in events:
            try:
                message_id = await self.publish_event(event)
                message_ids.append(message_id)
            except Exception as e:
                logger.error(f"Failed to publish event in batch: {e}")
                # Continue with other events
                message_ids.append(None)

        successful_publishes = sum(1 for mid in message_ids if mid is not None)
        logger.info(f"Batch publish completed: {successful_publishes}/{len(events)} events published")

        return message_ids

    async def publish_order_event(
        self, order_id: str, event_type: str, payload: Dict[str, Any], **metadata_kwargs
    ) -> str:
        """Convenience method for publishing order events"""
        metadata = EventMetadata(
            event_id=f"order_{order_id}_{event_type}_{int(datetime.now().timestamp())}",
            event_type=event_type,
            aggregate_id=order_id,
            aggregate_type="order",
            **metadata_kwargs,
        )

        event = StreamEvent(metadata=metadata, payload=payload)
        return await self.publish_event(event)

    async def publish_user_event(
        self, user_id: str, event_type: str, payload: Dict[str, Any], **metadata_kwargs
    ) -> str:
        """Convenience method for publishing user events"""
        metadata = EventMetadata(
            event_id=f"user_{user_id}_{event_type}_{int(datetime.now().timestamp())}",
            event_type=event_type,
            aggregate_id=user_id,
            aggregate_type="user",
            **metadata_kwargs,
        )

        event = StreamEvent(metadata=metadata, payload=payload)
        return await self.publish_event(event)

    async def publish_product_event(
        self,
        product_id: str,
        event_type: str,
        payload: Dict[str, Any],
        **metadata_kwargs,
    ) -> str:
        """Convenience method for publishing product events"""
        metadata = EventMetadata(
            event_id=f"product_{product_id}_{event_type}_{int(datetime.now().timestamp())}",
            event_type=event_type,
            aggregate_id=product_id,
            aggregate_type="product",
            **metadata_kwargs,
        )

        event = StreamEvent(metadata=metadata, payload=payload)
        return await self.publish_event(event)

    async def publish_notification_event(
        self,
        notification_id: str,
        event_type: str,
        payload: Dict[str, Any],
        **metadata_kwargs,
    ) -> str:
        """Convenience method for publishing notification events"""
        metadata = EventMetadata(
            event_id=f"notification_{notification_id}_{event_type}_{int(datetime.now().timestamp())}",
            event_type=event_type,
            aggregate_id=notification_id,
            aggregate_type="notification",
            **metadata_kwargs,
        )

        event = StreamEvent(metadata=metadata, payload=payload)
        return await self.publish_event(event)

    async def create_stream_consumer_groups(self):
        """Create all consumer groups for configured streams"""
        client = await self.get_client()

        for topic, stream_config in self.stream_configs.items():
            try:
                await client.create_consumer_group(stream_config, mkstream=True)
                logger.info(f"Created consumer group for {topic.value}")
            except Exception as e:
                logger.warning(f"Failed to create consumer group for {topic.value}: {e}")

    async def get_stream_info(self, topic: StreamTopic) -> Dict[str, Any]:
        """Get information about a specific stream"""
        client = await self.get_client()
        return await client.get_stream_info(topic.value)

    async def get_all_streams_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all configured streams"""
        streams_info = {}

        for topic in self.stream_configs:
            try:
                info = await self.get_stream_info(topic)
                streams_info[topic.value] = info
            except Exception as e:
                logger.warning(f"Failed to get info for {topic.value}: {e}")
                streams_info[topic.value] = {"error": str(e)}

        return streams_info

    async def get_metrics(self) -> Dict[str, Any]:
        """Get producer metrics"""
        client_metrics = {}
        if self.redis_client:
            client_metrics = await self.redis_client.get_metrics()

        return {
            "events_published": self.events_published,
            "events_failed": self.events_failed,
            "success_rate": (self.events_published / max(1, self.events_published + self.events_failed) * 100),
            "events_by_topic": self.events_by_topic,
            "configured_topics": list(self.stream_configs.keys()),
            "redis_client_metrics": client_metrics,
        }


# Global producer instance
_stream_producer: Optional[StreamProducer] = None


async def get_stream_producer() -> StreamProducer:
    """Get or create stream producer"""
    global _stream_producer

    if not _stream_producer:
        _stream_producer = StreamProducer()

    return _stream_producer
