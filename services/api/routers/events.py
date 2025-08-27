from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import asyncio
import json
import redis.asyncio as redis
from packages.security.auth import get_current_user_token
from packages.security.jwt import TokenData
import structlog
import os
from datetime import datetime, timezone

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/stream")
async def stream_events(
    token_data: TokenData = Depends(get_current_user_token)
):
    """Stream server-sent events for real-time updates."""
    tenant_id = token_data.tenant_id
    user_id = token_data.user_id
    
    async def event_generator():
        """Generate server-sent events from Redis streams."""
        redis_client = None
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis.from_url(redis_url, decode_responses=True)
            
            stream_key = "ragline:stream:orders"
            consumer_group = "ragline-sse-group"
            consumer_name = f"sse-consumer-{user_id}"
            
            # Create consumer group if needed
            try:
                await redis_client.xgroup_create(
                    stream_key, consumer_group, id="0", mkstream=True
                )
            except redis.exceptions.ResponseError:
                pass
            
            logger.info("SSE stream started", tenant_id=tenant_id, user_id=user_id)
            
            # Send connection confirmation
            yield {
                "event": "connected",
                "data": json.dumps({
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            }
            
            last_heartbeat = asyncio.get_event_loop().time()
            
            while True:
                try:
                    messages = await redis_client.xreadgroup(
                        consumer_group,
                        consumer_name,
                        {stream_key: ">"},
                        count=5,
                        block=1000
                    )
                    
                    if messages:
                        for stream, msgs in messages:
                            for msg_id, fields in msgs:
                                event_tenant_id = fields.get("tenant_id")
                                if event_tenant_id and str(event_tenant_id) == str(tenant_id):
                                    yield {
                                        "event": fields.get("event_type", "unknown"),
                                        "data": fields.get("payload", "{}")
                                    }
                                    await redis_client.xack(stream_key, consumer_group, msg_id)
                    
                    # Heartbeat every 30 seconds
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat > 30:
                        yield {
                            "event": "heartbeat",
                            "data": json.dumps({
                                "timestamp": current_time,
                                "message": "Connection alive",
                                "tenant_id": tenant_id
                            })
                        }
                        last_heartbeat = current_time
                        
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logger.error("Stream error", tenant_id=tenant_id, error=str(e))
                    break
                    
        except Exception as e:
            logger.error("SSE stream failed", tenant_id=tenant_id, error=str(e))
            yield {
                "event": "error", 
                "data": json.dumps({"message": "Stream failed", "error": str(e)})
            }
        finally:
            if redis_client:
                await redis_client.close()
    
    return EventSourceResponse(event_generator())


@router.get("/stream/orders")
async def stream_order_events():
    """Stream order-related events."""
    
    async def order_event_generator():
        """Generate order events."""
        # TODO: Implement order event streaming
        yield {
            "event": "order_created",
            "data": json.dumps({
                "message": "Order events streaming not yet implemented"
            })
        }
    
    return EventSourceResponse(order_event_generator())


@router.get("/stream/notifications")
async def stream_notifications():
    """Stream user notification events."""
    
    async def notification_generator():
        """Generate notification events."""
        # TODO: Implement notification streaming
        yield {
            "event": "notification",
            "data": json.dumps({
                "message": "Notification streaming not yet implemented"
            })
        }
    
    return EventSourceResponse(notification_generator())