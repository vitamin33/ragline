"""
RAGline Event Schemas

Pydantic models for event validation, serialization, and deserialization.
Implements validation for order_v1.json and other event contracts.
"""

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Union

from celery.utils.log import get_task_logger
from pydantic import BaseModel, Field, field_validator, model_validator

logger = get_task_logger(__name__)


# Enums for event types and statuses
class OrderStatus(str, Enum):
    """Order status enumeration matching order_v1.json schema"""

    CREATED = "created"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class OrderEvent(str, Enum):
    """Order event types matching order_v1.json schema"""

    ORDER_STATUS = "order_status"


# Core Event Models


class OrderEventMeta(BaseModel):
    """Metadata for order events"""

    reason: Optional[str] = Field(None, description="Reason for status change")

    class Config:
        extra = "allow"  # Allow additional metadata fields


class OrderV1Event(BaseModel):
    """
    Order v1 event model matching contracts/events/order_v1.json schema.

    This model validates events according to the JSON schema specification
    and provides type safety for order status events.
    """

    event: OrderEvent = Field(..., description="Event type")
    version: str = Field(..., pattern=r"^[0-9]+\.[0-9]+$", description="Event version")
    tenant_id: uuid.UUID = Field(..., description="Tenant identifier")
    order_id: uuid.UUID = Field(..., description="Order identifier")
    status: OrderStatus = Field(..., description="Order status")
    ts: datetime = Field(..., description="Event timestamp")
    meta: Optional[OrderEventMeta] = Field(None, description="Additional metadata")

    @field_validator("version")
    @classmethod
    def validate_version(cls, v):
        """Validate version format"""
        if not v or "." not in v:
            raise ValueError("Version must be in format 'major.minor'")

        try:
            major, minor = v.split(".")
            int(major)  # Validate it's a number
            int(minor)  # Validate it's a number
        except ValueError:
            raise ValueError("Version parts must be integers")

        return v

    @field_validator("ts", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        """Validate and normalize timestamp"""
        if isinstance(v, str):
            try:
                # Parse ISO format timestamp
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Timestamp must be in ISO format")
        elif isinstance(v, datetime):
            # Ensure timezone aware
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v
        else:
            raise ValueError("Timestamp must be string or datetime")

    @model_validator(mode="after")
    def validate_event_consistency(self):
        """Validate event consistency"""
        # Ensure event type matches expected pattern
        if self.event == OrderEvent.ORDER_STATUS:
            if self.status not in [
                OrderStatus.CREATED,
                OrderStatus.CONFIRMED,
                OrderStatus.FAILED,
            ]:
                raise ValueError(
                    f"Invalid status '{self.status}' for event '{self.event}'"
                )

        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with proper serialization"""
        data = self.model_dump()

        # Convert UUID to string
        data["tenant_id"] = str(data["tenant_id"])
        data["order_id"] = str(data["order_id"])

        # Convert datetime to ISO string
        data["ts"] = self.ts.isoformat()

        # Convert enums to values
        data["event"] = self.event.value
        data["status"] = self.status.value

        return data

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderV1Event":
        """Create from dictionary with validation"""
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> "OrderV1Event":
        """Create from JSON string with validation"""
        return cls.model_validate_json(json_str)


# Extended event models for internal use


class EnrichedOrderEvent(OrderV1Event):
    """
    Extended order event with additional internal fields.
    Used internally by RAGline for enhanced processing.
    """

    # Additional internal fields (not in external contract)
    source_service: Optional[str] = Field(
        None, description="Service that generated the event"
    )
    correlation_id: Optional[str] = Field(
        None, description="Correlation ID for tracing"
    )
    causation_id: Optional[str] = Field(
        None, description="ID of event that caused this event"
    )
    user_id: Optional[uuid.UUID] = Field(
        None, description="User who triggered the event"
    )
    retry_count: int = Field(0, description="Number of retry attempts")
    processed_at: Optional[datetime] = Field(
        None, description="When event was processed"
    )

    def to_external_event(self) -> OrderV1Event:
        """Convert to external contract format (remove internal fields)"""
        external_data = {
            "event": self.event,
            "version": self.version,
            "tenant_id": self.tenant_id,
            "order_id": self.order_id,
            "status": self.status,
            "ts": self.ts,
        }

        if self.meta:
            external_data["meta"] = self.meta

        return OrderV1Event(**external_data)


# Generic event models


class BaseEvent(BaseModel):
    """Base event model for all RAGline events"""

    event_id: str = Field(..., description="Unique event identifier")
    event_type: str = Field(..., description="Type of event")
    aggregate_id: str = Field(..., description="ID of the aggregate")
    aggregate_type: str = Field(..., description="Type of aggregate")
    version: str = Field("1.0", description="Event schema version")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Optional metadata
    source_service: Optional[str] = Field(
        None, description="Service that generated event"
    )
    correlation_id: Optional[str] = Field(None, description="Correlation ID")
    causation_id: Optional[str] = Field(None, description="Causation ID")
    user_id: Optional[str] = Field(None, description="User ID")
    tenant_id: Optional[str] = Field(None, description="Tenant ID")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat(), uuid.UUID: lambda v: str(v)}


class EventPayload(BaseModel):
    """Generic event payload model"""

    class Config:
        extra = "allow"  # Allow additional fields


# Event validation utilities


class EventSchemaValidator:
    """
    Validates events against their JSON schemas and provides
    serialization/deserialization utilities.
    """

    def __init__(self):
        self.schemas = {}
        self.load_schemas()

    def load_schemas(self):
        """Load event schemas from contracts directory"""
        try:
            import os

            # Load order_v1.json schema
            schema_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "contracts",
                "events",
                "order_v1.json",
            )

            if os.path.exists(schema_path):
                with open(schema_path, "r") as f:
                    self.schemas["order_v1"] = json.load(f)
                    logger.info("Loaded order_v1.json schema")
            else:
                logger.warning(f"Schema file not found: {schema_path}")

        except Exception as e:
            logger.error(f"Failed to load schemas: {e}")

    def validate_order_v1(self, event_data: Dict[str, Any]) -> bool:
        """Validate data against order_v1.json schema"""
        try:
            # Use Pydantic model for validation
            OrderV1Event.from_dict(event_data)
            return True
        except Exception as e:
            logger.error(f"Order v1 validation failed: {e}")
            return False

    def validate_event(self, event_type: str, event_data: Dict[str, Any]) -> bool:
        """Validate event data against appropriate schema"""
        if event_type == "order_v1" or event_data.get("event") == "order_status":
            return self.validate_order_v1(event_data)

        # For other event types, use basic validation
        try:
            BaseEvent(**event_data)
            return True
        except Exception as e:
            logger.error(f"Event validation failed for {event_type}: {e}")
            return False


# Event serialization utilities


class EventSerializer:
    """
    Handles serialization and deserialization of events
    with proper type conversion and validation.
    """

    @staticmethod
    def serialize_order_v1(event: OrderV1Event) -> str:
        """Serialize order v1 event to JSON"""
        return event.to_json()

    @staticmethod
    def deserialize_order_v1(json_str: str) -> OrderV1Event:
        """Deserialize JSON to order v1 event"""
        return OrderV1Event.from_json(json_str)

    @staticmethod
    def serialize_base_event(event: BaseEvent) -> str:
        """Serialize base event to JSON"""
        return event.model_dump_json()

    @staticmethod
    def deserialize_base_event(json_str: str) -> BaseEvent:
        """Deserialize JSON to base event"""
        return BaseEvent.model_validate_json(json_str)

    @staticmethod
    def serialize_to_stream_fields(
        event: Union[OrderV1Event, BaseEvent],
    ) -> Dict[str, str]:
        """
        Convert event to Redis stream fields format.
        All values must be strings for Redis streams.
        """
        if isinstance(event, OrderV1Event):
            data = event.to_dict()
        else:
            data = event.model_dump()

        # Convert all values to strings for Redis
        stream_fields = {}

        for key, value in data.items():
            if value is None:
                continue

            if isinstance(value, dict):
                stream_fields[key] = json.dumps(value)
            elif isinstance(value, list):
                stream_fields[key] = json.dumps(value)
            elif isinstance(value, (datetime, uuid.UUID)):
                stream_fields[key] = str(value)
            else:
                stream_fields[key] = str(value)

        return stream_fields

    @staticmethod
    def deserialize_from_stream_fields(
        fields: Dict[str, str], event_type: str = "base"
    ) -> Union[OrderV1Event, BaseEvent]:
        """
        Convert Redis stream fields back to event object.
        Handles type conversion and JSON parsing.
        """
        # Convert string fields back to appropriate types
        data = {}

        for key, value in fields.items():
            if not value:  # Skip empty values
                continue

            # Try to parse JSON fields
            if key in ["meta", "payload"] or value.startswith(("{", "[")):
                try:
                    data[key] = json.loads(value)
                    continue
                except json.JSONDecodeError:
                    pass

            # Handle specific field types
            if key in ["tenant_id", "order_id", "user_id"]:
                try:
                    data[key] = uuid.UUID(value)
                except ValueError:
                    data[key] = value  # Keep as string if not valid UUID
            elif key in ["ts", "timestamp", "processed_at"]:
                try:
                    data[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    data[key] = value  # Keep as string if not valid datetime
            elif key in ["retry_count"]:
                try:
                    data[key] = int(value)
                except ValueError:
                    data[key] = 0
            else:
                data[key] = value

        # Create appropriate event type
        if event_type == "order_v1" or data.get("event") == "order_status":
            return OrderV1Event.from_dict(data)
        else:
            return BaseEvent(**data)


# Event factory for creating events


class EventFactory:
    """Factory for creating validated events"""

    @staticmethod
    def create_order_status_event(
        tenant_id: Union[str, uuid.UUID],
        order_id: Union[str, uuid.UUID],
        status: OrderStatus,
        version: str = "1.0",
        reason: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> OrderV1Event:
        """Create order status event with validation"""

        meta = None
        if reason:
            meta = OrderEventMeta(reason=reason)

        return OrderV1Event(
            event=OrderEvent.ORDER_STATUS,
            version=version,
            tenant_id=tenant_id,
            order_id=order_id,
            status=status,
            ts=timestamp or datetime.now(timezone.utc),
            meta=meta,
        )

    @staticmethod
    def create_enriched_order_event(
        tenant_id: Union[str, uuid.UUID],
        order_id: Union[str, uuid.UUID],
        status: OrderStatus,
        user_id: Optional[Union[str, uuid.UUID]] = None,
        correlation_id: Optional[str] = None,
        source_service: str = "ragline_worker",
        version: str = "1.0",
        reason: Optional[str] = None,
    ) -> EnrichedOrderEvent:
        """Create enriched order event with internal metadata"""

        meta = None
        if reason:
            meta = OrderEventMeta(reason=reason)

        return EnrichedOrderEvent(
            event=OrderEvent.ORDER_STATUS,
            version=version,
            tenant_id=tenant_id,
            order_id=order_id,
            status=status,
            ts=datetime.now(timezone.utc),
            meta=meta,
            source_service=source_service,
            correlation_id=correlation_id,
            user_id=user_id,
        )


# Schema validation utilities


def validate_order_v1_json_schema(event_data: Dict[str, Any]) -> bool:
    """Validate event data against order_v1.json JSON schema"""
    try:
        # Use Pydantic model for validation
        OrderV1Event.from_dict(event_data)
        return True
    except Exception as e:
        logger.error(f"Order v1 schema validation failed: {e}")
        return False


def validate_event_structure(event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate event structure and return validation results.

    Returns:
        Dict with validation results and details
    """
    validation_result = {
        "valid": False,
        "event_type": "unknown",
        "errors": [],
        "warnings": [],
    }

    try:
        # Determine event type
        if "event" in event_dict and event_dict["event"] == "order_status":
            validation_result["event_type"] = "order_v1"

            # Validate against order v1 schema
            try:
                order_event = OrderV1Event.from_dict(event_dict)
                validation_result["valid"] = True
                validation_result["validated_event"] = order_event

            except Exception as e:
                validation_result["errors"].append(f"Order v1 validation: {str(e)}")

        else:
            # Try base event validation
            validation_result["event_type"] = "base"

            try:
                base_event = BaseEvent(**event_dict)
                validation_result["valid"] = True
                validation_result["validated_event"] = base_event

            except Exception as e:
                validation_result["errors"].append(f"Base event validation: {str(e)}")

        # Additional warnings
        required_fields = (
            ["event_id", "timestamp"]
            if validation_result["event_type"] == "base"
            else ["event", "version", "tenant_id", "order_id", "status", "ts"]
        )

        for field in required_fields:
            if field not in event_dict:
                validation_result["warnings"].append(
                    f"Missing recommended field: {field}"
                )

    except Exception as e:
        validation_result["errors"].append(f"Validation error: {str(e)}")

    return validation_result


# Global instances
_event_validator: Optional[EventSchemaValidator] = None
_event_serializer: Optional[EventSerializer] = None


def get_event_validator() -> EventSchemaValidator:
    """Get global event validator instance"""
    global _event_validator
    if not _event_validator:
        _event_validator = EventSchemaValidator()
    return _event_validator


def get_event_serializer() -> EventSerializer:
    """Get global event serializer instance"""
    global _event_serializer
    if not _event_serializer:
        _event_serializer = EventSerializer()
    return _event_serializer
