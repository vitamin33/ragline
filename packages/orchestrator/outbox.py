"""
RAGline Outbox Consumer

Implements the Outbox Pattern for reliable event processing.
Polls the outbox table every 100ms and processes unprocessed events.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import jsonschema
import redis.asyncio as redis
from celery.utils.log import get_task_logger
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from packages.db.database import AsyncSessionLocal, engine
from packages.db.models import Outbox
from services.worker.config import WorkerConfig

from .stream_producer import StreamEvent, get_stream_producer

logger = get_task_logger(__name__)


# Load event schemas
def _load_event_schemas() -> Dict[str, Dict[str, Any]]:
    """Load event schemas for validation"""
    import os

    schemas = {}

    # Load order_v1.json schema
    try:
        schema_path = os.path.join(os.path.dirname(__file__), "../../contracts/events/order_v1.json")
        with open(schema_path, "r") as f:
            schemas["order_v1"] = json.load(f)
        logger.info("Loaded order_v1 event schema")
    except Exception as e:
        logger.warning(f"Failed to load order_v1 schema: {e}")

    return schemas


# Global event schemas
EVENT_SCHEMAS = _load_event_schemas()


@dataclass
class OutboxEvent:
    """Represents an outbox event to be processed"""

    id: int
    aggregate_id: str
    aggregate_type: str
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime
    retry_count: int


class OutboxProcessingError(Exception):
    """Raised when outbox event processing fails"""

    pass


class OutboxConsumer:
    """
    Outbox pattern consumer that polls the database for unprocessed events
    and publishes them to Redis Streams with retry logic and error handling.
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.redis: Optional[redis.Redis] = None
        self.engine: Optional[AsyncEngine] = None
        self.is_running = False
        self.poll_interval = config.outbox_poll_interval
        self.batch_size = config.outbox_batch_size

        # Metrics tracking
        self.processed_count = 0
        self.error_count = 0
        self.last_poll_time: Optional[float] = None
        self.processing_duration_ms = 0.0

    async def start(self):
        """Start the outbox consumer"""
        if self.is_running:
            logger.warning("Outbox consumer is already running")
            return

        logger.info(f"Starting outbox consumer (poll interval: {self.poll_interval}s, batch size: {self.batch_size})")

        # Initialize connections
        await self._init_connections()

        self.is_running = True

        try:
            await self._consume_loop()
        except Exception as e:
            logger.error(f"Outbox consumer failed: {e}", exc_info=True)
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the outbox consumer and cleanup connections"""
        if not self.is_running:
            return

        logger.info("Stopping outbox consumer...")
        self.is_running = False

        if self.redis:
            await self.redis.close()

        if self.engine:
            await self.engine.dispose()

        logger.info("Outbox consumer stopped")

    async def _init_connections(self):
        """Initialize database and Redis connections"""
        # Initialize Redis connection
        self.redis = redis.from_url(self.config.redis_url)
        await self.redis.ping()
        logger.info("Redis connection established")

        # Database engine is handled by the get_async_session dependency
        logger.info("Database connection ready")

    async def _consume_loop(self):
        """Main consumption loop that polls every 100ms"""
        while self.is_running:
            start_time = time.time()

            try:
                events = await self._fetch_unprocessed_events()

                if events:
                    logger.debug(f"Found {len(events)} unprocessed events")
                    await self._process_events(events)

                self.last_poll_time = time.time()
                self.processing_duration_ms = (self.last_poll_time - start_time) * 1000

            except Exception as e:
                self.error_count += 1
                logger.error(f"Error in outbox consume loop: {e}", exc_info=True)

            # Wait for next poll interval
            await asyncio.sleep(self.poll_interval)

    async def _fetch_unprocessed_events(self) -> List[OutboxEvent]:
        """Fetch unprocessed events from the outbox table"""
        async with AsyncSessionLocal() as session:
            try:
                # Fetch unprocessed events ordered by created_at
                query = select(Outbox).where(not Outbox.processed).order_by(Outbox.created_at).limit(self.batch_size)

                result = await session.execute(query)
                outbox_records = result.scalars().all()

                # Convert to OutboxEvent objects
                events = []
                for record in outbox_records:
                    event = OutboxEvent(
                        id=record.id,
                        aggregate_id=record.aggregate_id,
                        aggregate_type=record.aggregate_type,
                        event_type=record.event_type,
                        payload=record.payload,
                        created_at=record.created_at,
                        retry_count=record.retry_count,
                    )
                    events.append(event)

                return events
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to fetch unprocessed events: {e}")
                raise

    async def _process_events(self, events: List[OutboxEvent]):
        """Process a batch of outbox events"""
        for event in events:
            try:
                await self._process_single_event(event)
                await self._mark_event_processed(event.id)
                self.processed_count += 1

                logger.debug(f"Successfully processed event {event.id} ({event.event_type})")

            except Exception as e:
                self.error_count += 1
                logger.error(f"Failed to process event {event.id}: {e}")

                # Update retry count
                await self._increment_retry_count(event.id)

                # If max retries reached, consider moving to DLQ
                if event.retry_count >= self.config.dlq_max_retries:
                    await self._handle_max_retries(event)

    async def _process_single_event(self, event: OutboxEvent):
        """Process a single outbox event by publishing to Redis Stream"""
        try:
            # Validate event schema before publishing
            await self._validate_event_schema(event)

            # Get stream producer
            producer = await get_stream_producer()

            # Create stream event from outbox event
            stream_event = StreamEvent.from_outbox_event(event)

            # Add retry count to payload for tracking
            stream_event.payload["_retry_count"] = event.retry_count

            # Publish event using the stream producer
            message_id = await producer.publish_event(stream_event)

            logger.debug(f"Published event {event.id} with message ID {message_id}")

        except Exception as e:
            raise OutboxProcessingError(f"Failed to publish to Redis Stream: {e}")

    async def _validate_event_schema(self, event: OutboxEvent):
        """Validate event payload against schema"""
        try:
            # Determine schema key based on aggregate type and event type
            schema_key = None
            if event.aggregate_type.lower() == "order":
                schema_key = "order_v1"

            if schema_key and schema_key in EVENT_SCHEMAS:
                schema = EVENT_SCHEMAS[schema_key]
                # Validate the payload against the schema
                jsonschema.validate(event.payload, schema)
                logger.debug(f"Event {event.id} payload validated against {schema_key} schema")
            else:
                logger.warning(
                    f"No schema found for event {event.id} (type: {event.aggregate_type}.{event.event_type})"
                )

        except jsonschema.ValidationError as e:
            logger.error(f"Schema validation failed for event {event.id}: {e}")
            raise OutboxProcessingError(f"Schema validation failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during schema validation for event {event.id}: {e}")
            raise OutboxProcessingError(f"Schema validation error: {e}")

    async def _mark_event_processed(self, event_id: int):
        """Mark an event as processed in the database"""
        async with AsyncSessionLocal() as session:
            try:
                query = (
                    update(Outbox)
                    .where(Outbox.id == event_id)
                    .values(processed=True, processed_at=datetime.now(timezone.utc))
                )

                await session.execute(query)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to mark event {event_id} as processed: {e}")
                raise

    async def _increment_retry_count(self, event_id: int):
        """Increment retry count for a failed event"""
        async with AsyncSessionLocal() as session:
            try:
                query = update(Outbox).where(Outbox.id == event_id).values(retry_count=Outbox.retry_count + 1)

                await session.execute(query)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to increment retry count for event {event_id}: {e}")
                raise

    async def _handle_max_retries(self, event: OutboxEvent):
        """Handle events that have exceeded max retries"""
        if self.config.dlq_enabled:
            await self._move_to_dlq(event)
            logger.warning(f"Event {event.id} moved to DLQ after {event.retry_count} retries")
        else:
            # Just mark as processed to prevent infinite retries
            await self._mark_event_processed(event.id)
            logger.error(
                f"Event {event.id} marked as processed after {event.retry_count} failed retries (DLQ disabled)"
            )

    async def _move_to_dlq(self, event: OutboxEvent):
        """Move failed event to Dead Letter Queue using DLQ Manager"""
        try:
            from .dlq_manager import get_dlq_manager

            dlq_event = {
                "event_id": str(event.id),
                "aggregate_id": event.aggregate_id,
                "aggregate_type": event.aggregate_type,
                "event_type": event.event_type,
                "payload": json.dumps(event.payload) if isinstance(event.payload, dict) else str(event.payload),
                "created_at": event.created_at.isoformat(),
                "retry_count": str(event.retry_count),
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "reason": "max_retries_exceeded",
            }

            # Use DLQ Manager for enhanced processing
            dlq_manager = await get_dlq_manager()
            await dlq_manager.add_event(dlq_event)

            # Mark original event as processed
            await self._mark_event_processed(event.id)

        except Exception as e:
            logger.error(f"Failed to move event {event.id} to DLQ via manager, falling back to direct Redis: {e}")

            # Fallback to direct Redis if DLQ manager fails
            dlq_key = f"ragline:dlq:{event.aggregate_type}"
            dlq_event = {
                "event_id": str(event.id),
                "aggregate_id": event.aggregate_id,
                "aggregate_type": event.aggregate_type,
                "event_type": event.event_type,
                "payload": json.dumps(event.payload) if isinstance(event.payload, dict) else str(event.payload),
                "created_at": event.created_at.isoformat(),
                "retry_count": str(event.retry_count),
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "reason": "max_retries_exceeded",
            }

            await self.redis.lpush(dlq_key, json.dumps(dlq_event))
            await self._mark_event_processed(event.id)

    async def get_metrics(self) -> Dict[str, Any]:
        """Get consumer metrics"""
        return {
            "is_running": self.is_running,
            "processed_count": self.processed_count,
            "error_count": self.error_count,
            "last_poll_time": self.last_poll_time,
            "processing_duration_ms": self.processing_duration_ms,
            "poll_interval_ms": self.poll_interval * 1000,
            "batch_size": self.batch_size,
        }


class OutboxReprocessor:
    """Utility class for reprocessing DLQ events"""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.redis: Optional[redis.Redis] = None

    async def reprocess_dlq_events(self, aggregate_type: str, limit: int = 10) -> int:
        """Reprocess events from the Dead Letter Queue"""
        if not self.redis:
            self.redis = redis.from_url(self.config.redis_url)

        dlq_key = f"ragline:dlq:{aggregate_type}"
        reprocessed = 0

        for _ in range(limit):
            # Pop event from DLQ
            event_json = await self.redis.rpop(dlq_key)
            if not event_json:
                break

            try:
                event_data = json.loads(event_json)

                # Reset event to unprocessed state in database
                async with AsyncSessionLocal() as session:
                    try:
                        query = (
                            update(Outbox)
                            .where(Outbox.id == int(event_data["event_id"]))
                            .values(
                                processed=False,
                                processed_at=None,
                                retry_count=0,  # Reset retry count
                            )
                        )

                        await session.execute(query)
                        await session.commit()
                    except Exception as e:
                        await session.rollback()
                        logger.error(f"Failed to reset event {event_data['event_id']}: {e}")
                        raise

                reprocessed += 1
                logger.info(f"Requeued event {event_data['event_id']} for processing")

            except Exception as e:
                logger.error(f"Failed to reprocess DLQ event: {e}")
                # Put it back in DLQ
                await self.redis.lpush(dlq_key, event_json)

        return reprocessed


# Convenience functions for Celery tasks
_consumer_instance: Optional[OutboxConsumer] = None


async def get_outbox_consumer() -> OutboxConsumer:
    """Get or create outbox consumer instance"""
    global _consumer_instance

    if not _consumer_instance:
        config = WorkerConfig()
        _consumer_instance = OutboxConsumer(config)

    return _consumer_instance
