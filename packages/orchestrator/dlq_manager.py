"""
RAGline Dead Letter Queue Manager

Comprehensive DLQ management system for handling failed events,
retry logic with exponential backoff, monitoring, and manual intervention.
"""

import asyncio
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from celery.utils.log import get_task_logger
from sqlalchemy import select, update

from packages.db.database import AsyncSessionLocal
from packages.db.models import Outbox
from services.worker.config import WorkerConfig

logger = get_task_logger(__name__)


class DLQEventStatus(str, Enum):
    """DLQ event processing status"""

    PENDING = "pending"  # Ready for reprocessing
    PROCESSING = "processing"  # Currently being reprocessed
    FAILED = "failed"  # Failed reprocessing
    EXPIRED = "expired"  # Too old to reprocess
    MANUAL = "manual"  # Requires manual intervention


@dataclass
class DLQEvent:
    """Dead Letter Queue event representation"""

    event_id: str
    aggregate_id: str
    aggregate_type: str
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime
    failed_at: datetime
    retry_count: int
    failure_reason: str
    last_attempt: Optional[datetime] = None
    status: DLQEventStatus = DLQEventStatus.PENDING

    @classmethod
    def from_redis_data(cls, data: Dict[str, Any]) -> "DLQEvent":
        """Create DLQEvent from Redis stored data"""
        payload_data = data.get("payload", "{}")
        if isinstance(payload_data, str):
            payload_data = json.loads(payload_data)

        return cls(
            event_id=data["event_id"],
            aggregate_id=data["aggregate_id"],
            aggregate_type=data["aggregate_type"],
            event_type=data["event_type"],
            payload=payload_data,
            created_at=datetime.fromisoformat(data["created_at"]),
            failed_at=datetime.fromisoformat(data["failed_at"]),
            retry_count=int(data["retry_count"]),
            failure_reason=data.get("reason", "unknown"),
            last_attempt=datetime.fromisoformat(data["last_attempt"]) if data.get("last_attempt") else None,
            status=DLQEventStatus(data.get("status", DLQEventStatus.PENDING.value)),
        )

    def to_redis_data(self) -> Dict[str, str]:
        """Convert to Redis storable format"""
        return {
            "event_id": self.event_id,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "event_type": self.event_type,
            "payload": json.dumps(self.payload),
            "created_at": self.created_at.isoformat(),
            "failed_at": self.failed_at.isoformat(),
            "retry_count": str(self.retry_count),
            "reason": self.failure_reason,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else "",
            "status": self.status.value,
        }


class DLQAlertManager:
    """Handles alerting for DLQ events"""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.alert_thresholds = {
            "high_volume": 100,  # Alert if DLQ has more than 100 events
            "age_hours": 24,  # Alert if events older than 24 hours
            "failure_rate": 0.1,  # Alert if 10% of events end up in DLQ
        }

    async def check_alerts(self, dlq_stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check for alert conditions and return list of alerts"""
        alerts = []

        # High volume alert
        total_events = dlq_stats.get("total_events", 0)
        if total_events > self.alert_thresholds["high_volume"]:
            alerts.append(
                {
                    "type": "high_volume",
                    "severity": "warning",
                    "message": f"DLQ has {total_events} events (threshold: {self.alert_thresholds['high_volume']})",
                    "count": total_events,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Old events alert
        oldest_event_hours = dlq_stats.get("oldest_event_hours", 0)
        if oldest_event_hours > self.alert_thresholds["age_hours"]:
            alerts.append(
                {
                    "type": "old_events",
                    "severity": "error",
                    "message": f"Events in DLQ for {oldest_event_hours:.1f} hours (threshold: {self.alert_thresholds['age_hours']})",
                    "age_hours": oldest_event_hours,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Failure rate alert
        failure_rate = dlq_stats.get("failure_rate", 0)
        if failure_rate > self.alert_thresholds["failure_rate"]:
            alerts.append(
                {
                    "type": "high_failure_rate",
                    "severity": "critical",
                    "message": f"High failure rate: {failure_rate:.1%} (threshold: {self.alert_thresholds['failure_rate']:.1%})",
                    "failure_rate": failure_rate,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        return alerts


class DLQManager:
    """
    Comprehensive Dead Letter Queue Manager

    Features:
    - Exponential backoff retry logic
    - Event aging and expiration
    - Manual intervention support
    - Comprehensive monitoring and alerting
    - Batch reprocessing
    """

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.redis: Optional[redis.Redis] = None
        self.alert_manager = DLQAlertManager(config)

        # Retry configuration
        self.initial_retry_delay = 60  # Start with 1 minute
        self.max_retry_delay = 3600  # Max 1 hour
        self.retry_multiplier = 2  # Double each time
        self.max_reprocess_attempts = 5  # Max attempts to reprocess from DLQ
        self.event_expiry_days = 7  # Events expire after 7 days

        # Metrics
        self.reprocessed_count = 0
        self.failed_reprocess_count = 0
        self.expired_count = 0

        # Prometheus metrics integration
        try:
            from .metrics import get_metrics

            self.prometheus_metrics = get_metrics() if config.metrics_enabled else None
        except ImportError:
            self.prometheus_metrics = None
            logger.warning("Prometheus metrics not available")

        logger.info(f"DLQ Manager initialized with {self.max_reprocess_attempts} max attempts")

    async def _get_redis(self) -> redis.Redis:
        """Get Redis connection"""
        if not self.redis:
            self.redis = redis.from_url(self.config.redis_url)
        return self.redis

    def _get_dlq_key(self, aggregate_type: str) -> str:
        """Get DLQ Redis key for aggregate type"""
        return f"ragline:dlq:{aggregate_type}"

    def _get_processing_key(self, aggregate_type: str) -> str:
        """Get processing Redis key for aggregate type"""
        return f"ragline:dlq:processing:{aggregate_type}"

    def _calculate_retry_delay(self, attempt: int) -> int:
        """Calculate exponential backoff delay"""
        delay = self.initial_retry_delay * (self.retry_multiplier**attempt)
        return min(delay, self.max_retry_delay)

    def _is_ready_for_retry(self, event: DLQEvent) -> bool:
        """Check if event is ready for retry based on exponential backoff"""
        if not event.last_attempt:
            return True

        retry_delay = self._calculate_retry_delay(event.retry_count)
        next_retry_time = event.last_attempt + timedelta(seconds=retry_delay)

        return datetime.now(timezone.utc) >= next_retry_time.replace(tzinfo=timezone.utc)

    def _is_expired(self, event: DLQEvent) -> bool:
        """Check if event has expired"""
        expiry_time = event.failed_at + timedelta(days=self.event_expiry_days)
        return datetime.now(timezone.utc) >= expiry_time.replace(tzinfo=timezone.utc)

    async def add_event(self, event_data: Dict[str, Any]) -> str:
        """Add event to DLQ"""
        redis_client = await self._get_redis()

        # Enhance event data with DLQ metadata
        enhanced_data = {
            **event_data,
            "status": DLQEventStatus.PENDING.value,
            "last_attempt": "",
        }

        dlq_key = self._get_dlq_key(event_data["aggregate_type"])
        await redis_client.lpush(dlq_key, json.dumps(enhanced_data))

        logger.info(f"Added event {event_data['event_id']} to DLQ: {dlq_key}")
        return dlq_key

    async def get_pending_events(self, aggregate_type: str, limit: int = 10) -> List[DLQEvent]:
        """Get events ready for reprocessing"""
        redis_client = await self._get_redis()
        dlq_key = self._get_dlq_key(aggregate_type)

        # Get all events from DLQ
        event_jsons = await redis_client.lrange(dlq_key, 0, -1)

        ready_events = []
        for event_json in event_jsons:
            try:
                event_data = json.loads(event_json)
                event = DLQEvent.from_redis_data(event_data)

                # Skip expired events
                if self._is_expired(event):
                    await self._expire_event(aggregate_type, event)
                    continue

                # Check if ready for retry
                if (
                    event.status == DLQEventStatus.PENDING
                    and self._is_ready_for_retry(event)
                    and len(ready_events) < limit
                ):
                    ready_events.append(event)

            except Exception as e:
                logger.error(f"Failed to parse DLQ event: {e}")
                continue

        return ready_events

    async def reprocess_event(self, event: DLQEvent) -> bool:
        """Reprocess a single DLQ event"""
        try:
            # Update event status to processing
            event.status = DLQEventStatus.PROCESSING
            event.last_attempt = datetime.now(timezone.utc)
            await self._update_event_in_dlq(event)

            # Reset event in database for outbox consumer to pick up
            async with AsyncSessionLocal() as session:
                try:
                    query = (
                        update(Outbox)
                        .where(Outbox.id == int(event.event_id))
                        .values(
                            processed=False,
                            processed_at=None,
                            retry_count=0,  # Reset retry count for fresh attempt
                        )
                    )

                    await session.execute(query)
                    await session.commit()

                    # Remove from DLQ since it's back in processing
                    await self._remove_event_from_dlq(event)

                    self.reprocessed_count += 1

                    # Record metrics
                    if self.prometheus_metrics:
                        self.prometheus_metrics.record_dlq_reprocess_attempt(event.aggregate_type, "success")

                    logger.info(f"Successfully reprocessed event {event.event_id}")
                    return True

                except Exception as e:
                    await session.rollback()
                    logger.error(f"Database error reprocessing event {event.event_id}: {e}")
                    raise

        except Exception as e:
            # Mark as failed in DLQ
            event.status = DLQEventStatus.FAILED
            event.retry_count += 1

            if event.retry_count >= self.max_reprocess_attempts:
                event.status = DLQEventStatus.MANUAL  # Requires manual intervention
                logger.error(f"Event {event.event_id} requires manual intervention after {event.retry_count} attempts")

            await self._update_event_in_dlq(event)

            self.failed_reprocess_count += 1

            # Record metrics
            if self.prometheus_metrics:
                self.prometheus_metrics.record_dlq_reprocess_attempt(event.aggregate_type, "failed")

            logger.error(f"Failed to reprocess event {event.event_id}: {e}")
            return False

    async def batch_reprocess(self, aggregate_type: str, limit: int = 10) -> Dict[str, int]:
        """Reprocess multiple events from DLQ"""
        events = await self.get_pending_events(aggregate_type, limit)

        results = {"attempted": len(events), "succeeded": 0, "failed": 0}

        for event in events:
            if await self.reprocess_event(event):
                results["succeeded"] += 1
            else:
                results["failed"] += 1

        logger.info(f"Batch reprocess results for {aggregate_type}: {results}")
        return results

    async def _update_event_in_dlq(self, event: DLQEvent):
        """Update event status in DLQ"""
        redis_client = await self._get_redis()
        dlq_key = self._get_dlq_key(event.aggregate_type)

        # Find and replace the event
        event_jsons = await redis_client.lrange(dlq_key, 0, -1)

        for i, event_json in enumerate(event_jsons):
            try:
                event_data = json.loads(event_json)
                if event_data["event_id"] == event.event_id:
                    # Replace with updated event
                    await redis_client.lset(dlq_key, i, json.dumps(event.to_redis_data()))
                    break
            except Exception as e:
                logger.error(f"Failed to update event in DLQ: {e}")

    async def _remove_event_from_dlq(self, event: DLQEvent):
        """Remove event from DLQ"""
        redis_client = await self._get_redis()
        dlq_key = self._get_dlq_key(event.aggregate_type)

        # Remove the event
        await redis_client.lrem(dlq_key, 1, json.dumps(event.to_redis_data()))

    async def _expire_event(self, aggregate_type: str, event: DLQEvent):
        """Mark event as expired and remove from active DLQ"""
        event.status = DLQEventStatus.EXPIRED

        # Move to expired events list for audit trail
        redis_client = await self._get_redis()
        expired_key = f"ragline:dlq:expired:{aggregate_type}"
        await redis_client.lpush(expired_key, json.dumps(event.to_redis_data()))

        # Remove from active DLQ
        await self._remove_event_from_dlq(event)

        self.expired_count += 1
        logger.info(f"Expired event {event.event_id} after {self.event_expiry_days} days")

    async def get_dlq_stats(self) -> Dict[str, Any]:
        """Get comprehensive DLQ statistics"""
        redis_client = await self._get_redis()
        stats = {
            "by_aggregate_type": {},
            "total_events": 0,
            "status_counts": {status.value: 0 for status in DLQEventStatus},
            "oldest_event_hours": 0,
            "failure_rate": 0,
            "reprocessed_count": self.reprocessed_count,
            "failed_reprocess_count": self.failed_reprocess_count,
            "expired_count": self.expired_count,
        }

        # Get all DLQ keys
        dlq_keys = await redis_client.keys("ragline:dlq:*")

        oldest_event = None

        for key in dlq_keys:
            if b":processing:" in key or b":expired:" in key:
                continue

            key_str = key.decode("utf-8")
            aggregate_type = key_str.split(":")[-1]

            events = await redis_client.lrange(key, 0, -1)
            event_count = len(events)

            stats["by_aggregate_type"][aggregate_type] = {
                "count": event_count,
                "status_breakdown": {status.value: 0 for status in DLQEventStatus},
            }

            stats["total_events"] += event_count

            # Analyze individual events
            for event_json in events:
                try:
                    event_data = json.loads(event_json)
                    status = event_data.get("status", DLQEventStatus.PENDING.value)
                    stats["status_counts"][status] += 1
                    stats["by_aggregate_type"][aggregate_type]["status_breakdown"][status] += 1

                    # Track oldest event
                    failed_at = datetime.fromisoformat(event_data["failed_at"])
                    if not oldest_event or failed_at < oldest_event:
                        oldest_event = failed_at

                except Exception as e:
                    logger.error(f"Failed to parse event for stats: {e}")

        # Calculate oldest event age
        if oldest_event:
            age_delta = datetime.now(timezone.utc) - oldest_event.replace(tzinfo=timezone.utc)
            stats["oldest_event_hours"] = age_delta.total_seconds() / 3600

        # Calculate failure rate (would need additional metrics from outbox consumer)
        # For now, use a simplified calculation
        total_processed = self.reprocessed_count + self.failed_reprocess_count
        if total_processed > 0:
            stats["failure_rate"] = stats["total_events"] / total_processed

        return stats

    async def get_events_requiring_manual_intervention(self) -> List[DLQEvent]:
        """Get events that require manual intervention"""
        redis_client = await self._get_redis()
        manual_events = []

        # Check all DLQ keys
        dlq_keys = await redis_client.keys("ragline:dlq:*")

        for key in dlq_keys:
            if b":processing:" in key or b":expired:" in key:
                continue

            events = await redis_client.lrange(key, 0, -1)

            for event_json in events:
                try:
                    event_data = json.loads(event_json)
                    event = DLQEvent.from_redis_data(event_data)

                    if event.status == DLQEventStatus.MANUAL:
                        manual_events.append(event)

                except Exception as e:
                    logger.error(f"Failed to parse manual intervention event: {e}")

        return manual_events

    async def mark_event_resolved(self, event_id: str, aggregate_type: str) -> bool:
        """Manually mark an event as resolved"""
        redis_client = await self._get_redis()
        dlq_key = self._get_dlq_key(aggregate_type)

        # Find and remove the event
        event_jsons = await redis_client.lrange(dlq_key, 0, -1)

        for event_json in event_jsons:
            try:
                event_data = json.loads(event_json)
                if event_data["event_id"] == event_id:
                    # Remove from DLQ
                    await redis_client.lrem(dlq_key, 1, event_json)

                    # Add to resolved events for audit
                    resolved_key = f"ragline:dlq:resolved:{aggregate_type}"
                    event_data["resolved_at"] = datetime.now(timezone.utc).isoformat()
                    await redis_client.lpush(resolved_key, json.dumps(event_data))

                    logger.info(f"Manually resolved event {event_id}")
                    return True

            except Exception as e:
                logger.error(f"Failed to resolve event {event_id}: {e}")

        return False

    async def get_alerts(self) -> List[Dict[str, Any]]:
        """Get current DLQ alerts"""
        stats = await self.get_dlq_stats()
        return await self.alert_manager.check_alerts(stats)

    async def cleanup_expired_events(self, days_to_keep: int = 30) -> int:
        """Clean up old expired and resolved events"""
        redis_client = await self._get_redis()
        cleaned = 0

        # Clean expired events
        expired_keys = await redis_client.keys("ragline:dlq:expired:*")
        resolved_keys = await redis_client.keys("ragline:dlq:resolved:*")

        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        for key in expired_keys + resolved_keys:
            events = await redis_client.lrange(key, 0, -1)

            for event_json in events:
                try:
                    event_data = json.loads(event_json)
                    event_time = datetime.fromisoformat(event_data.get("resolved_at") or event_data.get("failed_at"))

                    if event_time.replace(tzinfo=timezone.utc) < cutoff_time:
                        await redis_client.lrem(key, 1, event_json)
                        cleaned += 1

                except Exception as e:
                    logger.error(f"Failed to clean expired event: {e}")

        logger.info(f"Cleaned up {cleaned} old DLQ events")
        return cleaned


# Global DLQ manager instance
_dlq_manager: Optional[DLQManager] = None


async def get_dlq_manager() -> DLQManager:
    """Get or create DLQ manager instance"""
    global _dlq_manager

    if not _dlq_manager:
        config = WorkerConfig()
        _dlq_manager = DLQManager(config)

    return _dlq_manager
