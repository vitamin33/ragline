#!/usr/bin/env python3
"""
Simple test script for RAGline Celery worker service
"""

import os
import sys
import time

# Add current directory to path so imports work
sys.path.insert(0, os.path.dirname(__file__))

def test_celery_import():
    """Test if we can import the Celery app"""
    try:
        from services.worker.celery_app import app
        print("✅ Successfully imported Celery app")
        print(f"   - App name: {app.main}")
        print(f"   - Broker: {app.conf.broker_url}")
        return True
    except Exception as e:
        print(f"❌ Failed to import Celery app: {e}")
        return False

def test_config():
    """Test worker configuration"""
    try:
        from services.worker.config import WorkerConfig, get_environment_config
        
        config = WorkerConfig()
        print("✅ Successfully loaded worker configuration")
        print(f"   - Worker pool: {config.worker_pool}")
        print(f"   - Concurrency: {config.worker_concurrency}")
        print(f"   - Redis URL: {config.redis_url}")
        
        # Test environment config
        env_config = get_environment_config()
        print(f"   - Environment config pool: {env_config.worker_pool}")
        return True
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return False

def test_redis_connection():
    """Test Redis connectivity"""
    try:
        import redis
        from services.worker.config import WorkerConfig
        
        config = WorkerConfig()
        redis_client = redis.from_url(config.redis_url)
        
        # Test basic operations
        test_key = "ragline:test:connection"
        test_value = f"test_{int(time.time())}"
        
        redis_client.set(test_key, test_value, ex=10)  # Expire in 10 seconds
        retrieved = redis_client.get(test_key)
        redis_client.delete(test_key)
        
        if retrieved and retrieved.decode() == test_value:
            print("✅ Redis connection successful")
            print(f"   - Redis version: {redis_client.info().get('redis_version')}")
            return True
        else:
            print("❌ Redis set/get test failed")
            return False
            
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False

def test_health_task_import():
    """Test if we can import health check tasks"""
    try:
        from services.worker.tasks.health import health_check, ping
        print("✅ Successfully imported health check tasks")
        print(f"   - Health check task: {health_check.name}")
        print(f"   - Ping task: {ping.name}")
        return True
    except Exception as e:
        print(f"❌ Failed to import health tasks: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 RAGline Celery Worker Test Suite")
    print("=" * 40)
    
    tests = [
        ("Celery App Import", test_celery_import),
        ("Worker Configuration", test_config),
        ("Redis Connection", test_redis_connection),
        ("Health Tasks Import", test_health_task_import),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📋 Testing: {test_name}")
        print("-" * 30)
        if test_func():
            passed += 1
        
    print("\n" + "=" * 40)
    print(f"📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Celery service is ready.")
        return 0
    else:
        print("❌ Some tests failed. Check the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())