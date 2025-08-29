import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Set

import redis.asyncio as redis
import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from packages.security.auth import get_current_user_token
from packages.security.jwt import TokenData, verify_token

router = APIRouter()
logger = structlog.get_logger(__name__)


class RedisConnectionManager:
    """Manages Redis connection pool for SSE endpoints."""

    def __init__(self):
        self.pool: Optional[redis.ConnectionPool] = None
        self._lock = asyncio.Lock()

    async def get_pool(self) -> redis.ConnectionPool:
        """Get or create Redis connection pool."""
        if self.pool is None:
            async with self._lock:
                if self.pool is None:
                    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                    self.pool = redis.ConnectionPool.from_url(
                        redis_url,
                        decode_responses=True,
                        max_connections=20,
                        retry_on_timeout=True,
                        health_check_interval=30,
                    )
                    logger.info("Redis connection pool created", url=redis_url)
        return self.pool

    async def get_client(self) -> redis.Redis:
        """Get Redis client from pool."""
        pool = await self.get_pool()
        return redis.Redis(connection_pool=pool)

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.disconnect()
            self.pool = None
            logger.info("Redis connection pool closed")


# Global connection manager
redis_manager = RedisConnectionManager()


class WebSocketConnection:
    """Represents a WebSocket connection with metadata."""

    def __init__(
        self, websocket: WebSocket, client_id: str, user_id: str, tenant_id: str
    ):
        self.websocket = websocket
        self.client_id = client_id
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.connected_at = datetime.now(timezone.utc)
        self.last_message_at = self.connected_at
        self.message_count = 0
        self.subscriptions: Set[str] = set()

    async def send_message(self, message: dict):
        """Send message to WebSocket client."""
        try:
            await self.websocket.send_text(json.dumps(message))
            self.message_count += 1
            self.last_message_at = datetime.now(timezone.utc)
            return True
        except Exception as e:
            logger.error(
                "WebSocket send failed", client_id=self.client_id, error=str(e)
            )
            return False

    def is_healthy(self) -> bool:
        """Check if connection is healthy (not stale)."""
        now = datetime.now(timezone.utc)
        return (now - self.last_message_at).seconds < 300  # 5 minutes


class WebSocketConnectionManager:
    """Manages active WebSocket connections with tenant isolation."""

    def __init__(self):
        self.connections: Dict[str, WebSocketConnection] = {}
        self._tenant_connections: Dict[str, Set[str]] = {}
        self._user_connections: Dict[str, Set[str]] = {}
        self._lock = asyncio.Lock()

    async def add_connection(self, connection: WebSocketConnection) -> bool:
        """Add a new WebSocket connection."""
        async with self._lock:
            try:
                self.connections[connection.client_id] = connection

                # Track by tenant
                if connection.tenant_id not in self._tenant_connections:
                    self._tenant_connections[connection.tenant_id] = set()
                self._tenant_connections[connection.tenant_id].add(connection.client_id)

                # Track by user
                if connection.user_id not in self._user_connections:
                    self._user_connections[connection.user_id] = set()
                self._user_connections[connection.user_id].add(connection.client_id)

                logger.info(
                    "WebSocket connection added",
                    client_id=connection.client_id,
                    user_id=connection.user_id,
                    tenant_id=connection.tenant_id,
                )
                return True

            except Exception as e:
                logger.error(
                    "Failed to add WebSocket connection",
                    client_id=connection.client_id,
                    error=str(e),
                )
                return False

    async def remove_connection(self, client_id: str):
        """Remove a WebSocket connection."""
        async with self._lock:
            if client_id in self.connections:
                connection = self.connections[client_id]

                # Remove from tenant tracking
                if connection.tenant_id in self._tenant_connections:
                    self._tenant_connections[connection.tenant_id].discard(client_id)
                    if not self._tenant_connections[connection.tenant_id]:
                        del self._tenant_connections[connection.tenant_id]

                # Remove from user tracking
                if connection.user_id in self._user_connections:
                    self._user_connections[connection.user_id].discard(client_id)
                    if not self._user_connections[connection.user_id]:
                        del self._user_connections[connection.user_id]

                del self.connections[client_id]

                logger.info(
                    "WebSocket connection removed",
                    client_id=client_id,
                    user_id=connection.user_id,
                    tenant_id=connection.tenant_id,
                )

    def get_connections_for_tenant(self, tenant_id: str) -> list[WebSocketConnection]:
        """Get all connections for a tenant."""
        if tenant_id not in self._tenant_connections:
            return []

        return [
            self.connections[client_id]
            for client_id in self._tenant_connections[tenant_id]
            if client_id in self.connections
        ]

    def get_connections_for_user(self, user_id: str) -> list[WebSocketConnection]:
        """Get all connections for a user."""
        if user_id not in self._user_connections:
            return []

        return [
            self.connections[client_id]
            for client_id in self._user_connections[user_id]
            if client_id in self.connections
        ]

    async def broadcast_to_tenant(
        self, tenant_id: str, message: dict, event_filter: Optional[str] = None
    ):
        """Broadcast message to all connections in a tenant."""
        connections = self.get_connections_for_tenant(tenant_id)
        successful_sends = 0
        failed_connections = []

        for connection in connections:
            # Apply event filtering if specified
            if (
                event_filter
                and event_filter not in connection.subscriptions
                and "all" not in connection.subscriptions
            ):
                continue

            success = await connection.send_message(message)
            if success:
                successful_sends += 1
            else:
                failed_connections.append(connection.client_id)

        # Clean up failed connections
        for client_id in failed_connections:
            await self.remove_connection(client_id)

        return successful_sends

    def get_stats(self) -> dict:
        """Get connection statistics."""
        return {
            "total_connections": len(self.connections),
            "connections_by_tenant": {
                tenant: len(clients)
                for tenant, clients in self._tenant_connections.items()
            },
            "connections_by_user": {
                user: len(clients) for user, clients in self._user_connections.items()
            },
            "healthy_connections": sum(
                1 for conn in self.connections.values() if conn.is_healthy()
            ),
        }

    async def cleanup_stale_connections(self):
        """Remove stale/unhealthy connections."""
        stale_clients = [
            client_id
            for client_id, conn in self.connections.items()
            if not conn.is_healthy()
        ]

        for client_id in stale_clients:
            await self.remove_connection(client_id)

        return len(stale_clients)


# Global WebSocket connection manager
websocket_manager = WebSocketConnectionManager()


@router.get("/stream")
async def stream_events(token_data: TokenData = Depends(get_current_user_token)):
    """Stream server-sent events for real-time updates."""
    tenant_id = token_data.tenant_id
    user_id = token_data.user_id

    async def event_generator():
        """Generate server-sent events from Redis streams."""
        redis_client = None
        try:
            redis_client = await redis_manager.get_client()
            stream_key = "ragline:stream:orders"
            consumer_group = "ragline-sse-group"
            consumer_name = f"sse-consumer-{user_id}"

            # Create consumer group if needed
            try:
                await redis_client.xgroup_create(stream_key, consumer_group, id="0", mkstream=True)
            except redis.exceptions.ResponseError:
                pass

            logger.info("SSE stream started", tenant_id=tenant_id, user_id=user_id)

            # Send connection confirmation
            yield {
                "event": "connected",
                "data": json.dumps(
                    {
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            }

            last_heartbeat = asyncio.get_event_loop().time()

            while True:
                try:
                    messages = await redis_client.xreadgroup(
                        consumer_group,
                        consumer_name,
                        {stream_key: ">"},
                        count=5,
                        block=1000,
                    )

                    if messages:
                        for stream, msgs in messages:
                            for msg_id, fields in msgs:
                                event_tenant_id = fields.get("tenant_id")
                                if event_tenant_id and str(event_tenant_id) == str(tenant_id):
                                    yield {
                                        "event": fields.get("event_type", "unknown"),
                                        "data": fields.get("payload", "{}"),
                                    }
                                    await redis_client.xack(stream_key, consumer_group, msg_id)

                    # Heartbeat every 30 seconds
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat > 30:
                        yield {
                            "event": "heartbeat",
                            "data": json.dumps(
                                {
                                    "timestamp": current_time,
                                    "message": "Connection alive",
                                    "tenant_id": tenant_id,
                                }
                            ),
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
                "data": json.dumps({"message": "Stream failed", "error": str(e)}),
            }
        finally:
            # Redis client cleanup handled by connection pool
            pass

    return EventSourceResponse(event_generator())


@router.get("/stream/orders")
async def stream_order_events(token_data: TokenData = Depends(get_current_user_token)):
    """Stream order-related events for authenticated user."""
    tenant_id = token_data.tenant_id
    user_id = token_data.user_id

    async def order_event_generator():
        """Generate order events from Redis streams."""
        redis_client = None
        try:
            redis_client = await redis_manager.get_client()

            stream_key = "ragline:stream:orders"
            consumer_group = f"ragline-orders-{tenant_id}"
            consumer_name = f"orders-consumer-{user_id}"

            # Create consumer group if needed
            try:
                await redis_client.xgroup_create(
                    stream_key, consumer_group, id="0", mkstream=True
                )
            except redis.exceptions.ResponseError:
                pass

            logger.info(
                "Order SSE stream started", tenant_id=tenant_id, user_id=user_id
            )

            # Send connection confirmation
            yield {
                "event": "connected",
                "data": json.dumps(
                    {
                        "stream": "orders",
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            }

            last_heartbeat = asyncio.get_event_loop().time()

            while True:
                try:
                    messages = await redis_client.xreadgroup(
                        consumer_group,
                        consumer_name,
                        {stream_key: ">"},
                        count=10,
                        block=2000,
                    )

                    if messages:
                        for stream, msgs in messages:
                            for msg_id, fields in msgs:
                                event_tenant_id = fields.get("tenant_id")
                                event_type = fields.get("event_type", "")

                                # Only send order events for this tenant
                                if (
                                    event_tenant_id
                                    and str(event_tenant_id) == str(tenant_id)
                                    and event_type.startswith("order")
                                ):
                                    yield {
                                        "event": event_type,
                                        "data": fields.get("payload", "{}"),
                                    }
                                    await redis_client.xack(
                                        stream_key, consumer_group, msg_id
                                    )

                    # Heartbeat every 45 seconds for order streams
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat > 45:
                        yield {
                            "event": "heartbeat",
                            "data": json.dumps(
                                {
                                    "stream": "orders",
                                    "timestamp": current_time,
                                    "tenant_id": tenant_id,
                                }
                            ),
                        }
                        last_heartbeat = current_time

                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logger.error(
                        "Order stream error", tenant_id=tenant_id, error=str(e)
                    )
                    break

        except Exception as e:
            logger.error("Order SSE stream failed", tenant_id=tenant_id, error=str(e))
            yield {
                "event": "error",
                "data": json.dumps(
                    {"stream": "orders", "message": "Stream failed", "error": str(e)}
                ),
            }
        finally:
            # Redis client cleanup handled by connection pool
            pass

    return EventSourceResponse(order_event_generator())


@router.get("/stream/notifications")
async def stream_notifications(token_data: TokenData = Depends(get_current_user_token)):
    """Stream notification events for authenticated user."""
    tenant_id = token_data.tenant_id
    user_id = token_data.user_id

    async def notification_generator():
        """Generate notification events from Redis streams."""
        redis_client = None
        try:
            redis_client = await redis_manager.get_client()

            # Listen to multiple stream types for notifications
            stream_keys = {
                "ragline:stream:orders": ">",
                "ragline:stream:notifications": ">",
                "ragline:stream:system": ">",
            }
            consumer_group = f"ragline-notif-{tenant_id}"
            consumer_name = f"notif-consumer-{user_id}"

            # Create consumer groups for all streams
            for stream_key in stream_keys.keys():
                try:
                    await redis_client.xgroup_create(
                        stream_key, consumer_group, id="0", mkstream=True
                    )
                except redis.exceptions.ResponseError:
                    pass

            logger.info(
                "Notification SSE stream started", tenant_id=tenant_id, user_id=user_id
            )

            # Send connection confirmation
            yield {
                "event": "connected",
                "data": json.dumps(
                    {
                        "stream": "notifications",
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            }

            last_heartbeat = asyncio.get_event_loop().time()

            while True:
                try:
                    messages = await redis_client.xreadgroup(
                        consumer_group, consumer_name, stream_keys, count=5, block=3000
                    )

                    if messages:
                        for stream, msgs in messages:
                            for msg_id, fields in msgs:
                                event_tenant_id = fields.get("tenant_id")
                                event_type = fields.get("event_type", "")

                                # Send notification-worthy events for this tenant
                                if event_tenant_id and str(event_tenant_id) == str(
                                    tenant_id
                                ):
                                    # Filter for notification-worthy events
                                    if event_type in [
                                        "order_created",
                                        "order_completed",
                                        "order_failed",
                                        "payment_processed",
                                        "notification",
                                        "system_alert",
                                    ]:
                                        yield {
                                            "event": event_type,
                                            "data": fields.get("payload", "{}"),
                                        }
                                        await redis_client.xack(
                                            stream, consumer_group, msg_id
                                        )

                    # Heartbeat every 60 seconds for notifications
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat > 60:
                        yield {
                            "event": "heartbeat",
                            "data": json.dumps(
                                {
                                    "stream": "notifications",
                                    "timestamp": current_time,
                                    "tenant_id": tenant_id,
                                }
                            ),
                        }
                        last_heartbeat = current_time

                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logger.error(
                        "Notification stream error", tenant_id=tenant_id, error=str(e)
                    )
                    break

        except Exception as e:
            logger.error(
                "Notification SSE stream failed", tenant_id=tenant_id, error=str(e)
            )
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "stream": "notifications",
                        "message": "Stream failed",
                        "error": str(e),
                    }
                ),
            }
        finally:
            # Redis client cleanup handled by connection pool
            pass

    return EventSourceResponse(notification_generator())


# WebSocket Authentication Helper
async def authenticate_websocket(websocket: WebSocket) -> Optional[TokenData]:
    """Authenticate WebSocket connection using token from query parameters."""
    try:
        # Get token from query parameters
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=1008, reason="Authentication required")
            return None

        # Verify token
        token_data = verify_token(token)
        if not token_data:
            await websocket.close(code=1008, reason="Invalid token")
            return None

        return token_data

    except Exception as e:
        logger.error("WebSocket authentication failed", error=str(e))
        await websocket.close(code=1008, reason="Authentication failed")
        return None


@router.websocket("/ws")
async def websocket_events(websocket: WebSocket):
    """WebSocket endpoint for real-time event streaming."""
    client_id = str(uuid.uuid4())

    try:
        await websocket.accept()

        # Authenticate
        token_data = await authenticate_websocket(websocket)
        if not token_data:
            return

        # Create connection
        connection = WebSocketConnection(
            websocket=websocket,
            client_id=client_id,
            user_id=token_data.user_id,
            tenant_id=token_data.tenant_id,
        )

        # Add to manager
        await websocket_manager.add_connection(connection)

        # Send connection confirmation
        await connection.send_message(
            {
                "type": "connected",
                "data": {
                    "client_id": client_id,
                    "tenant_id": token_data.tenant_id,
                    "user_id": token_data.user_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "subscriptions": list(connection.subscriptions),
                },
            }
        )

        # Start Redis stream listener
        redis_client = await redis_manager.get_client()
        stream_key = "ragline:stream:orders"
        consumer_group = f"ragline-ws-{token_data.tenant_id}"
        consumer_name = f"ws-consumer-{client_id}"

        # Create consumer group
        try:
            await redis_client.xgroup_create(
                stream_key, consumer_group, id="0", mkstream=True
            )
        except redis.exceptions.ResponseError:
            pass

        logger.info(
            "WebSocket connected", client_id=client_id, tenant_id=token_data.tenant_id
        )

        # Message processing loop
        while True:
            try:
                # Check for messages from client
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_text(), timeout=1.0
                    )
                    await handle_websocket_message(connection, message)
                except asyncio.TimeoutError:
                    pass

                # Check for Redis stream messages
                messages = await redis_client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: ">"},
                    count=5,
                    block=1000,
                )

                if messages:
                    for stream, msgs in messages:
                        for msg_id, fields in msgs:
                            event_tenant_id = fields.get("tenant_id")
                            if event_tenant_id and str(event_tenant_id) == str(
                                token_data.tenant_id
                            ):
                                await connection.send_message(
                                    {
                                        "type": "event",
                                        "event_type": fields.get(
                                            "event_type", "unknown"
                                        ),
                                        "data": json.loads(fields.get("payload", "{}")),
                                        "timestamp": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                    }
                                )
                                await redis_client.xack(
                                    stream_key, consumer_group, msg_id
                                )

                # Send periodic ping
                if (
                    datetime.now(timezone.utc) - connection.last_message_at
                ).seconds > 30:
                    await connection.send_message(
                        {
                            "type": "ping",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(
                    "WebSocket message processing error",
                    client_id=client_id,
                    error=str(e),
                )
                await connection.send_message(
                    {
                        "type": "error",
                        "message": "Message processing failed",
                        "error": str(e),
                    }
                )
                break

    except Exception as e:
        logger.error("WebSocket connection failed", client_id=client_id, error=str(e))

    finally:
        # Clean up connection
        await websocket_manager.remove_connection(client_id)
        logger.info("WebSocket disconnected", client_id=client_id)


async def handle_websocket_message(connection: WebSocketConnection, message: str):
    """Handle incoming WebSocket message from client."""
    try:
        data = json.loads(message)
        message_type = data.get("type", "")

        if message_type == "subscribe":
            # Handle subscription changes
            subscriptions = data.get("subscriptions", [])
            connection.subscriptions = set(subscriptions)

            await connection.send_message(
                {
                    "type": "subscription_updated",
                    "subscriptions": list(connection.subscriptions),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            logger.info(
                "WebSocket subscription updated",
                client_id=connection.client_id,
                subscriptions=list(connection.subscriptions),
            )

        elif message_type == "ping":
            # Respond to client ping
            await connection.send_message(
                {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}
            )

        elif message_type == "get_stats":
            # Send connection statistics
            stats = websocket_manager.get_stats()
            await connection.send_message(
                {
                    "type": "stats",
                    "data": stats,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        else:
            await connection.send_message(
                {"type": "error", "message": f"Unknown message type: {message_type}"}
            )

    except json.JSONDecodeError:
        await connection.send_message(
            {"type": "error", "message": "Invalid JSON message"}
        )
    except Exception as e:
        logger.error(
            "WebSocket message handling error",
            client_id=connection.client_id,
            error=str(e),
        )
        await connection.send_message(
            {"type": "error", "message": "Message handling failed", "error": str(e)}
        )


@router.websocket("/ws/orders")
async def websocket_orders(websocket: WebSocket):
    """WebSocket endpoint specifically for order events."""
    client_id = str(uuid.uuid4())

    try:
        await websocket.accept()

        # Authenticate
        token_data = await authenticate_websocket(websocket)
        if not token_data:
            return

        # Create connection with order subscriptions
        connection = WebSocketConnection(
            websocket=websocket,
            client_id=client_id,
            user_id=token_data.user_id,
            tenant_id=token_data.tenant_id,
        )
        connection.subscriptions = {
            "order_created",
            "order_updated",
            "order_completed",
            "order_failed",
        }

        # Add to manager
        await websocket_manager.add_connection(connection)

        # Send connection confirmation
        await connection.send_message(
            {
                "type": "connected",
                "stream": "orders",
                "data": {
                    "client_id": client_id,
                    "tenant_id": token_data.tenant_id,
                    "user_id": token_data.user_id,
                    "subscriptions": list(connection.subscriptions),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }
        )

        # Start streaming order events
        redis_client = await redis_manager.get_client()
        stream_key = "ragline:stream:orders"
        consumer_group = f"ragline-ws-orders-{token_data.tenant_id}"
        consumer_name = f"ws-orders-{client_id}"

        # Create consumer group
        try:
            await redis_client.xgroup_create(
                stream_key, consumer_group, id="0", mkstream=True
            )
        except redis.exceptions.ResponseError:
            pass

        logger.info(
            "WebSocket orders connected",
            client_id=client_id,
            tenant_id=token_data.tenant_id,
        )

        # Message processing loop
        while True:
            try:
                # Handle client messages
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_text(), timeout=2.0
                    )
                    await handle_websocket_message(connection, message)
                except asyncio.TimeoutError:
                    pass

                # Process Redis stream messages
                messages = await redis_client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: ">"},
                    count=10,
                    block=2000,
                )

                if messages:
                    for stream, msgs in messages:
                        for msg_id, fields in msgs:
                            event_tenant_id = fields.get("tenant_id")
                            event_type = fields.get("event_type", "")

                            # Only send order events for this tenant
                            if (
                                event_tenant_id
                                and str(event_tenant_id) == str(token_data.tenant_id)
                                and event_type.startswith("order")
                            ):
                                await connection.send_message(
                                    {
                                        "type": "order_event",
                                        "event_type": event_type,
                                        "data": json.loads(fields.get("payload", "{}")),
                                        "timestamp": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                    }
                                )
                                await redis_client.xack(
                                    stream_key, consumer_group, msg_id
                                )

                # Send heartbeat every 45 seconds
                if (
                    datetime.now(timezone.utc) - connection.last_message_at
                ).seconds > 45:
                    await connection.send_message(
                        {
                            "type": "heartbeat",
                            "stream": "orders",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )

            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(
                    "WebSocket orders error", client_id=client_id, error=str(e)
                )
                break

    except Exception as e:
        logger.error(
            "WebSocket orders connection failed", client_id=client_id, error=str(e)
        )

    finally:
        await websocket_manager.remove_connection(client_id)
        logger.info("WebSocket orders disconnected", client_id=client_id)


@router.get("/ws/stats")
async def websocket_stats(token_data: TokenData = Depends(get_current_user_token)):
    """Get WebSocket connection statistics."""
    stats = websocket_manager.get_stats()

    # Add cleanup stats
    cleaned = await websocket_manager.cleanup_stale_connections()
    stats["stale_connections_cleaned"] = cleaned

    return {
        "websocket_stats": stats,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
