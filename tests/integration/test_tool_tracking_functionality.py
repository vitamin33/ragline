#!/usr/bin/env python3
"""
Tool Tracking Functionality Test

Tests core functionality that doesn't require external services.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def test_tool_execution_event_functionality():
    """Test ToolExecutionEvent creation and serialization"""
    print("🧪 Testing ToolExecutionEvent Functionality...")

    # Mock the dependencies that would cause import errors
    import types

    # Create mock modules
    mock_redis = types.ModuleType("redis")
    mock_redis.asyncio = types.ModuleType("asyncio")
    sys.modules["redis"] = mock_redis
    sys.modules["redis.asyncio"] = mock_redis.asyncio

    mock_celery = types.ModuleType("celery")
    mock_celery.Task = object
    mock_celery.utils = types.ModuleType("utils")
    mock_celery.utils.log = types.ModuleType("log")
    mock_celery.utils.log.get_task_logger = lambda x: types.ModuleType("logger")
    sys.modules["celery"] = mock_celery
    sys.modules["celery.utils"] = mock_celery.utils
    sys.modules["celery.utils.log"] = mock_celery.utils.log

    mock_prometheus = types.ModuleType("prometheus_client")
    for attr in ["Counter", "Gauge", "Histogram", "Info", "CollectorRegistry"]:
        setattr(mock_prometheus, attr, type)
    sys.modules["prometheus_client"] = mock_prometheus

    mock_psutil = types.ModuleType("psutil")
    mock_psutil.cpu_percent = lambda interval=None: 25.0
    mock_psutil.virtual_memory = lambda: types.SimpleNamespace(used=1024 * 1024 * 1024)
    sys.modules["psutil"] = mock_psutil

    try:
        from services.worker.tasks.tool_tracking import ToolExecutionEvent, ToolUsageStats

        # Test 1: Basic event creation
        event = ToolExecutionEvent(tenant_id="tenant_001", tool_name="retrieve_menu", status="completed")

        # Verify auto-generated fields
        assert event.tool_execution_id
        assert event.ts
        assert len(event.tool_execution_id) == 36  # UUID length
        assert event.ts.endswith("Z") or "+" in event.ts  # ISO format

        # Test 2: Event with full data
        full_event = ToolExecutionEvent(
            tenant_id="tenant_002",
            tool_name="search_knowledge_base",
            status="failed",
            user_id="user_001",
            execution_data={
                "duration_ms": 250.5,
                "input_tokens": 100,
                "output_tokens": 150,
                "cost_usd": 0.005,
                "cache_hit": False,
                "external_api_calls": 3,
                "memory_usage_mb": 128.0,
            },
            tool_parameters={"parameter_count": 4, "query_length": 50, "has_filters": True},
            result_metadata={
                "result_count": 0,  # Failed request
                "result_size_bytes": 0,
                "truncated": False,
            },
            error_details={
                "error_type": "timeout",
                "error_code": "REQUEST_TIMEOUT",
                "retry_count": 2,
                "circuit_breaker_state": "open",
            },
            context={
                "session_id": "sess_123",
                "conversation_turn": 5,
                "request_id": str(uuid.uuid4()),
                "worker_id": "worker_002",
                "model_name": "gpt-4",
                "source_ip": "10.0.1.100",
            },
            meta={
                "reason": "Knowledge base search timeout",
                "tags": ["search", "timeout", "knowledge_base"],
                "experiment_id": "exp_timeout_001",
            },
        )

        # Test 3: Serialization
        event_dict = full_event.to_dict()

        # Verify required fields
        assert event_dict["event"] == "tool_execution"
        assert event_dict["version"] == "1.0"
        assert event_dict["tool_name"] == "search_knowledge_base"
        assert event_dict["status"] == "failed"

        # Verify optional fields
        assert event_dict["execution_data"]["duration_ms"] == 250.5
        assert event_dict["error_details"]["error_type"] == "timeout"
        assert event_dict["context"]["model_name"] == "gpt-4"
        assert event_dict["meta"]["tags"] == ["search", "timeout", "knowledge_base"]

        # Test 4: JSON serialization
        json_str = json.dumps(event_dict, indent=2)
        assert len(json_str) > 1000  # Should be substantial JSON

        # Parse back and verify
        parsed = json.loads(json_str)
        assert parsed["tool_name"] == "search_knowledge_base"
        assert parsed["execution_data"]["cost_usd"] == 0.005

        print("  ✅ ToolExecutionEvent functionality test passed")
        return True

    except Exception as e:
        print(f"  ❌ ToolExecutionEvent functionality test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_tool_usage_stats_functionality():
    """Test ToolUsageStats aggregation logic"""
    print("🧪 Testing ToolUsageStats Functionality...")

    try:
        from services.worker.tasks.tool_tracking import ToolExecutionEvent, ToolUsageStats

        # Test 1: Initial state
        stats = ToolUsageStats(tool_name="analytics_test_tool")
        assert stats.total_executions == 0
        assert stats.success_rate == 0.0
        assert stats.average_duration_ms == 0.0
        assert stats.average_cost_usd == 0.0
        assert len(stats.unique_users) == 0
        assert len(stats.unique_tenants) == 0

        # Test 2: Add successful executions
        successful_executions = [
            {"user": "user_001", "tenant": "tenant_001", "duration": 100.0, "cost": 0.001},
            {"user": "user_002", "tenant": "tenant_001", "duration": 150.0, "cost": 0.002},
            {"user": "user_001", "tenant": "tenant_002", "duration": 75.0, "cost": 0.0015},
        ]

        for exec_data in successful_executions:
            event = ToolExecutionEvent(
                tenant_id=exec_data["tenant"],
                tool_name="analytics_test_tool",
                status="completed",
                user_id=exec_data["user"],
                execution_data={
                    "duration_ms": exec_data["duration"],
                    "cost_usd": exec_data["cost"],
                    "input_tokens": 50,
                    "output_tokens": 100,
                },
            )
            stats.update_from_event(event)

        # Verify aggregations
        assert stats.total_executions == 3
        assert stats.successful_executions == 3
        assert stats.failed_executions == 0
        assert stats.success_rate == 100.0
        assert stats.total_duration_ms == 325.0  # 100 + 150 + 75
        assert stats.average_duration_ms == 108.333333333334  # 325/3
        assert abs(stats.total_cost_usd - 0.0045) < 0.0001  # 0.001 + 0.002 + 0.0015
        assert len(stats.unique_users) == 2  # user_001, user_002
        assert len(stats.unique_tenants) == 2  # tenant_001, tenant_002

        # Test 3: Add failed execution
        failed_event = ToolExecutionEvent(
            tenant_id="tenant_003",
            tool_name="analytics_test_tool",
            status="failed",
            user_id="user_003",
            execution_data={"duration_ms": 200.0, "cost_usd": 0.001},
        )
        stats.update_from_event(failed_event)

        # Verify updated stats
        assert stats.total_executions == 4
        assert stats.successful_executions == 3
        assert stats.failed_executions == 1
        assert stats.success_rate == 75.0  # 3/4 * 100
        assert len(stats.unique_users) == 3
        assert len(stats.unique_tenants) == 3

        # Test 4: Add cached and rate limited executions
        cached_event = ToolExecutionEvent(
            tenant_id="tenant_001",
            tool_name="analytics_test_tool",
            status="cached",
            execution_data={"duration_ms": 5.0, "cache_hit": True},
        )
        stats.update_from_event(cached_event)

        rate_limited_event = ToolExecutionEvent(
            tenant_id="tenant_001", tool_name="analytics_test_tool", status="rate_limited"
        )
        stats.update_from_event(rate_limited_event)

        assert stats.total_executions == 6
        assert stats.cached_executions == 1
        assert stats.rate_limited_executions == 1

        # Test 5: Hourly usage tracking
        assert len(stats.hourly_usage) > 0  # Should have some hourly data

        # Test 6: Serialization
        stats_dict = stats.to_dict()

        assert stats_dict["tool_name"] == "analytics_test_tool"
        assert stats_dict["total_executions"] == 6
        assert stats_dict["success_rate"] == 50.0  # 3 successful out of 6 total
        assert stats_dict["unique_users_count"] == 3
        assert stats_dict["unique_tenants_count"] == 3
        assert "window_start" in stats_dict
        assert "last_updated" in stats_dict

        # Verify JSON serialization
        json_str = json.dumps(stats_dict, indent=2)
        parsed_stats = json.loads(json_str)
        assert parsed_stats["tool_name"] == "analytics_test_tool"

        print("  ✅ ToolUsageStats functionality test passed")
        return True

    except Exception as e:
        print(f"  ❌ ToolUsageStats functionality test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_event_schema_compliance():
    """Test that generated events comply with the schema"""
    print("🧪 Testing Event Schema Compliance...")

    try:
        from services.worker.tasks.tool_tracking import ToolExecutionEvent

        # Load schema
        with open("contracts/events/tool_execution_v1.json", "r") as f:
            schema = json.load(f)

        # Test various event configurations
        test_cases = [
            # Minimal required fields
            {"tenant_id": "tenant_001", "tool_name": "minimal_tool", "status": "started"},
            # Complete successful execution
            {
                "tenant_id": "tenant_002",
                "tool_name": "complete_tool",
                "status": "completed",
                "user_id": "user_001",
                "execution_data": {
                    "duration_ms": 125.5,
                    "input_tokens": 50,
                    "output_tokens": 100,
                    "cost_usd": 0.0025,
                    "cache_hit": False,
                    "external_api_calls": 2,
                    "memory_usage_mb": 64.0,
                },
                "tool_parameters": {"parameter_count": 3, "query_length": 25, "has_filters": True},
                "result_metadata": {
                    "result_count": 5,
                    "result_size_bytes": 2048,
                    "truncated": False,
                    "relevance_scores": [0.95, 0.87, 0.82, 0.75, 0.68],
                },
            },
            # Failed execution with errors
            {
                "tenant_id": "tenant_003",
                "tool_name": "failing_tool",
                "status": "failed",
                "error_details": {
                    "error_type": "api_error",
                    "error_code": "SERVICE_UNAVAILABLE",
                    "retry_count": 3,
                    "circuit_breaker_state": "open",
                },
            },
            # Cached execution
            {
                "tenant_id": "tenant_004",
                "tool_name": "cached_tool",
                "status": "cached",
                "execution_data": {"cache_hit": True, "duration_ms": 2.0},
            },
            # Rate limited execution
            {"tenant_id": "tenant_005", "tool_name": "limited_tool", "status": "rate_limited"},
        ]

        for i, test_case in enumerate(test_cases):
            event = ToolExecutionEvent(**test_case)
            event_dict = event.to_dict()

            # Verify required fields
            for required_field in schema["required"]:
                assert required_field in event_dict, f"Test case {i}: Missing required field {required_field}"

            # Verify field types and constraints
            assert event_dict["event"] in schema["properties"]["event"]["enum"]
            assert event_dict["status"] in schema["properties"]["status"]["enum"]

            # Verify UUID format for tenant_id and tool_execution_id
            assert len(event_dict["tenant_id"]) >= 32  # UUID-like
            assert len(event_dict["tool_execution_id"]) == 36  # Full UUID with dashes

            # Verify timestamp format
            assert "T" in event_dict["ts"]  # ISO 8601 format

            # Test JSON serialization
            json.dumps(event_dict)  # Should not raise exception

        print("  ✅ Event schema compliance test passed")
        return True

    except Exception as e:
        print(f"  ❌ Event schema compliance test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def run_functionality_tests():
    """Run all functionality tests"""
    print("🧪 Running Tool Tracking Functionality Tests")
    print("=" * 60)

    tests = [
        ("ToolExecutionEvent Functionality", test_tool_execution_event_functionality),
        ("ToolUsageStats Functionality", test_tool_usage_stats_functionality),
        ("Event Schema Compliance", test_event_schema_compliance),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n📋 {test_name}...")
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"  ❌ {test_name} failed with exception: {e}")
            import traceback

            traceback.print_exc()

    print("=" * 60)
    print(f"🎯 Test Results: {passed}/{total} passed")

    if passed == total:
        print("🎉 All functionality tests passed! Core logic is working correctly.")
        return True
    else:
        failed = total - passed
        print(f"⚠️  {failed} test(s) failed. Check implementation.")
        return False


if __name__ == "__main__":
    success = run_functionality_tests()

    if success:
        print("\n📊 Summary:")
        print("  ✅ Event structure and serialization working")
        print("  ✅ Analytics aggregation logic correct")
        print("  ✅ Schema compliance verified")
        print("  ✅ Ready for integration with Redis/Celery")

    sys.exit(0 if success else 1)
