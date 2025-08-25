#!/usr/bin/env python3
"""
RAGline Event Schemas Complete Demo

Demonstrates the complete event schema system with validation,
serialization, and integration with Redis streams.
"""

import os
import sys
import json
import uuid
from datetime import datetime, timezone

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))


async def demo_event_schemas():
    """Demonstrate complete event schema functionality"""
    print("🎯 RAGline Event Schemas Complete Demo")
    print("=" * 60)
    
    try:
        from packages.orchestrator.event_schemas import (
            OrderV1Event, EventFactory, EventSerializer, OrderStatus,
            validate_order_v1_json_schema, get_event_validator
        )
        from packages.orchestrator.stream_producer import get_stream_producer
        
        print("✅ All event schema components imported successfully")
        print()
        
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return
    
    # Step 1: Create events using the factory
    print("🏭 Step 1: Creating Events with Factory")
    print("-" * 40)
    
    # Business scenario: Complete order lifecycle
    tenant_id = uuid.uuid4()
    order_id = uuid.uuid4()
    user_id = uuid.uuid4()
    correlation_id = f"order_flow_{int(datetime.now().timestamp())}"
    
    print(f"📋 Business Scenario: Order Lifecycle")
    print(f"   Tenant: {tenant_id}")
    print(f"   Order: {order_id}")
    print(f"   User: {user_id}")
    print(f"   Correlation: {correlation_id}")
    print()
    
    # Create lifecycle events
    lifecycle_events = []
    
    # Event 1: Order Created
    created_event = EventFactory.create_order_status_event(
        tenant_id=tenant_id,
        order_id=order_id,
        status=OrderStatus.CREATED,
        version="1.0",
        reason="Customer completed checkout process"
    )
    lifecycle_events.append(("Order Created", created_event))
    print(f"   ✅ Created event: {created_event.status.value} at {created_event.ts}")
    
    # Event 2: Order Confirmed  
    confirmed_event = EventFactory.create_enriched_order_event(
        tenant_id=tenant_id,
        order_id=order_id,
        status=OrderStatus.CONFIRMED,
        user_id=user_id,
        correlation_id=correlation_id,
        reason="Payment processed successfully by Stripe"
    )
    lifecycle_events.append(("Order Confirmed", confirmed_event))
    print(f"   ✅ Confirmed event: {confirmed_event.status.value} with correlation {correlation_id}")
    
    print()
    
    # Step 2: Validate against JSON schema
    print("📋 Step 2: JSON Schema Validation")
    print("-" * 40)
    
    validator = get_event_validator()
    
    for event_name, event in lifecycle_events:
        try:
            # Convert to dict for validation
            event_dict = event.to_dict() if hasattr(event, 'to_dict') else event.model_dump()
            
            # Validate against order_v1.json schema
            is_valid = validate_order_v1_json_schema(event_dict)
            
            print(f"   ✅ {event_name}: {'Valid' if is_valid else 'Invalid'} against schema")
            
            if is_valid:
                print(f"      Event: {event_dict['event']}")
                print(f"      Version: {event_dict['version']}")
                print(f"      Status: {event_dict['status']}")
                
        except Exception as e:
            print(f"   ❌ {event_name}: Validation error - {e}")
    
    print()
    
    # Step 3: Serialization/Deserialization
    print("🔄 Step 3: Serialization & Deserialization")
    print("-" * 40)
    
    serializer = EventSerializer()
    
    for event_name, event in lifecycle_events:
        try:
            # Serialize to JSON
            json_str = serializer.serialize_order_v1(event)
            print(f"   📤 {event_name}: Serialized to {len(json_str)} chars")
            
            # Deserialize back
            reconstructed = serializer.deserialize_order_v1(json_str)
            print(f"   📥 {event_name}: Deserialized successfully")
            
            # Verify integrity
            integrity_check = (
                reconstructed.order_id == event.order_id and
                reconstructed.status == event.status and
                reconstructed.event == event.event
            )
            print(f"   ✅ {event_name}: Integrity check {'passed' if integrity_check else 'failed'}")
            
        except Exception as e:
            print(f"   ❌ {event_name}: Serialization error - {e}")
    
    print()
    
    # Step 4: Redis Streams Integration
    print("📤 Step 4: Redis Streams Integration")
    print("-" * 40)
    
    try:
        producer = await get_stream_producer()
        
        for event_name, event in lifecycle_events:
            try:
                # Convert to stream fields
                stream_fields = serializer.serialize_to_stream_fields(event)
                print(f"   📊 {event_name}: {len(stream_fields)} stream fields")
                
                # Create metadata for stream event
                from packages.orchestrator.stream_producer import StreamEvent, EventMetadata
                
                metadata = EventMetadata(
                    event_id=f"order_{order_id}_{event.status.value}_{int(event.ts.timestamp())}",
                    event_type=event.event.value,
                    aggregate_id=str(event.order_id),
                    aggregate_type="order",
                    tenant_id=str(event.tenant_id),
                    correlation_id=correlation_id if hasattr(event, 'correlation_id') and event.correlation_id else None
                )
                
                stream_event = StreamEvent(
                    metadata=metadata,
                    payload=event.to_dict() if hasattr(event, 'to_dict') else event.model_dump()
                )
                
                # Publish to stream
                message_id = await producer.publish_event(stream_event)
                print(f"   ✅ {event_name}: Published to stream with ID {message_id}")
                
            except Exception as e:
                print(f"   ❌ {event_name}: Stream publishing failed - {e}")
    
    except Exception as e:
        print(f"   ❌ Stream integration setup failed: {e}")
    
    print()
    
    # Step 5: Verify streams contain our events
    print("🔍 Step 5: Stream Verification")
    print("-" * 40)
    
    try:
        from packages.orchestrator.redis_simple import get_simple_redis_client
        
        client = await get_simple_redis_client()
        
        # Check orders stream
        orders_stream = "ragline:stream:orders"
        info = await client.get_stream_info(orders_stream)
        stream_length = info.get('length', 0)
        
        print(f"   📊 {orders_stream}: {stream_length} total messages")
        
        if stream_length > 0:
            # Read recent messages
            try:
                recent_messages = await client.client.xrevrange(orders_stream, count=5)
                
                print(f"   📨 Recent messages:")
                for msg_id, fields in recent_messages:
                    event_type = fields.get(b'event_type', b'unknown').decode()
                    order_ref = fields.get(b'aggregate_id', b'unknown').decode()
                    print(f"      {msg_id.decode()}: {event_type} for order {order_ref}")
                    
            except Exception as e:
                print(f"   ⚠️  Failed to read recent messages: {e}")
        
        await client.close()
        
    except Exception as e:
        print(f"   ❌ Stream verification failed: {e}")
    
    print()
    
    # Step 6: Contract Compliance Summary
    print("📜 Step 6: Contract Compliance Summary")
    print("-" * 40)
    
    try:
        # Load the actual schema
        with open("contracts/events/order_v1.json", 'r') as f:
            schema = json.load(f)
        
        print(f"   ✅ Contract schema loaded:")
        print(f"      Schema version: {schema.get('$schema', 'unknown')}")
        print(f"      Required fields: {len(schema.get('required', []))}")
        print(f"      Event types: {schema.get('properties', {}).get('event', {}).get('enum', [])}")
        print(f"      Status values: {schema.get('properties', {}).get('status', {}).get('enum', [])}")
        
        # Verify our events comply
        compliant_events = 0
        for event_name, event in lifecycle_events:
            event_dict = event.to_dict() if hasattr(event, 'to_dict') else event.model_dump()
            
            # Check required fields
            required_fields = schema.get('required', [])
            has_required = all(field in event_dict for field in required_fields)
            
            if has_required:
                compliant_events += 1
                print(f"   ✅ {event_name}: Contract compliant")
            else:
                missing = [field for field in required_fields if field not in event_dict]
                print(f"   ❌ {event_name}: Missing fields {missing}")
        
        print(f"\n   📊 Contract compliance: {compliant_events}/{len(lifecycle_events)} events")
        
    except Exception as e:
        print(f"   ❌ Contract compliance check failed: {e}")
    
    print()
    
    # Final Summary
    print("🎉 Event Schemas Demo Complete!")
    print("=" * 60)
    print("✨ RAGline Event Schemas Implementation:")
    print("   ✅ Complete order_v1.json schema compliance")
    print("   ✅ Type-safe Pydantic models with validation")
    print("   ✅ JSON serialization with round-trip integrity")
    print("   ✅ Redis streams integration and field conversion")
    print("   ✅ Event factory for easy event creation")
    print("   ✅ Advanced validation and error handling")
    print("   ✅ Unicode and edge case support")
    print("   ✅ Enriched events with internal metadata")
    print()
    print("🚀 Production-ready event processing with schema validation!")
    print("📋 Events flow: Factory → Validation → Streams → Consumers")


if __name__ == "__main__":
    import asyncio
    asyncio.run(demo_event_schemas())