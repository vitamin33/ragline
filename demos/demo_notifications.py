#!/usr/bin/env python3
"""
RAGline SSE/WebSocket Notifier Demo

Demonstrates the complete notification system with stream subscription,
connection management, and event fan-out capabilities.
"""

import asyncio
import os
import sys
import uuid

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))


async def demo_notification_system():
    """Demonstrate complete notification system functionality"""
    print("🎯 RAGline SSE/WebSocket Notifier Demo")
    print("=" * 60)

    try:
        from packages.orchestrator.event_schemas import EventFactory, OrderStatus
        from packages.orchestrator.stream_producer import (
            EventMetadata,
            StreamEvent,
            get_stream_producer,
        )
        from services.worker.config import WorkerConfig
        from services.worker.tasks.notifications import (
            ConnectedClient,
            StreamNotifier,
        )

        print("✅ All notification components imported successfully")
        print()

    except Exception as e:
        print(f"❌ Import failed: {e}")
        return

    # Step 1: Set up notification infrastructure
    print("🔧 Step 1: Setting up Notification Infrastructure")
    print("-" * 40)

    try:
        config = WorkerConfig()
        notifier = StreamNotifier(config)

        print("   ✅ Stream notifier initialized")
        print("   📊 Monitoring streams:")

        for stream_topic, stream_config in notifier.stream_configs.items():
            print(f"      📍 {stream_topic.value}")
            print(f"         Consumer group: {stream_config['consumer_group']}")
            print(f"         Block time: {stream_config['block_time']}ms")

        print()

    except Exception as e:
        print(f"   ❌ Setup failed: {e}")
        return

    # Step 2: Create client connections
    print("📱 Step 2: Creating Client Connections")
    print("-" * 40)

    try:
        # Business scenario: E-commerce platform with multiple clients
        tenant_id = "acme_corp"

        clients = [
            {
                "name": "Web Dashboard",
                "client": ConnectedClient(
                    client_id="web_dashboard_001",
                    user_id="admin_user",
                    tenant_id=tenant_id,
                    connection_type="sse",
                    subscriptions={"order_created", "order_confirmed", "order_failed"},
                ),
            },
            {
                "name": "Mobile App",
                "client": ConnectedClient(
                    client_id="mobile_app_002",
                    user_id="customer_user",
                    tenant_id=tenant_id,
                    connection_type="websocket",
                    subscriptions={"order_confirmed", "order_shipped"},
                ),
            },
            {
                "name": "Admin Console",
                "client": ConnectedClient(
                    client_id="admin_console_003",
                    user_id="admin_user",
                    tenant_id=tenant_id,
                    connection_type="sse",
                    subscriptions={"all"},  # Admin sees everything
                ),
            },
        ]

        connected_clients = 0
        for client_info in clients:
            if notifier.connection_manager.add_connection(client_info["client"]):
                connected_clients += 1
                print(
                    f"   ✅ {client_info['name']}: Connected ({client_info['client'].connection_type})"
                )
                print(f"      User: {client_info['client'].user_id}")
                print(f"      Subscriptions: {client_info['client'].subscriptions}")

        print(f"\n   📊 Connected clients: {connected_clients}/{len(clients)}")
        print()

    except Exception as e:
        print(f"   ❌ Client connection setup failed: {e}")
        return

    # Step 3: Simulate order lifecycle events
    print("🛒 Step 3: Simulating Order Lifecycle Events")
    print("-" * 40)

    try:
        producer = await get_stream_producer()

        # Business scenario: Customer places order through fulfillment
        order_id = uuid.uuid4()
        customer_user = "customer_user"

        order_events = [
            {
                "step": "Order Placed",
                "status": OrderStatus.CREATED,
                "reason": "Customer completed checkout",
                "user": customer_user,
            },
            {
                "step": "Payment Processed",
                "status": OrderStatus.CONFIRMED,
                "reason": "Credit card payment successful",
                "user": customer_user,
            },
        ]

        published_events = []

        for i, event_info in enumerate(order_events):
            # Create order event
            order_event = EventFactory.create_enriched_order_event(
                tenant_id=uuid.UUID(
                    "12345678-1234-5678-9012-123456789abc"
                ),  # Fixed for demo
                order_id=order_id,
                status=event_info["status"],
                user_id=uuid.UUID(
                    "87654321-4321-8765-4321-987654321abc"
                ),  # Fixed for demo
                correlation_id=f"order_lifecycle_{order_id}",
                reason=event_info["reason"],
            )

            # Create stream event
            metadata = EventMetadata(
                event_id=f"demo_order_{order_id}_{i}",
                event_type=order_event.event.value,
                aggregate_id=str(order_id),
                aggregate_type="order",
                tenant_id=tenant_id,
                user_id=customer_user,
            )

            stream_event = StreamEvent(metadata=metadata, payload=order_event.to_dict())

            # Publish to stream
            message_id = await producer.publish_event(stream_event)

            if message_id:
                published_events.append((event_info["step"], message_id))
                print(f"   📤 {event_info['step']}: Published to stream")
                print(f"      Status: {event_info['status'].value}")
                print(f"      Message ID: {message_id}")

            # Small delay between events
            await asyncio.sleep(0.5)

        print(f"\n   📊 Events published: {len(published_events)}")
        print()

    except Exception as e:
        print(f"   ❌ Event publishing failed: {e}")
        return

    # Step 4: Simulate notification processing
    print("📡 Step 4: Processing Notifications")
    print("-" * 40)

    try:
        # Simulate checking for new events in streams
        from packages.orchestrator.redis_simple import get_simple_redis_client

        client = await get_simple_redis_client()

        # Check orders stream for our events
        orders_info = await client.get_stream_info("ragline:stream:orders")
        stream_length = orders_info.get("length", 0)

        print(f"   📊 Orders stream: {stream_length} total messages")

        if stream_length > 0:
            # Read recent messages to show what's available
            try:
                recent_messages = await client.client.xrevrange(
                    "ragline:stream:orders", count=3
                )

                print("   📨 Recent messages in stream:")
                for msg_id, fields in recent_messages:
                    event_type = fields.get(b"event_type", b"unknown").decode()
                    aggregate_id = fields.get(b"aggregate_id", b"unknown").decode()
                    print(f"      {msg_id.decode()}: {event_type} for {aggregate_id}")

            except Exception as e:
                print(f"   ⚠️  Could not read recent messages: {e}")

        await client.close()

        # Simulate event processing for each published event
        processed_notifications = 0

        for event_step, message_id in published_events:
            try:
                # Simulate getting event from stream
                event_data = {
                    "event_id": f"demo_{event_step.lower().replace(' ', '_')}",
                    "event_type": "order_status",
                    "tenant_id": tenant_id,
                    "user_id": customer_user,
                    "message_id": str(message_id) if message_id else "unknown",
                }

                # Get relevant connections
                recipients = notifier.connection_manager.get_connections_for_event(
                    event_data
                )

                print(f"   📧 {event_step}: {len(recipients)} recipients")
                for recipient in recipients:
                    print(
                        f"      📨 {recipient.client_id} ({recipient.connection_type})"
                    )

                if recipients:
                    # Simulate fan-out
                    await notifier._fanout_to_connections(event_data, recipients)
                    processed_notifications += 1

            except Exception as e:
                print(f"   ⚠️  Processing {event_step} failed: {e}")

        print(f"\n   📊 Processed notifications: {processed_notifications}")
        print()

    except Exception as e:
        print(f"   ❌ Notification processing failed: {e}")

    # Step 5: Show system statistics
    print("📊 Step 5: System Statistics")
    print("-" * 40)

    try:
        stats = await notifier.get_stats()

        print("   📈 Notifier Status:")
        notifier_stats = stats["notifier"]
        print(f"      Running: {notifier_stats['is_running']}")
        print(f"      Processed events: {notifier_stats['processed_events']}")
        print(f"      Failed events: {notifier_stats['failed_events']}")
        print(f"      Streams monitored: {notifier_stats['streams_monitored']}")

        print("\n   📈 Connection Statistics:")
        conn_stats = stats["connections"]
        print(f"      Total connections: {conn_stats['total_connections']}")
        print(f"      Healthy connections: {conn_stats['healthy_connections']}")
        print(f"      Messages sent: {conn_stats['total_messages_sent']}")
        print(f"      Success rate: {conn_stats['success_rate']:.1f}%")

        print("\n   📈 Connection Types:")
        for conn_type, count in conn_stats["connections_by_type"].items():
            print(f"      {conn_type}: {count} connections")

    except Exception as e:
        print(f"   ❌ Statistics collection failed: {e}")

    print()

    # Final summary
    print("🎉 SSE/WebSocket Notifier Demo Complete!")
    print("=" * 60)
    print("✨ RAGline Notification System Features:")
    print("   ✅ Redis streams subscription with consumer groups")
    print("   ✅ Connection management with health monitoring")
    print("   ✅ Event filtering based on tenant and subscriptions")
    print("   ✅ Fan-out to multiple client types (SSE, WebSocket)")
    print("   ✅ Backpressure handling and connection limits")
    print("   ✅ Comprehensive statistics and monitoring")
    print("   ✅ Integration with outbox pattern and event schemas")
    print()
    print("🚀 Infrastructure ready for Agent A's SSE/WebSocket endpoints!")
    print("📋 Flow: Database → Outbox → Streams → Notifier → SSE/WS Clients")


if __name__ == "__main__":
    asyncio.run(demo_notification_system())
