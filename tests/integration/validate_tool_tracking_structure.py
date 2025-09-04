#!/usr/bin/env python3
"""
Tool Tracking Structure Validation

Validates the implementation structure without requiring external dependencies.
"""

import ast
import json
import os
import sys


def validate_event_schema():
    """Validate tool_execution_v1.json schema structure"""
    print("🔍 Validating Event Schema...")

    schema_path = "contracts/events/tool_execution_v1.json"

    try:
        with open(schema_path, "r") as f:
            schema = json.load(f)

        # Check schema structure
        assert "$schema" in schema, "Missing $schema"
        assert schema["type"] == "object", "Schema type should be object"
        assert "required" in schema, "Missing required fields list"
        assert "properties" in schema, "Missing properties"

        # Validate required fields
        required_fields = ["event", "version", "tenant_id", "tool_execution_id", "tool_name", "status", "ts"]
        for field in required_fields:
            assert field in schema["required"], f"Missing required field: {field}"
            assert field in schema["properties"], f"Missing property definition: {field}"

        # Validate event enum
        assert "enum" in schema["properties"]["event"], "Event should have enum values"
        assert "tool_execution" in schema["properties"]["event"]["enum"], "Missing tool_execution in event enum"

        # Validate status enum
        expected_statuses = ["started", "completed", "failed", "cached", "rate_limited"]
        status_enum = schema["properties"]["status"]["enum"]
        for status in expected_statuses:
            assert status in status_enum, f"Missing status: {status}"

        # Validate complex objects
        complex_objects = ["execution_data", "tool_parameters", "result_metadata", "error_details", "context"]
        for obj in complex_objects:
            if obj in schema["properties"]:
                assert schema["properties"][obj]["type"] == "object", f"{obj} should be object type"

        print("  ✅ Event schema structure valid")
        return True

    except Exception as e:
        print(f"  ❌ Schema validation failed: {e}")
        return False


def validate_tool_tracking_file():
    """Validate tool_tracking.py file structure"""
    print("🔍 Validating Tool Tracking Implementation...")

    file_path = "services/worker/tasks/tool_tracking.py"

    try:
        with open(file_path, "r") as f:
            content = f.read()

        # Parse the file to check structure
        tree = ast.parse(content)

        # Find classes and functions
        classes = []
        functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                functions.append(node.name)

        # Check required classes
        required_classes = ["ToolExecutionEvent", "ToolUsageStats", "ToolExecutionTracker"]
        for cls in required_classes:
            assert cls in classes, f"Missing class: {cls}"

        # Check required functions (including async)
        required_functions = ["get_tool_tracker", "track_tool_execution", "get_tool_analytics"]
        for func in required_functions:
            # Check both regular function and async function definitions
            func_found = func in functions or f"async def {func}(" in content or f"def {func}(" in content
            assert func_found, f"Missing function: {func}"

        # Check for specific method signatures by searching content
        assert "def to_dict(self)" in content, "ToolExecutionEvent missing to_dict method"
        assert "def update_from_event(self" in content, "ToolUsageStats missing update_from_event method"
        assert (
            "async def track_tool_execution(self" in content
        ), "ToolExecutionTracker missing track_tool_execution method"

        # Check for Celery tasks
        assert "@app.task" in content, "Missing Celery task decorators"
        assert "track_tool_execution" in content, "Missing track_tool_execution task"
        assert "get_tool_analytics" in content, "Missing get_tool_analytics task"

        print("  ✅ Tool tracking implementation structure valid")
        return True

    except Exception as e:
        print(f"  ❌ Tool tracking validation failed: {e}")
        return False


def validate_tool_metrics_file():
    """Validate tool_metrics.py file structure"""
    print("🔍 Validating Tool Metrics Implementation...")

    file_path = "packages/orchestrator/tool_metrics.py"

    try:
        with open(file_path, "r") as f:
            content = f.read()

        tree = ast.parse(content)

        classes = []
        functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                functions.append(node.name)

        # Check required classes
        assert "ToolMetrics" in classes, "Missing ToolMetrics class"

        # Check required functions
        required_functions = ["get_tool_metrics", "record_tool_execution_from_event"]
        for func in required_functions:
            assert func in functions, f"Missing function: {func}"

        # Check for metric initialization methods
        metric_methods = [
            "_init_execution_metrics",
            "_init_performance_metrics",
            "_init_usage_metrics",
            "_init_cost_metrics",
            "_init_resource_metrics",
            "_init_error_metrics",
        ]

        for method in metric_methods:
            assert method in content, f"Missing metrics method: {method}"

        # Check for Prometheus metric types
        prometheus_types = ["Counter", "Gauge", "Histogram"]
        for metric_type in prometheus_types:
            assert metric_type in content, f"Missing Prometheus metric type: {metric_type}"

        # Check for specific metrics
        key_metrics = [
            "tool_execution_duration",
            "tool_executions_total",
            "tool_success_rate",
            "tool_cost_usd",
            "tool_errors",
        ]

        for metric in key_metrics:
            assert metric in content, f"Missing key metric: {metric}"

        print("  ✅ Tool metrics implementation structure valid")
        return True

    except Exception as e:
        print(f"  ❌ Tool metrics validation failed: {e}")
        return False


def validate_celery_integration():
    """Validate Celery configuration includes tool tracking"""
    print("🔍 Validating Celery Integration...")

    file_path = "services/worker/celery_app.py"

    try:
        with open(file_path, "r") as f:
            content = f.read()

        # Check includes
        assert "services.worker.tasks.tool_tracking" in content, "Tool tracking not in includes"

        # Check task routes
        assert "services.worker.tasks.tool_tracking.*" in content, "Tool tracking task routes not configured"
        assert '"queue": "tool_tracking"' in content, "Tool tracking queue not configured"

        # Check queue definition
        assert 'Queue("tool_tracking"' in content, "Tool tracking queue not defined"
        assert 'Exchange("tool_tracking")' in content, "Tool tracking exchange not defined"

        # Check beat schedule
        assert "tool-analytics-cleanup" in content, "Tool analytics cleanup not scheduled"
        assert "cleanup_old_tool_stats" in content, "Cleanup task not configured"

        # Check Redis streams config
        assert "tool_executions" in content, "Tool executions stream not configured"
        assert "ragline:stream:tool_executions" in content, "Tool executions stream name not configured"

        print("  ✅ Celery integration structure valid")
        return True

    except Exception as e:
        print(f"  ❌ Celery integration validation failed: {e}")
        return False


def validate_metrics_integration():
    """Validate tool metrics integration with main metrics system"""
    print("🔍 Validating Metrics Integration...")

    # Check main metrics file
    metrics_file = "packages/orchestrator/metrics.py"

    try:
        with open(metrics_file, "r") as f:
            content = f.read()

        # Check tool metrics import
        assert "from .tool_metrics import get_tool_metrics" in content, "Tool metrics import missing"
        assert "TOOL_METRICS_AVAILABLE" in content, "Tool metrics availability check missing"

        # Check collector integration
        assert "self.tool_metrics = get_tool_metrics()" in content, "Tool metrics not integrated in collector"
        assert "collect_tool_metrics" in content, "collect_tool_metrics method missing"

        # Check metrics task integration
        metrics_task_file = "services/worker/tasks/metrics.py"

        with open(metrics_task_file, "r") as f:
            task_content = f.read()

        assert (
            "from .tool_tracking import get_tool_tracker" in task_content
        ), "Tool tracker import missing from metrics task"
        assert "TOOL_TRACKING_AVAILABLE" in task_content, "Tool tracking availability check missing"
        assert "tool_analytics = await tracker.get_tool_analytics" in task_content, "Tool analytics collection missing"

        print("  ✅ Metrics integration structure valid")
        return True

    except Exception as e:
        print(f"  ❌ Metrics integration validation failed: {e}")
        return False


def validate_code_quality():
    """Validate code quality aspects"""
    print("🔍 Validating Code Quality...")

    files_to_check = ["services/worker/tasks/tool_tracking.py", "packages/orchestrator/tool_metrics.py"]

    try:
        for file_path in files_to_check:
            with open(file_path, "r") as f:
                content = f.read()

            # Check for docstrings
            assert '"""' in content, f"Missing docstrings in {file_path}"

            # Check for error handling
            assert "try:" in content, f"Missing error handling in {file_path}"
            assert "except" in content, f"Missing exception handling in {file_path}"

            # Check for logging
            assert "logger" in content, f"Missing logging in {file_path}"

            # Check for type hints
            assert "Dict[str, Any]" in content, f"Missing type hints in {file_path}"
            assert "Optional[" in content, f"Missing Optional type hints in {file_path}"

        print("  ✅ Code quality checks passed")
        return True

    except Exception as e:
        print(f"  ❌ Code quality validation failed: {e}")
        return False


def run_structure_validation():
    """Run all structure validation tests"""
    print("🔍 Running Tool Tracking Structure Validation")
    print("=" * 60)

    validations = [
        ("Event Schema Structure", validate_event_schema),
        ("Tool Tracking Implementation", validate_tool_tracking_file),
        ("Tool Metrics Implementation", validate_tool_metrics_file),
        ("Celery Integration", validate_celery_integration),
        ("Metrics System Integration", validate_metrics_integration),
        ("Code Quality", validate_code_quality),
    ]

    passed = 0
    total = len(validations)

    for validation_name, validation_func in validations:
        print(f"\n📋 {validation_name}...")
        try:
            if validation_func():
                passed += 1
        except Exception as e:
            print(f"  ❌ {validation_name} failed with exception: {e}")

    print("=" * 60)
    print(f"🎯 Validation Results: {passed}/{total} passed")

    if passed == total:
        print("🎉 All validations passed! Implementation structure is correct.")
        return True
    else:
        failed = total - passed
        print(f"⚠️  {failed} validation(s) failed. Check implementation.")
        return False


if __name__ == "__main__":
    success = run_structure_validation()

    if success:
        print("\n💡 Next Steps:")
        print("  1. Set up virtual environment with dependencies")
        print("  2. Run integration tests with Redis and Celery")
        print("  3. Test with actual tool executions")
        print("  4. Validate Prometheus metrics collection")

    sys.exit(0 if success else 1)
