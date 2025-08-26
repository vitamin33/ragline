"""
RAGline SSE/WebSocket Notification Tasks

Subscribes to Redis streams and fans out events to connected SSE/WebSocket clients.
Implements backpressure handling and connection management for real-time notifications.
"""

import asyncio
import json
import time
import weakref
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any, AsyncGenerator
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

import redis.asyncio as redis
from celery import Task
from celery.utils.log import get_task_logger

from ..celery_app import app
from ..config import WorkerConfig
from packages.orchestrator.redis_simple import get_simple_redis_client
from packages.orchestrator.stream_producer import StreamTopic
from packages.orchestrator.event_schemas import OrderV1Event, EventSerializer, validate_event_structure

logger = get_task_logger(__name__)


@dataclass
class ConnectedClient:
    """Represents a connected SSE/WebSocket client"""
    client_id: str
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    connection_type: str = "sse"  # "sse" or "websocket"
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_ping: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    subscriptions: Set[str] = field(default_factory=set)  # Event types to receive
    
    # Connection health
    missed_pings: int = 0
    is_healthy: bool = True
    
    def update_ping(self):
        """Update last ping timestamp"""
        self.last_ping = datetime.now(timezone.utc)
        self.missed_pings = 0
        self.is_healthy = True
    
    def mark_missed_ping(self):
        """Mark a missed ping"""
        self.missed_pings += 1
        if self.missed_pings >= 3:
            self.is_healthy = False


class ConnectionManager:
    """
    Manages SSE/WebSocket client connections with health monitoring.
    Implements connection pooling and automatic cleanup of stale connections.
    """
    
    def __init__(self):
        # Use WeakSet for automatic cleanup when clients disconnect
        self._connections: Dict[str, ConnectedClient] = {}
        self._connections_by_user: Dict[str, Set[str]] = {}
        self._connections_by_tenant: Dict[str, Set[str]] = {}
        
        # Metrics
        self.total_connections = 0
        self.total_messages_sent = 0
        self.total_send_failures = 0
        
        # Connection limits and backpressure
        self.max_connections_per_user = 10
        self.max_connections_per_tenant = 1000
        self.message_queue_limit = 100
        
    def add_connection(self, client: ConnectedClient) -> bool:
        """
        Add a new client connection with validation.
        Returns False if connection limits are exceeded.
        """
        # Check user connection limit
        if client.user_id:
            user_connections = self._connections_by_user.get(client.user_id, set())
            if len(user_connections) >= self.max_connections_per_user:
                logger.warning(f"User {client.user_id} connection limit exceeded")
                return False
        
        # Check tenant connection limit
        if client.tenant_id:
            tenant_connections = self._connections_by_tenant.get(client.tenant_id, set())
            if len(tenant_connections) >= self.max_connections_per_tenant:
                logger.warning(f"Tenant {client.tenant_id} connection limit exceeded")
                return False
        
        # Add connection
        self._connections[client.client_id] = client
        
        # Update indexes
        if client.user_id:
            self._connections_by_user.setdefault(client.user_id, set()).add(client.client_id)
        
        if client.tenant_id:
            self._connections_by_tenant.setdefault(client.tenant_id, set()).add(client.client_id)
        
        self.total_connections += 1
        logger.info(f"Added connection {client.client_id} ({client.connection_type})")
        return True
    
    def remove_connection(self, client_id: str):
        """Remove a client connection"""
        if client_id in self._connections:
            client = self._connections[client_id]
            
            # Remove from indexes
            if client.user_id and client.user_id in self._connections_by_user:
                self._connections_by_user[client.user_id].discard(client_id)
                if not self._connections_by_user[client.user_id]:
                    del self._connections_by_user[client.user_id]
            
            if client.tenant_id and client.tenant_id in self._connections_by_tenant:
                self._connections_by_tenant[client.tenant_id].discard(client_id)
                if not self._connections_by_tenant[client.tenant_id]:
                    del self._connections_by_tenant[client.tenant_id]
            
            # Remove connection
            del self._connections[client_id]
            logger.info(f"Removed connection {client_id}")
    
    def get_connections_for_event(self, event_data: Dict[str, Any]) -> List[ConnectedClient]:
        """Get connections that should receive this event"""
        relevant_connections = []
        
        # Extract event metadata
        tenant_id = event_data.get('tenant_id')
        user_id = event_data.get('user_id')
        event_type = event_data.get('event_type', 'unknown')
        
        for client in self._connections.values():
            should_receive = False
            
            # Must match tenant first (security boundary)
            tenant_match = tenant_id and client.tenant_id == tenant_id
            if not tenant_match and tenant_id:
                continue  # Skip if tenant doesn't match
            
            # Check subscription filtering
            if client.subscriptions:
                subscription_match = (
                    event_type in client.subscriptions or 
                    'all' in client.subscriptions
                )
                
                if subscription_match:
                    # Additional user filtering if user_id specified
                    if user_id:
                        user_match = client.user_id == user_id
                        should_receive = user_match
                    else:
                        should_receive = tenant_match
                else:
                    should_receive = False
            else:
                # Default: receive tenant events if no specific subscriptions
                should_receive = tenant_match
            
            # Health check
            if should_receive and client.is_healthy:
                relevant_connections.append(client)
        
        return relevant_connections
    
    def cleanup_stale_connections(self, max_age_minutes: int = 30):
        """Remove stale connections based on last ping"""
        current_time = datetime.now(timezone.utc)
        stale_connections = []
        
        for client_id, client in self._connections.items():
            age_minutes = (current_time - client.last_ping).total_seconds() / 60
            
            if age_minutes > max_age_minutes or not client.is_healthy:
                stale_connections.append(client_id)
        
        for client_id in stale_connections:
            self.remove_connection(client_id)
        
        if stale_connections:
            logger.info(f"Cleaned up {len(stale_connections)} stale connections")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection manager statistics"""
        healthy_connections = sum(1 for c in self._connections.values() if c.is_healthy)
        
        return {
            'total_connections': len(self._connections),
            'healthy_connections': healthy_connections,
            'unhealthy_connections': len(self._connections) - healthy_connections,
            'connections_by_type': {
                'sse': sum(1 for c in self._connections.values() if c.connection_type == 'sse'),
                'websocket': sum(1 for c in self._connections.values() if c.connection_type == 'websocket')
            },
            'users_connected': len(self._connections_by_user),
            'tenants_connected': len(self._connections_by_tenant),
            'total_messages_sent': self.total_messages_sent,
            'total_send_failures': self.total_send_failures,
            'success_rate': (
                (self.total_messages_sent / max(1, self.total_messages_sent + self.total_send_failures)) * 100
            )
        }


class StreamNotifier:
    """
    Subscribes to Redis streams and fans out events to connected clients.
    Implements backpressure handling and connection health monitoring.
    """
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.connection_manager = ConnectionManager()
        self.redis_client: Optional[redis.Redis] = None
        self.serializer = EventSerializer()
        
        # Stream subscriptions
        self.stream_configs = {
            StreamTopic.ORDERS: {
                'consumer_group': 'ragline_notifiers',
                'consumer_name': f'notifier_{time.time()}',
                'block_time': 1000,  # 1 second
                'count': 10
            },
            StreamTopic.USERS: {
                'consumer_group': 'ragline_notifiers', 
                'consumer_name': f'notifier_{time.time()}',
                'block_time': 1000,
                'count': 5
            },
            StreamTopic.NOTIFICATIONS: {
                'consumer_group': 'ragline_notifiers',
                'consumer_name': f'notifier_{time.time()}',
                'block_time': 1000,
                'count': 20
            }
        }
        
        # Notifier state
        self.is_running = False
        self.processed_events = 0
        self.failed_events = 0
        
    async def start(self):
        """Start the stream notifier"""
        if self.is_running:
            logger.warning("Stream notifier is already running")
            return
        
        logger.info("Starting Redis streams notifier...")
        
        try:
            # Initialize Redis connection
            self.redis_client = await get_simple_redis_client()
            await self.redis_client.initialize()
            
            self.is_running = True
            
            # Start notification loop
            await self._notification_loop()
            
        except Exception as e:
            logger.error(f"Stream notifier failed: {e}", exc_info=True)
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the stream notifier"""
        if not self.is_running:
            return
            
        logger.info("Stopping stream notifier...")
        self.is_running = False
        
        if self.redis_client:
            await self.redis_client.close()
    
    async def _notification_loop(self):
        """Main notification loop that reads from streams"""
        while self.is_running:
            try:
                # Clean up stale connections periodically
                self.connection_manager.cleanup_stale_connections()
                
                # Read from all subscribed streams
                for stream_topic, config in self.stream_configs.items():
                    await self._process_stream(stream_topic.value, config)
                
                # Small delay to prevent tight loop
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in notification loop: {e}", exc_info=True)
                self.failed_events += 1
                
                # Continue running despite errors
                await asyncio.sleep(1.0)
    
    async def _process_stream(self, stream_name: str, config: Dict[str, Any]):
        """Process events from a specific stream"""
        try:
            # Read messages from stream
            messages = await self.redis_client.read_from_stream(
                stream_name,
                config['consumer_group'],
                config['consumer_name'],
                from_id='>',  # Only new messages
                count=config['count'],
                block=config['block_time']
            )
            
            if messages:
                logger.debug(f"Processing {len(messages)} messages from {stream_name}")
                
                for message in messages:
                    await self._process_message(message, stream_name)
                    
                    # Acknowledge message
                    await self.redis_client.acknowledge_message(
                        stream_name,
                        config['consumer_group'],
                        message['id']
                    )
        
        except Exception as e:
            logger.error(f"Error processing stream {stream_name}: {e}")
    
    async def _process_message(self, message: Dict[str, Any], stream_name: str):
        """Process a single message and fan out to clients"""
        try:
            # Extract event data
            fields = message['fields']
            event_data = {
                'event_id': fields.get('event_id'),
                'event_type': fields.get('event_type'),
                'aggregate_id': fields.get('aggregate_id'),
                'aggregate_type': fields.get('aggregate_type'),
                'tenant_id': fields.get('tenant_id'),
                'user_id': fields.get('user_id'),
                'timestamp': fields.get('created_at'),
                'stream_source': stream_name,
                'message_id': message['id']
            }
            
            # Parse payload if present
            if 'payload' in fields:
                try:
                    event_data['payload'] = json.loads(fields['payload'])
                except json.JSONDecodeError:
                    event_data['payload'] = fields['payload']
            
            # Get relevant connections
            connections = self.connection_manager.get_connections_for_event(event_data)
            
            if connections:
                # Fan out to all relevant connections
                await self._fanout_to_connections(event_data, connections)
                
                logger.debug(f"Fanned out event {event_data['event_id']} to {len(connections)} clients")
                self.processed_events += 1
            else:
                logger.debug(f"No connections found for event {event_data['event_id']}")
        
        except Exception as e:
            logger.error(f"Error processing message {message['id']}: {e}")
            self.failed_events += 1
    
    async def _fanout_to_connections(self, event_data: Dict[str, Any], connections: List[ConnectedClient]):
        """Fan out event to multiple connections with backpressure handling"""
        # Prepare notification message
        notification = {
            'type': 'event',
            'event': event_data,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'server': 'ragline_notifier'
        }
        
        # Send to all connections concurrently
        send_tasks = []
        for connection in connections:
            task = asyncio.create_task(
                self._send_to_connection(connection, notification)
            )
            send_tasks.append(task)
        
        # Wait for all sends to complete
        if send_tasks:
            results = await asyncio.gather(*send_tasks, return_exceptions=True)
            
            # Count successes and failures
            successes = sum(1 for r in results if r is True)
            failures = len(results) - successes
            
            self.connection_manager.total_messages_sent += successes
            self.connection_manager.total_send_failures += failures
            
            if failures > 0:
                logger.warning(f"Failed to send to {failures}/{len(connections)} connections")
    
    async def _send_to_connection(self, connection: ConnectedClient, notification: Dict[str, Any]) -> bool:
        """
        Send notification to a specific connection.
        This is a placeholder - actual implementation depends on SSE/WS framework.
        """
        try:
            # TODO: Actual sending logic depends on Agent A's SSE/WebSocket implementation
            # This would typically involve:
            # 1. Format message for SSE or WebSocket protocol
            # 2. Write to connection stream/queue
            # 3. Handle backpressure if client is slow
            # 4. Update connection health
            
            # Simulate sending (for testing without actual connections)
            message_size = len(json.dumps(notification))
            
            # Simulate backpressure check
            if message_size > 10000:  # 10KB limit
                logger.warning(f"Large message ({message_size} bytes) for client {connection.client_id}")
                return False
            
            # Update connection health
            connection.update_ping()
            
            logger.debug(f"Sent {message_size} bytes to {connection.client_id} ({connection.connection_type})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send to connection {connection.client_id}: {e}")
            connection.mark_missed_ping()
            return False
    
    async def add_client_connection(self, client_id: str, connection_type: str = "sse",
                                  user_id: Optional[str] = None, tenant_id: Optional[str] = None,
                                  subscriptions: Optional[Set[str]] = None) -> bool:
        """Add a new client connection"""
        client = ConnectedClient(
            client_id=client_id,
            user_id=user_id,
            tenant_id=tenant_id,
            connection_type=connection_type,
            subscriptions=subscriptions or {'all'}
        )
        
        return self.connection_manager.add_connection(client)
    
    async def remove_client_connection(self, client_id: str):
        """Remove a client connection"""
        self.connection_manager.remove_connection(client_id)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get notifier statistics"""
        connection_stats = self.connection_manager.get_stats()
        
        return {
            'notifier': {
                'is_running': self.is_running,
                'processed_events': self.processed_events,
                'failed_events': self.failed_events,
                'processing_rate': self.processed_events / max(1, time.time()),
                'streams_monitored': len(self.stream_configs)
            },
            'connections': connection_stats,
            'streams': {
                stream.value: config for stream, config in self.stream_configs.items()
            }
        }


# Global notifier instance
_stream_notifier: Optional[StreamNotifier] = None

async def get_stream_notifier() -> StreamNotifier:
    """Get or create stream notifier instance"""
    global _stream_notifier
    
    if not _stream_notifier:
        config = WorkerConfig()
        _stream_notifier = StreamNotifier(config)
    
    return _stream_notifier


# Celery Tasks for Notification Management

class NotificationTask(Task):
    """Base notification task with error handling"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Notification task failed: {exc}", exc_info=einfo)
    
    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"Notification task completed: {retval}")


@app.task(bind=True, base=NotificationTask, name="services.worker.tasks.notifications.start_stream_notifier")
def start_stream_notifier(self) -> Dict[str, Any]:
    """
    Long-running task to start the stream notifier daemon.
    Subscribes to Redis streams and manages client connections.
    """
    async def _start_notifier():
        try:
            notifier = await get_stream_notifier()
            
            logger.info("Starting stream notifier daemon...")
            await notifier.start()
            
            return {"status": "completed", "message": "Stream notifier stopped"}
            
        except Exception as e:
            logger.error(f"Stream notifier daemon failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    try:
        result = asyncio.run(_start_notifier())
        return result
    except Exception as e:
        logger.error(f"Failed to start stream notifier daemon: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, base=NotificationTask, name="services.worker.tasks.notifications.add_client_connection")
def add_client_connection(self, client_id: str, connection_type: str = "sse",
                         user_id: Optional[str] = None, tenant_id: Optional[str] = None,
                         subscriptions: Optional[List[str]] = None) -> Dict[str, Any]:
    """Add a client connection for notifications"""
    async def _add_connection():
        try:
            notifier = await get_stream_notifier()
            
            subscription_set = set(subscriptions) if subscriptions else {'all'}
            
            success = await notifier.add_client_connection(
                client_id=client_id,
                connection_type=connection_type,
                user_id=user_id,
                tenant_id=tenant_id,
                subscriptions=subscription_set
            )
            
            return {
                "status": "success" if success else "failed",
                "client_id": client_id,
                "connection_type": connection_type,
                "subscriptions": list(subscription_set)
            }
            
        except Exception as e:
            logger.error(f"Failed to add client connection: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    try:
        result = asyncio.run(_add_connection())
        return result
    except Exception as e:
        logger.error(f"Failed to add client connection: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, base=NotificationTask, name="services.worker.tasks.notifications.remove_client_connection")
def remove_client_connection(self, client_id: str) -> Dict[str, Any]:
    """Remove a client connection"""
    async def _remove_connection():
        try:
            notifier = await get_stream_notifier()
            await notifier.remove_client_connection(client_id)
            
            return {"status": "success", "client_id": client_id}
            
        except Exception as e:
            logger.error(f"Failed to remove client connection: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    try:
        result = asyncio.run(_remove_connection())
        return result
    except Exception as e:
        logger.error(f"Failed to remove client connection: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, base=NotificationTask, name="services.worker.tasks.notifications.get_notifier_stats")
def get_notifier_stats(self) -> Dict[str, Any]:
    """Get stream notifier statistics"""
    async def _get_stats():
        try:
            notifier = await get_stream_notifier()
            stats = await notifier.get_stats()
            
            # Add timestamp
            stats['timestamp'] = datetime.now(timezone.utc).isoformat()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get notifier stats: {e}", exc_info=True)
            return {"error": str(e)}
    
    try:
        result = asyncio.run(_get_stats())
        return result
    except Exception as e:
        logger.error(f"Failed to get notifier stats: {e}", exc_info=True)
        return {"error": str(e)}


@app.task(bind=True, base=NotificationTask, name="services.worker.tasks.notifications.send_test_notification")
def send_test_notification(self, user_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Send a test notification to verify the system is working"""
    async def _send_test():
        try:
            from packages.orchestrator.stream_producer import get_stream_producer
            from packages.orchestrator.event_schemas import EventFactory, OrderStatus
            import uuid
            
            # Create test order event
            test_event = EventFactory.create_enriched_order_event(
                tenant_id=uuid.UUID(tenant_id) if tenant_id else uuid.uuid4(),
                order_id=uuid.uuid4(),
                status=OrderStatus.CREATED,
                user_id=uuid.UUID(user_id) if user_id else uuid.uuid4(),
                correlation_id="test_notification",
                reason="Test notification from notifier system"
            )
            
            # Publish to stream
            producer = await get_stream_producer()
            
            from packages.orchestrator.stream_producer import StreamEvent, EventMetadata
            
            metadata = EventMetadata(
                event_id=f"test_notification_{int(time.time())}",
                event_type=test_event.event.value,
                aggregate_id=str(test_event.order_id),
                aggregate_type="order",
                tenant_id=str(test_event.tenant_id),
                user_id=str(test_event.user_id)
            )
            
            stream_event = StreamEvent(metadata=metadata, payload=test_event.to_dict())
            message_id = await producer.publish_event(stream_event)
            
            return {
                "status": "success",
                "message": "Test notification sent",
                "event_id": test_event.event.value,
                "order_id": str(test_event.order_id),
                "stream_message_id": str(message_id) if message_id else None
            }
            
        except Exception as e:
            logger.error(f"Failed to send test notification: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    try:
        result = asyncio.run(_send_test())
        return result
    except Exception as e:
        logger.error(f"Failed to send test notification: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}