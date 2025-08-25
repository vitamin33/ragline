#!/usr/bin/env python3
"""
Test health check tasks directly without running worker
"""

import os
import sys

# Add current directory to path so imports work
sys.path.insert(0, os.path.dirname(__file__))

def test_ping_task():
    """Test ping task directly"""
    try:
        from services.worker.tasks.health import ping
        from services.worker.celery_app import app
        
        # Configure app to run tasks eagerly (synchronously) for testing
        app.conf.task_always_eager = True
        
        print("🏓 Testing ping task...")
        result = ping.delay()
        response = result.get()
        
        print(f"✅ Ping task executed successfully!")
        print(f"   Status: {response.get('status')}")
        print(f"   Timestamp: {response.get('timestamp')}")
        return True
        
    except Exception as e:
        print(f"❌ Ping task failed: {e}")
        return False

def test_health_check_task():
    """Test health check task directly"""
    try:
        from services.worker.tasks.health import health_check
        from services.worker.celery_app import app
        
        # Configure app to run tasks eagerly (synchronously) for testing
        app.conf.task_always_eager = True
        
        print("🏥 Testing health check task...")
        result = health_check.delay()
        response = result.get()
        
        print(f"✅ Health check task executed successfully!")
        print(f"   Overall Status: {response.get('status')}")
        print(f"   Timestamp: {response.get('timestamp')}")
        
        # Show detailed check results
        checks = response.get('checks', {})
        for check_name, check_result in checks.items():
            status = check_result.get('status', 'unknown')
            print(f"   - {check_name}: {status}")
        
        # Show metrics
        metrics = response.get('metrics', {})
        duration = metrics.get('check_duration_ms', 0)
        print(f"   - Duration: {duration}ms")
        
        return True
        
    except Exception as e:
        print(f"❌ Health check task failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_stress_test_task():
    """Test stress test task"""
    try:
        from services.worker.tasks.health import stress_test
        from services.worker.celery_app import app
        
        # Configure app to run tasks eagerly (synchronously) for testing
        app.conf.task_always_eager = True
        
        print("💪 Testing stress test task (CPU - 3 seconds)...")
        result = stress_test.delay(duration=3, task_type="cpu")
        response = result.get()
        
        print(f"✅ Stress test task executed successfully!")
        print(f"   Task type: {response.get('task_type')}")
        print(f"   Duration: {response.get('duration')}s")
        print(f"   Iterations: {response.get('iterations')}")
        print(f"   Rate: {response.get('iterations_per_second')} iter/sec")
        
        return True
        
    except Exception as e:
        print(f"❌ Stress test task failed: {e}")
        return False

def main():
    """Run health task tests"""
    print("🧪 RAGline Health Tasks Test Suite")
    print("=" * 40)
    
    tests = [
        ("Ping Task", test_ping_task),
        ("Health Check Task", test_health_check_task),
        ("Stress Test Task", test_stress_test_task),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📋 Testing: {test_name}")
        print("-" * 30)
        if test_func():
            passed += 1
        print()  # Add spacing between tests
        
    print("=" * 40)
    print(f"📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All health tasks working correctly!")
        return 0
    else:
        print("❌ Some health tasks failed. Check the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())