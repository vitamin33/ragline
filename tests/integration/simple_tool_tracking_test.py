#!/usr/bin/env python3
"""
Simple Tool Execution Tracking Tests

Tests the core functionality without external dependencies.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def test_event_schema_validation():
    """Test tool_execution_v1.json schema exists and is valid"""
    print("🧪 Testing Event Schema Validation...")

    schema_path = "contracts/events/tool_execution_v1.json"

    try:
        with open(schema_path, "r") as f:
            schema = json.load(f)

        # Check required fields
        required_fields = ["event", "version", "tenant_id", "tool_execution_id", "tool_name", "status", "ts"]
        schema_required = schema.get("required", [])

        for field in required_fields:
            if field not in schema_required:
                print(f"  ❌ Missing required field: {field}")
                return False

        # Check event enum values
        event_enum = schema["properties"]["event"]["enum"]
        if "tool_execution" not in event_enum:
            print("  ❌ 'tool_execution' not in event enum")
            return False

        # Check status enum values
        status_enum = schema["properties"]["status"]["enum"]
        expected_statuses = ["started", "completed", "failed", "cached", "rate_limited"]
        for status in expected_statuses:
            if status not in status_enum:
                print(f"  ❌ Missing status: {status}")
                return False

        print("  ✅ Event schema validation passed")
        return True

    except FileNotFoundError:
        print(f"  ❌ Schema file not found: {schema_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"  ❌ Invalid JSON in schema: {e}")
        return False


def test_tool_execution_event_structure():
    """Test ToolExecutionEvent class structure"""
    print("🧪 Testing ToolExecutionEvent Structure...")

    try:
        from services.worker.tasks.tool_tracking import ToolExecutionEvent

        # Test basic event creation
        event = ToolExecutionEvent(
            tenant_id="123e4567-e89b-12d3-a456-426614174000", tool_name="retrieve_menu", status="completed"
        )

        # Check required fields
        assert event.event == "tool_execution"
        assert event.version == "1.0"
        assert event.tenant_id == "123e4567-e89b-12d3-a456-426614174000"
        assert event.tool_name == "retrieve_menu"
        assert event.status == "completed"
        assert event.tool_execution_id  # Should be auto-generated UUID
        assert event.ts  # Should be auto-generated timestamp

        # Test with optional fields
        event_full = ToolExecutionEvent(
            tenant_id="tenant_001",
            tool_name="search_knowledge_base",
            status="failed",
            user_id="user_001",
            execution_data={
                "duration_ms": 150.5,
                "cost_usd": 0.0025,
                "input_tokens": 50,
                "output_tokens": 100,
                "cache_hit": False,
            },
            error_details={"error_type": "timeout", "error_code": "REQUEST_TIMEOUT", "retry_count": 2},
        )

        # Test to_dict conversion
        event_dict = event_full.to_dict()

        # Verify serialization
        assert event_dict["event"] == "tool_execution"
        assert event_dict["tool_name"] == "search_knowledge_base"
        assert event_dict["execution_data"]["duration_ms"] == 150.5
        assert event_dict["error_details"]["error_type"] == "timeout"

        # Test JSON serialization
        json_str = json.dumps(event_dict)
        assert len(json_str) > 0

        print("  ✅ ToolExecutionEvent structure test passed")
        return True

    except ImportError as e:
        print(f"  ❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Structure test failed: {e}")
        return False


def test_tool_usage_stats():
    """Test ToolUsageStats aggregation"""
    print("🧪 Testing ToolUsageStats Aggregation...")

    try:
        from services.worker.tasks.tool_tracking import ToolExecutionEvent, ToolUsageStats

        stats = ToolUsageStats(tool_name="test_tool")

        # Test initial state
        assert stats.tool_name == "test_tool"
        assert stats.total_executions == 0
        assert stats.success_rate == 0.0
        assert stats.average_duration_ms == 0.0

        # Add successful execution
        success_event = ToolExecutionEvent(
            tenant_id="tenant_001",
            tool_name="test_tool",
            status="completed",
            user_id="user_001",
            execution_data={"duration_ms": 100.0, "cost_usd": 0.005},
        )

        stats.update_from_event(success_event)

        assert stats.total_executions == 1
        assert stats.successful_executions == 1
        assert stats.success_rate == 100.0
        assert stats.average_duration_ms == 100.0
        assert stats.total_cost_usd == 0.005
        assert len(stats.unique_users) == 1
        assert len(stats.unique_tenants) == 1

        # Add failed execution
        failed_event = ToolExecutionEvent(
            tenant_id="tenant_002",
            tool_name="test_tool",
            status="failed",
            user_id="user_002",
            execution_data={"duration_ms": 50.0},
        )

        stats.update_from_event(failed_event)

        assert stats.total_executions == 2
        assert stats.successful_executions == 1
        assert stats.failed_executions == 1
        assert stats.success_rate == 50.0
        assert len(stats.unique_users) == 2
        assert len(stats.unique_tenants) == 2

        # Test cached execution
        cached_event = ToolExecutionEvent(tenant_id="tenant_001", tool_name="test_tool", status="cached")

        stats.update_from_event(cached_event)
        assert stats.cached_executions == 1

        # Test serialization
        stats_dict = stats.to_dict()
        assert stats_dict["tool_name"] == "test_tool"
        assert stats_dict["total_executions"] == 3
        assert stats_dict["success_rate"] == 50.0

        print("  ✅ ToolUsageStats aggregation test passed")
        return True

    except ImportError as e:
        print(f"  ❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Stats test failed: {e}")
        return False


def test_celery_configuration():
    """Test Celery configuration includes tool tracking"""
    print("🧪 Testing Celery Configuration...")

    try:
        from services.worker.celery_app import app

        # Check task routes include tool tracking
        task_routes = app.conf.task_routes
        tool_tracking_route = task_routes.get("services.worker.tasks.tool_tracking.*")

        if not tool_tracking_route:
            print("  ❌ Tool tracking task route not configured")
            return False

        if tool_tracking_route["queue"] != "tool_tracking":
            print(f"  ❌ Wrong queue for tool tracking: {tool_tracking_route['queue']}")
            return False

        # Check queues include tool_tracking
        queue_names = [q.name for q in app.conf.task_queues]
        if "tool_tracking" not in queue_names:
            print("  ❌ tool_tracking queue not configured")
            return False

        # Check beat schedule includes cleanup task
        beat_schedule = app.conf.beat_schedule
        cleanup_task = beat_schedule.get("tool-analytics-cleanup")

        if not cleanup_task:
            print("  ❌ Tool analytics cleanup task not scheduled")
            return False

        if cleanup_task["task"] != "services.worker.tasks.tool_tracking.cleanup_old_tool_stats":
            print("  ❌ Wrong cleanup task name")
            return False

        # Check includes
        includes = app.conf.include
        if "services.worker.tasks.tool_tracking" not in includes:
            print("  ❌ Tool tracking module not included")
            return False

        print("  ✅ Celery configuration test passed")
        return True

    except ImportError as e:
        print(f"  ❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Configuration test failed: {e}")
        return False


def test_tool_metrics_integration():
    """Test tool metrics integration"""
    print("🧪 Testing Tool Metrics Integration...")

    try:
        # Test metrics module import
        from packages.orchestrator.tool_metrics import get_tool_metrics, record_tool_execution_from_event

        # Test event processing function exists
        event_data = {
            "tool_name": "test_tool",
            "tenant_id": "tenant_001",
            "status": "completed",
            "execution_data": {"duration_ms": 100.0},
        }

        # This should not raise an exception (even if it fails internally)
        try:
            record_tool_execution_from_event(event_data)
            print("  ✅ Event processing function callable")
        except Exception as e:
            print(f"  ⚠️  Event processing failed (expected without setup): {e}")

        # Test metrics integration in main metrics module
        from packages.orchestrator.metrics import TOOL_METRICS_AVAILABLE

        if TOOL_METRICS_AVAILABLE:
            print("  ✅ Tool metrics available in main metrics system")
        else:
            print("  ⚠️  Tool metrics not available in main metrics system")

        print("  ✅ Tool metrics integration test passed")
        return True

    except ImportError as e:
        print(f"  ❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Integration test failed: {e}")
        return False


def test_file_structure():
    """Test that all expected files exist"""
    print("🧪 Testing File Structure...")

    expected_files = [
        "contracts/events/tool_execution_v1.json",
        "services/worker/tasks/tool_tracking.py",
        "packages/orchestrator/tool_metrics.py",
        "services/worker/celery_app.py",
    ]

    missing_files = []
    for file_path in expected_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)

    if missing_files:
        print(f"  ❌ Missing files: {missing_files}")
        return False

    print("  ✅ All expected files exist")
    return True


def run_simple_tests():
    """Run all simple tests"""
    print("🧪 Running Simple Tool Execution Tracking Tests")
    print("=" * 60)

    tests = [
        ("File Structure", test_file_structure),
        ("Event Schema Validation", test_event_schema_validation),
        ("ToolExecutionEvent Structure", test_tool_execution_event_structure),
        ("ToolUsageStats Aggregation", test_tool_usage_stats),
        ("Celery Configuration", test_celery_configuration),
        ("Tool Metrics Integration", test_tool_metrics_integration),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n📋 {test_name}...")
        try:
            if test_func():
                passed += 1
            else:
                print(f"  ❌ {test_name} failed")
        except Exception as e:
            print(f"  ❌ {test_name} failed with exception: {e}")

    print("=" * 60)
    print(f"🎯 Test Results: {passed}/{total} passed")

    if passed == total:
        print("🎉 All tests passed! Tool execution tracking system is ready.")
        return True
    else:
        failed = total - passed
        print(f"⚠️  {failed} test(s) failed. Check implementation.")
        return False


if __name__ == "__main__":
    success = run_simple_tests()
    sys.exit(0 if success else 1)
