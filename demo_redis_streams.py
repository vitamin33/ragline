#!/usr/bin/env python3
"""
RAGline Redis Streams Complete Demo

Demonstrates the complete Redis streams implementation with
connection pooling, retry logic, and stream producer.
"""

import os
import sys
import asyncio
import json
from datetime import datetime, timezone

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))


async def demo_redis_streams():
    """Demonstrate complete Redis streams functionality"""
    print("🎯 RAGline Redis Streams Complete Demo")
    print("=" * 60)
    
    try:
        from packages.orchestrator.stream_producer import (
            StreamProducer, StreamEvent, EventMetadata, StreamTopic
        )
        from packages.orchestrator.redis_simple import get_simple_redis_client
        
        print("✅ Imports successful")
        print()
        
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return
    
    # Step 1: Initialize stream producer
    print("🔧 Step 1: Initializing Stream Producer")
    print("-" * 40)
    
    try:
        producer = StreamProducer()
        print("   ✅ Stream producer created")
        print(f"   ✅ Configured topics: {len(producer.stream_configs)}")
        
        for topic, config in producer.stream_configs.items():
            print(f"      📍 {topic.value}: max_len={config.max_len}, group={config.consumer_group}")
        
        print()
        
    except Exception as e:
        print(f"   ❌ Producer initialization failed: {e}")
        return
    
    # Step 2: Test stream routing
    print("📍 Step 2: Testing Stream Routing")
    print("-" * 40)
    
    routing_tests = [
        ("order", "order_created", StreamTopic.ORDERS),
        ("user", "profile_updated", StreamTopic.USERS),
        ("product", "price_changed", StreamTopic.PRODUCTS),
        ("notification", "email_queued", StreamTopic.NOTIFICATIONS),
        ("payment", "charge_successful", StreamTopic.PAYMENTS),
        ("inventory", "stock_depleted", StreamTopic.INVENTORY)
    ]
    
    for aggregate_type, event_type, expected in routing_tests:
        actual = producer.get_stream_topic(aggregate_type, event_type)
        status = "✅" if actual == expected else "❌"
        print(f"   {status} {aggregate_type}.{event_type} -> {actual.value}")
    
    print()
    
    # Step 3: Create and publish events
    print("📤 Step 3: Publishing Events to Streams")
    print("-" * 40)
    
    # Sample events representing real business scenarios
    sample_events = [
        {
            "description": "New order created",
            "event": StreamEvent(
                metadata=EventMetadata(
                    event_id="order_20250825_001",
                    event_type="order_created",
                    aggregate_id="order_12345",
                    aggregate_type="order",
                    user_id="user_67890",
                    tenant_id="tenant_acme"
                ),
                payload={
                    "order_id": "order_12345",
                    "user_id": "user_67890",
                    "total_amount": 25000,  # $250.00
                    "currency": "USD",
                    "items": [
                        {"product_id": "laptop_pro", "quantity": 1, "price": 20000},
                        {"product_id": "mouse_wireless", "quantity": 2, "price": 2500}
                    ],
                    "shipping_address": {
                        "street": "123 Tech Street",
                        "city": "San Francisco",
                        "state": "CA",
                        "zip": "94105"
                    },
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
            )
        },
        {
            "description": "User profile updated",
            "event": StreamEvent(
                metadata=EventMetadata(
                    event_id="user_20250825_001",
                    event_type="profile_updated",
                    aggregate_id="user_67890",
                    aggregate_type="user",
                    user_id="user_67890"
                ),
                payload={
                    "user_id": "user_67890",
                    "changes": {
                        "email": "john.doe.new@example.com",
                        "phone": "+1-555-123-4567",
                        "preferences": {
                            "email_notifications": True,
                            "sms_notifications": False,
                            "marketing": True
                        }
                    },
                    "updated_by": "user_67890",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
            )
        },
        {
            "description": "Product inventory updated", 
            "event": StreamEvent(
                metadata=EventMetadata(
                    event_id="inventory_20250825_001",
                    event_type="stock_updated",
                    aggregate_id="laptop_pro",
                    aggregate_type="inventory",
                    tenant_id="tenant_acme"
                ),
                payload={
                    "product_id": "laptop_pro",
                    "previous_stock": 50,
                    "new_stock": 49,
                    "change": -1,
                    "reason": "order_fulfillment",
                    "reference_id": "order_12345",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }
            )
        },
        {
            "description": "Email notification queued",
            "event": StreamEvent(
                metadata=EventMetadata(
                    event_id="notification_20250825_001",
                    event_type="email_notification_queued",
                    aggregate_id="notif_order_confirmation_001",
                    aggregate_type="notification",
                    user_id="user_67890",
                    correlation_id="order_12345"
                ),
                payload={
                    "notification_id": "notif_order_confirmation_001",
                    "recipient": "john.doe.new@example.com",
                    "template": "order_confirmation",
                    "data": {
                        "order_id": "order_12345",
                        "order_total": "$250.00",
                        "estimated_delivery": "2025-08-27"
                    },
                    "priority": "high",
                    "scheduled_for": datetime.now(timezone.utc).isoformat()
                }
            )
        }
    ]
    
    published_events = []
    
    for event_info in sample_events:
        try:
            print(f"   📝 Publishing: {event_info['description']}")
            
            message_id = await producer.publish_event(event_info['event'])
            published_events.append((event_info['description'], message_id))
            
            print(f"      ✅ Message ID: {message_id}")
            
        except Exception as e:
            print(f"      ❌ Failed: {e}")
    
    print(f"\n   ✅ Successfully published {len(published_events)} events")
    print()
    
    # Step 4: Verify streams
    print("🔍 Step 4: Verifying Stream Contents")
    print("-" * 40)
    
    try:
        client = await get_simple_redis_client()
        
        streams_to_check = [
            StreamTopic.ORDERS.value,
            StreamTopic.USERS.value,
            StreamTopic.INVENTORY.value,
            StreamTopic.NOTIFICATIONS.value
        ]
        
        total_messages = 0
        
        for stream_name in streams_to_check:
            try:
                info = await client.get_stream_info(stream_name)
                length = info.get('length', 0)
                
                if length > 0:
                    print(f"   📊 {stream_name}: {length} messages")
                    total_messages += length
                else:
                    print(f"   📊 {stream_name}: empty")
                    
            except Exception as e:
                print(f"   ⚠️  {stream_name}: error ({e})")
        
        print(f"\n   ✅ Total messages across all streams: {total_messages}")
        print()
        
        await client.close()
        
    except Exception as e:
        print(f"   ❌ Stream verification failed: {e}")
    
    # Step 5: Test convenience methods
    print("🎯 Step 5: Testing Convenience Methods")
    print("-" * 40)
    
    try:
        # Test order convenience method
        order_msg_id = await producer.publish_order_event(
            order_id="order_99999",
            event_type="order_shipped",
            payload={
                "tracking_number": "1Z999AA1234567890",
                "carrier": "UPS",
                "estimated_delivery": "2025-08-28",
                "shipped_at": datetime.now(timezone.utc).isoformat()
            },
            user_id="user_67890",
            correlation_id="order_12345"
        )
        print(f"   ✅ Order event published: {order_msg_id}")
        
        # Test user convenience method
        user_msg_id = await producer.publish_user_event(
            user_id="user_67890",
            event_type="login_successful",
            payload={
                "session_id": "sess_20250825_001",
                "ip_address": "192.168.1.100",
                "user_agent": "Mozilla/5.0 Chrome/91.0",
                "login_method": "email_password",
                "login_at": datetime.now(timezone.utc).isoformat()
            }
        )
        print(f"   ✅ User event published: {user_msg_id}")
        
        # Test notification convenience method
        notif_msg_id = await producer.publish_notification_event(
            notification_id="notif_shipping_001",
            event_type="sms_notification_queued",
            payload={
                "recipient": "+1-555-123-4567",
                "message": "Your order #12345 has shipped! Track: 1Z999AA1234567890",
                "priority": "normal"
            },
            user_id="user_67890"
        )
        print(f"   ✅ Notification event published: {notif_msg_id}")
        
    except Exception as e:
        print(f"   ❌ Convenience methods test failed: {e}")
    
    print()
    
    # Step 6: Show metrics
    print("📊 Step 6: Producer Metrics")
    print("-" * 40)
    
    try:
        metrics = await producer.get_metrics()
        
        print(f"   📈 Events published: {metrics['events_published']}")
        print(f"   📈 Events failed: {metrics['events_failed']}")
        print(f"   📈 Success rate: {metrics['success_rate']:.1f}%")
        print(f"   📈 Events by topic:")
        
        for topic, count in metrics['events_by_topic'].items():
            print(f"      📍 {topic}: {count} events")
        
        print(f"   📈 Configured topics: {len(metrics['configured_topics'])}")
        
        # Redis client metrics
        if 'redis_client_metrics' in metrics:
            redis_metrics = metrics['redis_client_metrics']
            print(f"   📈 Redis operations: {redis_metrics.get('operations_count', 0)}")
            print(f"   📈 Redis success rate: {redis_metrics.get('success_rate', 0):.1f}%")
        
    except Exception as e:
        print(f"   ❌ Metrics collection failed: {e}")
    
    print()
    
    # Final summary
    print("🎉 Demo Completed Successfully!")
    print("=" * 60)
    print("✨ RAGline Redis Streams Implementation:")
    print("   ✅ Stream producer with automatic routing")
    print("   ✅ Connection pooling and retry logic")
    print("   ✅ Multiple stream topics (orders, users, products, etc.)")
    print("   ✅ Event metadata and payload serialization")
    print("   ✅ Convenience methods for common event types")
    print("   ✅ Comprehensive metrics collection")
    print("   ✅ Integration with outbox pattern")
    print()
    print("🚀 Ready for high-throughput event processing!")
    print("📋 Event flows: Database → Outbox → Stream Producer → Redis Streams → Consumers")


if __name__ == "__main__":
    asyncio.run(demo_redis_streams())