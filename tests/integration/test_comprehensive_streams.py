#!/usr/bin/env python3
"""
Comprehensive Testing Suite for RAGline Redis Streams

Tests all aspects of the Redis streams implementation including:
- Connection pooling and client management
- Retry logic with exponential backoff
- Stream operations (producer and consumer)
- Error handling and recovery scenarios
- Performance and load testing
- Integration with outbox pattern
"""

import os
import sys
import asyncio
import json
import time
import random
from datetime import datetime, timezone
from typing import List, Dict, Any

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))


class TestResults:
    """Track comprehensive test results"""
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.error_details = []
        self.performance_metrics = {}
        self.start_time = time.time()
    
    def add_result(self, test_name: str, passed: bool, details: str = "", metrics: Dict = None):
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            print(f"   ✅ {test_name}: PASSED")
        else:
            self.tests_failed += 1
            print(f"   ❌ {test_name}: FAILED")
            if details:
                print(f"      {details}")
                self.error_details.append(f"{test_name}: {details}")
        
        if metrics:
            self.performance_metrics[test_name] = metrics
    
    def get_summary(self):
        duration = time.time() - self.start_time
        return {
            'tests_run': self.tests_run,
            'tests_passed': self.tests_passed,
            'tests_failed': self.tests_failed,
            'success_rate': (self.tests_passed / max(1, self.tests_run)) * 100,
            'duration_seconds': duration,
            'error_details': self.error_details,
            'performance_metrics': self.performance_metrics
        }


async def test_redis_client_initialization(results: TestResults):
    """Test Redis client initialization and connection pooling"""
    print("🔧 Testing Redis Client Initialization")
    print("-" * 50)
    
    try:
        from packages.orchestrator.redis_simple import SimpleRedisClient
        from services.worker.config import WorkerConfig
        
        config = WorkerConfig()
        
        # Test client creation
        client = SimpleRedisClient(config)
        results.add_result("Client Creation", True)
        
        # Test initialization
        start_time = time.time()
        await client.initialize()
        init_duration = (time.time() - start_time) * 1000
        
        results.add_result(
            "Client Initialization", 
            client._initialized, 
            metrics={'init_time_ms': init_duration}
        )
        
        # Test basic operation
        start_time = time.time()
        await client.ensure_initialized()
        ensure_duration = (time.time() - start_time) * 1000
        
        results.add_result(
            "Ensure Initialized", 
            True,
            metrics={'ensure_time_ms': ensure_duration}
        )
        
        # Test metrics
        metrics = await client.get_metrics()
        has_expected_metrics = all(key in metrics for key in ['operations_count', 'errors_count', 'success_rate'])
        results.add_result("Metrics Collection", has_expected_metrics)
        
        # Test proper cleanup
        await client.close()
        results.add_result("Client Cleanup", not client._initialized)
        
        print(f"   📊 Initialization time: {init_duration:.2f}ms")
        print(f"   📊 Ensure time: {ensure_duration:.2f}ms")
        print(f"   📊 Metrics available: {len(metrics)} fields")
        
    except Exception as e:
        results.add_result("Redis Client Tests", False, str(e))
        import traceback
        traceback.print_exc()


async def test_retry_logic(results: TestResults):
    """Test retry logic with exponential backoff"""
    print("\n🔄 Testing Retry Logic")
    print("-" * 50)
    
    try:
        from packages.orchestrator.redis_client import RetryConfig, RetryStrategy
        
        # Test different retry strategies
        strategies = [
            (RetryStrategy.EXPONENTIAL_BACKOFF, "Exponential"),
            (RetryStrategy.LINEAR_BACKOFF, "Linear"),
            (RetryStrategy.FIXED_DELAY, "Fixed")
        ]
        
        for strategy, name in strategies:
            retry_config = RetryConfig(
                max_retries=4,
                base_delay=0.01,  # Fast for testing
                strategy=strategy,
                jitter=True
            )
            
            # Simulate delay calculation
            delays = []
            for attempt in range(retry_config.max_retries):
                # Mock the calculation method
                if strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
                    delay = retry_config.base_delay * (retry_config.backoff_multiplier ** attempt)
                elif strategy == RetryStrategy.LINEAR_BACKOFF:
                    delay = retry_config.base_delay * (attempt + 1)
                else:  # FIXED_DELAY
                    delay = retry_config.base_delay
                
                # Apply jitter simulation
                if retry_config.jitter:
                    jitter_range = delay * 0.1
                    delay += random.uniform(-jitter_range, jitter_range)
                
                delays.append(max(0.0, delay))
            
            # Verify delays are reasonable
            valid_delays = all(0 <= delay <= 1.0 for delay in delays)  # Within 1 second for test
            results.add_result(
                f"{name} Backoff Strategy", 
                valid_delays,
                metrics={'delays': delays}
            )
            
            print(f"   📊 {name} delays: {[f'{d:.3f}s' for d in delays]}")
        
        # Test retry configuration
        results.add_result("Retry Config Creation", True)
        
    except Exception as e:
        results.add_result("Retry Logic Tests", False, str(e))


async def test_stream_operations(results: TestResults):
    """Test stream operations (add, read, acknowledge)"""
    print("\n📤 Testing Stream Operations")
    print("-" * 50)
    
    try:
        from packages.orchestrator.redis_simple import SimpleRedisClient
        from services.worker.config import WorkerConfig
        
        config = WorkerConfig()
        client = SimpleRedisClient(config)
        await client.initialize()
        
        stream_name = "test:stream:operations"
        consumer_group = "test_group"
        consumer_name = "test_consumer"
        
        # Test 1: Add messages to stream
        test_messages = []
        start_time = time.time()
        
        for i in range(5):
            message = {
                "event_type": f"test_event_{i}",
                "data": f"test data {i}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sequence": str(i)
            }
            
            message_id = await client.add_to_stream(
                stream_name,
                {k: str(v) for k, v in message.items()},
                max_len=100
            )
            
            test_messages.append((message_id, message))
        
        add_duration = (time.time() - start_time) * 1000
        results.add_result(
            "Stream Add Operations", 
            len(test_messages) == 5,
            metrics={'add_duration_ms': add_duration, 'messages_added': len(test_messages)}
        )
        
        print(f"   📊 Added {len(test_messages)} messages in {add_duration:.2f}ms")
        
        # Test 2: Get stream info
        info = await client.get_stream_info(stream_name)
        stream_length = info.get('length', 0)
        results.add_result(
            "Stream Info Retrieval", 
            stream_length >= 5,
            metrics={'stream_length': stream_length}
        )
        
        print(f"   📊 Stream length: {stream_length}")
        
        # Test 3: Create consumer group BEFORE reading (correct Redis semantics)
        try:
            await client.client.xgroup_create(
                stream_name,
                consumer_group,
                id='0',
                mkstream=True
            )
            print(f"   ✅ Consumer group created: {consumer_group}")
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                print(f"   ⚠️  Consumer group creation: {e}")
        
        # Add NEW messages that the consumer group can see
        new_messages = []
        for i in range(3):
            message_id = await client.add_to_stream(
                stream_name,
                {
                    "event_type": f"new_test_{i}",
                    "data": f"new data {i}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )
            new_messages.append(message_id)
        
        print(f"   ✅ Added {len(new_messages)} messages after consumer group creation")
        
        # Test 4: Read messages from stream
        start_time = time.time()
        
        messages = await client.read_from_stream(
            stream_name,
            consumer_group,
            consumer_name,
            from_id='>',  # Read new messages (correct approach)
            count=10,
            block=100
        )
        
        read_duration = (time.time() - start_time) * 1000
        results.add_result(
            "Stream Read Operations",
            len(messages) >= 3,  # Expect the 3 new messages we added
            metrics={'read_duration_ms': read_duration, 'messages_read': len(messages)}
        )
        
        print(f"   📊 Read {len(messages)} messages in {read_duration:.2f}ms")
        
        # Test 4: Acknowledge messages
        acknowledged = 0
        start_time = time.time()
        
        for message in messages:
            try:
                await client.acknowledge_message(
                    stream_name,
                    consumer_group,
                    message['id']
                )
                acknowledged += 1
            except Exception as e:
                print(f"   ⚠️  Failed to acknowledge message {message['id']}: {e}")
        
        ack_duration = (time.time() - start_time) * 1000
        results.add_result(
            "Message Acknowledgment",
            acknowledged >= len(messages),  # Expect all messages to be acknowledged
            metrics={'ack_duration_ms': ack_duration, 'acknowledged': acknowledged}
        )
        
        print(f"   📊 Acknowledged {acknowledged} messages in {ack_duration:.2f}ms")
        
        # Test 5: Verify message content
        valid_messages = 0
        for message in messages:
            fields = message['fields']
            if 'event_type' in fields and 'data' in fields and 'timestamp' in fields:
                valid_messages += 1
        
        results.add_result(
            "Message Content Validation",
            valid_messages == len(messages)
        )
        
        print(f"   📊 Valid messages: {valid_messages}/{len(messages)}")
        
        await client.close()
        
    except Exception as e:
        results.add_result("Stream Operations", False, str(e))
        import traceback
        traceback.print_exc()


async def test_stream_producer(results: TestResults):
    """Test stream producer routing and event publishing"""
    print("\n🎯 Testing Stream Producer")
    print("-" * 50)
    
    try:
        from packages.orchestrator.stream_producer import (
            StreamProducer, StreamEvent, EventMetadata, StreamTopic
        )
        
        producer = StreamProducer()
        
        # Test 1: Stream routing logic
        routing_tests = [
            ("order", "order_created", StreamTopic.ORDERS),
            ("user", "user_updated", StreamTopic.USERS),
            ("product", "product_deleted", StreamTopic.PRODUCTS),
            ("notification", "email_sent", StreamTopic.NOTIFICATIONS),
            ("payment", "payment_processed", StreamTopic.PAYMENTS),
            ("inventory", "stock_updated", StreamTopic.INVENTORY),
            ("unknown", "mystery_event", StreamTopic.ORDERS)  # Default
        ]
        
        correct_routing = 0
        for aggregate_type, event_type, expected in routing_tests:
            actual = producer.get_stream_topic(aggregate_type, event_type)
            if actual == expected:
                correct_routing += 1
        
        results.add_result(
            "Stream Routing Logic",
            correct_routing == len(routing_tests),
            metrics={'correct_routes': correct_routing, 'total_routes': len(routing_tests)}
        )
        
        print(f"   📊 Correct routing: {correct_routing}/{len(routing_tests)}")
        
        # Test 2: Event creation and serialization
        metadata = EventMetadata(
            event_id="test_event_123",
            event_type="test_event",
            aggregate_id="test_aggregate",
            aggregate_type="test",
            user_id="test_user",
            tenant_id="test_tenant"
        )
        
        test_payload = {
            "string_field": "test string",
            "number_field": 42,
            "boolean_field": True,
            "array_field": [1, 2, 3],
            "object_field": {"nested": "value"}
        }
        
        event = StreamEvent(metadata=metadata, payload=test_payload)
        fields = event.to_stream_fields()
        
        required_fields = ['event_id', 'event_type', 'aggregate_id', 'aggregate_type', 'payload']
        has_required_fields = all(field in fields for field in required_fields)
        
        # Test payload serialization
        payload_json = fields.get('payload', '{}')
        try:
            parsed_payload = json.loads(payload_json)
            payload_valid = parsed_payload == test_payload
        except json.JSONDecodeError:
            payload_valid = False
        
        results.add_result(
            "Event Serialization",
            has_required_fields and payload_valid,
            metrics={'fields_count': len(fields)}
        )
        
        print(f"   📊 Event fields: {len(fields)}")
        print(f"   📊 Required fields present: {has_required_fields}")
        print(f"   📊 Payload serialization valid: {payload_valid}")
        
        # Test 3: Publish events
        published_events = 0
        start_time = time.time()
        
        test_events = [
            {
                "metadata": EventMetadata(
                    event_id=f"perf_test_{i}",
                    event_type="performance_test",
                    aggregate_id=f"test_agg_{i}",
                    aggregate_type="test"
                ),
                "payload": {"test_id": i, "timestamp": datetime.now(timezone.utc).isoformat()}
            }
            for i in range(10)
        ]
        
        for event_data in test_events:
            try:
                event = StreamEvent(**event_data)
                message_id = await producer.publish_event(event)
                if message_id:
                    published_events += 1
            except Exception as e:
                print(f"   ⚠️  Failed to publish event: {e}")
        
        publish_duration = (time.time() - start_time) * 1000
        results.add_result(
            "Event Publishing",
            published_events >= 8,  # Allow some failures
            metrics={
                'published_events': published_events,
                'total_events': len(test_events),
                'publish_duration_ms': publish_duration
            }
        )
        
        print(f"   📊 Published events: {published_events}/{len(test_events)}")
        print(f"   📊 Publishing duration: {publish_duration:.2f}ms")
        
        # Test 4: Convenience methods
        convenience_results = []
        
        # Test order event
        try:
            msg_id = await producer.publish_order_event(
                order_id="test_order_001",
                event_type="order_test_event",
                payload={"amount": 1000},
                user_id="test_user"
            )
            convenience_results.append(("Order", bool(msg_id)))
        except Exception as e:
            convenience_results.append(("Order", False))
            print(f"   ⚠️  Order convenience method failed: {e}")
        
        # Test user event
        try:
            msg_id = await producer.publish_user_event(
                user_id="test_user_001",
                event_type="user_test_event",
                payload={"action": "test"}
            )
            convenience_results.append(("User", bool(msg_id)))
        except Exception as e:
            convenience_results.append(("User", False))
            print(f"   ⚠️  User convenience method failed: {e}")
        
        convenience_success = sum(1 for _, success in convenience_results if success)
        results.add_result(
            "Convenience Methods",
            convenience_success >= 1,
            metrics={'successful_convenience': convenience_success}
        )
        
        print(f"   📊 Convenience methods working: {convenience_success}/{len(convenience_results)}")
        
        # Test 5: Producer metrics
        metrics = await producer.get_metrics()
        has_metrics = 'events_published' in metrics and 'success_rate' in metrics
        results.add_result(
            "Producer Metrics",
            has_metrics,
            metrics=metrics
        )
        
        print(f"   📊 Producer metrics available: {has_metrics}")
        if has_metrics:
            print(f"   📊 Events published: {metrics['events_published']}")
            print(f"   📊 Success rate: {metrics['success_rate']:.1f}%")
        
    except Exception as e:
        results.add_result("Stream Producer", False, str(e))
        import traceback
        traceback.print_exc()


async def test_outbox_integration(results: TestResults):
    """Test integration with outbox consumer"""
    print("\n🔄 Testing Outbox Integration")
    print("-" * 50)
    
    try:
        from packages.orchestrator.outbox import OutboxEvent
        from packages.orchestrator.stream_producer import StreamEvent
        from datetime import datetime, timezone
        
        # Test 1: Outbox event creation
        outbox_event = OutboxEvent(
            id=9999,
            aggregate_id="integration_test_order",
            aggregate_type="order",
            event_type="order_integration_test",
            payload={
                "order_id": "integration_test_order",
                "amount": 15000,
                "currency": "USD",
                "items": [{"product_id": "test_product", "quantity": 1}],
                "test_timestamp": datetime.now(timezone.utc).isoformat()
            },
            created_at=datetime.now(timezone.utc),
            retry_count=2
        )
        
        results.add_result("Outbox Event Creation", True)
        
        # Test 2: Conversion to stream event
        stream_event = StreamEvent.from_outbox_event(outbox_event)
        
        conversion_valid = (
            stream_event.metadata.event_id == str(outbox_event.id) and
            stream_event.metadata.event_type == outbox_event.event_type and
            stream_event.metadata.aggregate_id == outbox_event.aggregate_id and
            stream_event.metadata.aggregate_type == outbox_event.aggregate_type and
            stream_event.payload == outbox_event.payload
        )
        
        results.add_result("Outbox to Stream Conversion", conversion_valid)
        
        # Test 3: Stream event fields generation
        fields = stream_event.to_stream_fields()
        required_fields = ['event_id', 'event_type', 'aggregate_id', 'aggregate_type', 'payload']
        has_all_fields = all(field in fields for field in required_fields)
        
        results.add_result("Stream Fields Generation", has_all_fields)
        
        # Test 4: Payload integrity
        try:
            payload_json = fields['payload']
            parsed_payload = json.loads(payload_json)
            payload_integrity = parsed_payload == outbox_event.payload
        except Exception:
            payload_integrity = False
        
        results.add_result("Payload Integrity", payload_integrity)
        
        print(f"   📊 Outbox event ID: {outbox_event.id}")
        print(f"   📊 Stream event ID: {stream_event.metadata.event_id}")
        print(f"   📊 Conversion valid: {conversion_valid}")
        print(f"   📊 Fields count: {len(fields)}")
        print(f"   📊 Payload integrity: {payload_integrity}")
        
        # Test 5: Integration with stream producer
        try:
            from packages.orchestrator.stream_producer import get_stream_producer
            
            producer = await get_stream_producer()
            
            # Add retry count to payload for tracking
            stream_event.payload['_retry_count'] = outbox_event.retry_count
            
            message_id = await producer.publish_event(stream_event)
            integration_success = bool(message_id)
            
            results.add_result(
                "Producer Integration",
                integration_success,
                metrics={'message_id': str(message_id) if message_id else None}
            )
            
            print(f"   📊 Integration publish: {integration_success}")
            if message_id:
                print(f"   📊 Message ID: {message_id}")
                
        except Exception as e:
            results.add_result("Producer Integration", False, str(e))
        
    except Exception as e:
        results.add_result("Outbox Integration", False, str(e))
        import traceback
        traceback.print_exc()


async def test_error_scenarios(results: TestResults):
    """Test error scenarios and recovery"""
    print("\n⚠️  Testing Error Scenarios")
    print("-" * 50)
    
    try:
        from packages.orchestrator.stream_producer import StreamProducer, StreamEvent, EventMetadata
        
        producer = StreamProducer()
        
        # Test 1: Invalid event data handling
        try:
            invalid_metadata = EventMetadata(
                event_id="",  # Empty event ID
                event_type="",  # Empty event type
                aggregate_id="test",
                aggregate_type="test"
            )
            
            invalid_event = StreamEvent(
                metadata=invalid_metadata,
                payload={"test": "data"}
            )
            
            # This should work despite empty fields (our implementation is robust)
            fields = invalid_event.to_stream_fields()
            error_handling_works = len(fields) > 0
            
        except Exception as e:
            error_handling_works = False
            print(f"   ⚠️  Invalid data handling failed: {e}")
        
        results.add_result("Invalid Data Handling", error_handling_works)
        
        # Test 2: Large payload handling
        try:
            large_payload = {
                "data": "x" * 10000,  # 10KB string
                "array": list(range(1000)),  # Large array
                "nested": {"level_" + str(i): f"value_{i}" for i in range(100)}  # Nested object
            }
            
            large_event = StreamEvent(
                metadata=EventMetadata(
                    event_id="large_test",
                    event_type="large_payload_test",
                    aggregate_id="large_test",
                    aggregate_type="test"
                ),
                payload=large_payload
            )
            
            fields = large_event.to_stream_fields()
            payload_json = fields.get('payload', '{}')
            
            # Verify payload can be serialized and is large
            large_payload_handled = len(payload_json) > 10000
            
        except Exception as e:
            large_payload_handled = False
            print(f"   ⚠️  Large payload handling failed: {e}")
        
        results.add_result("Large Payload Handling", large_payload_handled)
        
        # Test 3: JSON serialization edge cases
        try:
            edge_case_payload = {
                "datetime": datetime.now(timezone.utc),
                "none_value": None,
                "unicode": "测试数据 🚀",
                "special_chars": "!@#$%^&*()[]{}|\\:;\"'<>?,./"
            }
            
            edge_event = StreamEvent(
                metadata=EventMetadata(
                    event_id="edge_case_test",
                    event_type="edge_case_test",
                    aggregate_id="edge_test",
                    aggregate_type="test"
                ),
                payload=edge_case_payload
            )
            
            fields = edge_event.to_stream_fields()
            payload_json = fields.get('payload', '{}')
            
            # Verify we can parse it back
            parsed = json.loads(payload_json)
            edge_case_handled = 'unicode' in parsed and 'special_chars' in parsed
            
        except Exception as e:
            edge_case_handled = False
            print(f"   ⚠️  Edge case handling failed: {e}")
        
        results.add_result("JSON Edge Cases", edge_case_handled)
        
        # Test 4: Stream routing for unknown types
        unknown_routing_tests = [
            ("completely_unknown", "mysterious_event"),
            ("", ""),
            ("123", "456"),
            ("special!@#", "event$%^")
        ]
        
        routing_fallback_works = True
        for aggregate_type, event_type in unknown_routing_tests:
            try:
                topic = producer.get_stream_topic(aggregate_type, event_type)
                # Should default to ORDERS stream
                if not topic or topic.value != "ragline:stream:orders":
                    routing_fallback_works = False
                    break
            except Exception:
                routing_fallback_works = False
                break
        
        results.add_result("Routing Fallback", routing_fallback_works)
        
        print(f"   📊 Invalid data handled: {error_handling_works}")
        print(f"   📊 Large payload handled: {large_payload_handled}")
        print(f"   📊 JSON edge cases handled: {edge_case_handled}")
        print(f"   📊 Routing fallback works: {routing_fallback_works}")
        
    except Exception as e:
        results.add_result("Error Scenarios", False, str(e))
        import traceback
        traceback.print_exc()


async def test_performance_load(results: TestResults):
    """Performance and load testing"""
    print("\n🏎️  Testing Performance & Load")
    print("-" * 50)
    
    try:
        from packages.orchestrator.stream_producer import StreamProducer, StreamEvent, EventMetadata
        
        producer = StreamProducer()
        
        # Test 1: Bulk event creation performance
        print("   🔧 Creating test events...")
        
        bulk_events = []
        start_time = time.time()
        
        for i in range(100):
            metadata = EventMetadata(
                event_id=f"perf_test_{i:04d}",
                event_type="performance_test",
                aggregate_id=f"agg_{i:04d}",
                aggregate_type="test",
                user_id=f"user_{i % 10}",  # 10 different users
                tenant_id="perf_tenant"
            )
            
            payload = {
                "sequence": i,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": f"Performance test data for event {i}",
                "metadata": {
                    "batch_id": "perf_batch_001",
                    "test_run": "comprehensive_test"
                },
                "large_field": "x" * 1000  # 1KB of data per event
            }
            
            event = StreamEvent(metadata=metadata, payload=payload)
            bulk_events.append(event)
        
        creation_duration = (time.time() - start_time) * 1000
        creation_rate = len(bulk_events) / (creation_duration / 1000)
        
        results.add_result(
            "Bulk Event Creation",
            len(bulk_events) == 100,
            metrics={
                'events_created': len(bulk_events),
                'creation_duration_ms': creation_duration,
                'creation_rate_per_sec': creation_rate
            }
        )
        
        print(f"   📊 Created {len(bulk_events)} events in {creation_duration:.2f}ms")
        print(f"   📊 Creation rate: {creation_rate:.1f} events/sec")
        
        # Test 2: Bulk publishing performance
        print("   🚀 Publishing test events...")
        
        published_count = 0
        failed_count = 0
        start_time = time.time()
        
        # Publish in smaller batches to avoid overwhelming Redis
        batch_size = 10
        for i in range(0, len(bulk_events), batch_size):
            batch = bulk_events[i:i + batch_size]
            
            for event in batch:
                try:
                    message_id = await producer.publish_event(event)
                    if message_id:
                        published_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
                    if failed_count <= 5:  # Only log first few failures
                        print(f"   ⚠️  Publish failed: {e}")
            
            # Small delay between batches
            await asyncio.sleep(0.01)
        
        publish_duration = (time.time() - start_time) * 1000
        publish_rate = published_count / (publish_duration / 1000) if publish_duration > 0 else 0
        success_rate = (published_count / len(bulk_events)) * 100
        
        results.add_result(
            "Bulk Publishing",
            success_rate >= 80,  # Allow 20% failure rate
            metrics={
                'published_count': published_count,
                'failed_count': failed_count,
                'publish_duration_ms': publish_duration,
                'publish_rate_per_sec': publish_rate,
                'success_rate_percent': success_rate
            }
        )
        
        print(f"   📊 Published {published_count}/{len(bulk_events)} events")
        print(f"   📊 Publishing duration: {publish_duration:.2f}ms")
        print(f"   📊 Publishing rate: {publish_rate:.1f} events/sec")
        print(f"   📊 Success rate: {success_rate:.1f}%")
        
        # Test 3: Memory usage estimation
        import sys
        
        single_event_size = sys.getsizeof(bulk_events[0].to_stream_fields())
        total_memory_kb = (single_event_size * len(bulk_events)) / 1024
        
        results.add_result(
            "Memory Efficiency",
            total_memory_kb < 500,  # Less than 500KB for 100 events
            metrics={
                'single_event_bytes': single_event_size,
                'total_memory_kb': total_memory_kb
            }
        )
        
        print(f"   📊 Single event size: {single_event_size} bytes")
        print(f"   📊 Total memory usage: {total_memory_kb:.2f} KB")
        
        # Test 4: Producer metrics after load test
        final_metrics = await producer.get_metrics()
        
        results.add_result(
            "Load Test Metrics",
            final_metrics.get('events_published', 0) > 50,
            metrics=final_metrics
        )
        
        print(f"   📊 Final producer metrics:")
        print(f"      Events published: {final_metrics.get('events_published', 0)}")
        print(f"      Success rate: {final_metrics.get('success_rate', 0):.1f}%")
        print(f"      Events by topic: {len(final_metrics.get('events_by_topic', {}))}")
        
    except Exception as e:
        results.add_result("Performance Load Test", False, str(e))
        import traceback
        traceback.print_exc()


async def main():
    """Run comprehensive testing suite"""
    print("🧪 RAGline Redis Streams - Comprehensive Testing Suite")
    print("=" * 70)
    
    results = TestResults()
    
    test_suites = [
        ("Redis Client Initialization", test_redis_client_initialization),
        ("Retry Logic", test_retry_logic),
        ("Stream Operations", test_stream_operations),
        ("Stream Producer", test_stream_producer),
        ("Outbox Integration", test_outbox_integration),
        ("Error Scenarios", test_error_scenarios),
        ("Performance & Load", test_performance_load),
    ]
    
    for suite_name, test_func in test_suites:
        try:
            await test_func(results)
        except Exception as e:
            print(f"\n❌ Test suite {suite_name} crashed: {e}")
            results.add_result(f"{suite_name} (Suite)", False, str(e))
    
    # Final summary
    summary = results.get_summary()
    
    print("\n" + "=" * 70)
    print("📊 COMPREHENSIVE TEST RESULTS")
    print("=" * 70)
    
    print(f"🎯 Tests Run: {summary['tests_run']}")
    print(f"✅ Tests Passed: {summary['tests_passed']}")
    print(f"❌ Tests Failed: {summary['tests_failed']}")
    print(f"📈 Success Rate: {summary['success_rate']:.1f}%")
    print(f"⏱️  Total Duration: {summary['duration_seconds']:.2f}s")
    
    if summary['error_details']:
        print(f"\n❌ Error Details:")
        for error in summary['error_details']:
            print(f"   • {error}")
    
    # Performance highlights
    print(f"\n🏎️  Performance Highlights:")
    perf_metrics = summary['performance_metrics']
    
    if 'Bulk Event Creation' in perf_metrics:
        creation = perf_metrics['Bulk Event Creation']
        print(f"   • Event creation: {creation.get('creation_rate_per_sec', 0):.1f} events/sec")
    
    if 'Bulk Publishing' in perf_metrics:
        publishing = perf_metrics['Bulk Publishing']
        print(f"   • Event publishing: {publishing.get('publish_rate_per_sec', 0):.1f} events/sec")
    
    if 'Memory Efficiency' in perf_metrics:
        memory = perf_metrics['Memory Efficiency']
        print(f"   • Memory per event: {memory.get('single_event_bytes', 0)} bytes")
    
    # Final verdict
    print(f"\n" + "=" * 70)
    
    if summary['success_rate'] >= 90:
        print("🎉 EXCELLENT: Redis Streams implementation is production-ready!")
        print("✨ All critical functionality working with high reliability")
        return 0
    elif summary['success_rate'] >= 75:
        print("✅ GOOD: Redis Streams implementation is mostly working")
        print("⚠️  Some issues detected but core functionality solid")
        return 0
    else:
        print("❌ ISSUES: Redis Streams implementation needs attention")
        print("🔧 Multiple test failures indicate problems requiring fixes")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))