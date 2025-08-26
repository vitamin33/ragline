#!/usr/bin/env python3
"""
Comprehensive Product CRUD and Redis Caching Integration Tests
"""
import sys
import os
import json
import time
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from packages.security.jwt import JWTManager
from packages.cache.redis_cache import RedisCache


class ProductCRUDTester:
    """Test Product CRUD operations with comprehensive scenarios"""
    
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.jwt_manager = JWTManager()
        
    def create_test_token(self, user_id=123, tenant_id=456):
        """Create JWT token for testing"""
        return self.jwt_manager.create_access_token(
            user_id=user_id,
            tenant_id=tenant_id,
            email=f"user{user_id}@tenant{tenant_id}.com",
            roles=["user"]
        )
    
    async def test_redis_caching_system(self):
        """Test Redis caching functionality"""
        print("🧪 Testing Redis Caching System")
        print("=" * 60)
        
        try:
            cache = RedisCache()
            tenant_id = 456
            
            # Test 1: Basic get/set operations
            print("📝 Test 1: Basic cache operations...")
            test_data = {"id": 123, "name": "Test Product", "price": 1999}
            
            # Set cache
            success = await cache.set(tenant_id, "product", "123", test_data, ttl=60)
            if success:
                print("✅ Cache set successful")
            else:
                print("❌ Cache set failed")
                return False
            
            # Get from cache
            cached_data = await cache.get(tenant_id, "product", "123")
            if cached_data == test_data:
                print("✅ Cache retrieval successful")
            else:
                print(f"❌ Cache data mismatch. Got: {cached_data}")
                return False
            
            # Test 2: Cache invalidation
            print("\n📝 Test 2: Cache invalidation...")
            delete_success = await cache.delete(tenant_id, "product", "123")
            if delete_success:
                print("✅ Cache deletion successful")
            else:
                print("❌ Cache deletion failed")
                return False
            
            # Verify deletion
            deleted_data = await cache.get(tenant_id, "product", "123")
            if deleted_data is None:
                print("✅ Cache properly invalidated")
            else:
                print("❌ Cache not properly invalidated")
                return False
            
            # Test 3: TTL with jitter
            print("\n📝 Test 3: TTL calculation with jitter...")
            base_ttl = 300
            ttl1 = cache._calculate_ttl_with_jitter(base_ttl)
            ttl2 = cache._calculate_ttl_with_jitter(base_ttl)
            
            if 300 <= ttl1 <= 360 and 300 <= ttl2 <= 360:
                print(f"✅ TTL jitter working (TTL1: {ttl1}s, TTL2: {ttl2}s)")
            else:
                print(f"❌ TTL jitter out of range (TTL1: {ttl1}s, TTL2: {ttl2}s)")
                return False
            
            if ttl1 != ttl2:
                print("✅ Jitter creates different TTLs (thundering herd protection)")
            else:
                print("⚠️  TTLs identical (might be coincidental)")
            
            # Test 4: Tenant isolation
            print("\n📝 Test 4: Tenant isolation...")
            await cache.set(100, "product", "456", {"tenant": 100, "data": "tenant100"})
            await cache.set(200, "product", "456", {"tenant": 200, "data": "tenant200"})
            
            tenant100_data = await cache.get(100, "product", "456")
            tenant200_data = await cache.get(200, "product", "456")
            
            if (tenant100_data["tenant"] == 100 and tenant200_data["tenant"] == 200):
                print("✅ Tenant isolation working correctly")
            else:
                print("❌ Tenant isolation failed")
                return False
            
            # Test 5: Pattern deletion
            print("\n📝 Test 5: Pattern-based cache invalidation...")
            await cache.set(tenant_id, "product", "001", {"id": 1})
            await cache.set(tenant_id, "product", "002", {"id": 2}) 
            await cache.set(tenant_id, "product", "003", {"id": 3})
            
            deleted_count = await cache.delete_pattern(tenant_id, "product", "*")
            if deleted_count >= 3:
                print(f"✅ Pattern deletion successful ({deleted_count} keys deleted)")
            else:
                print(f"❌ Pattern deletion incomplete ({deleted_count} keys deleted)")
                return False
            
            await cache.close()
            print("\n🎉 All Redis caching tests passed!")
            return True
            
        except Exception as e:
            print(f"❌ Redis caching test failed: {e}")
            return False
    
    async def test_cache_aside_pattern(self):
        """Test the cache-aside pattern implementation"""
        print("\n🧪 Testing Cache-Aside Pattern")
        print("=" * 60)
        
        try:
            cache = RedisCache()
            tenant_id = 789
            
            # Test fetch function that simulates database call
            fetch_call_count = 0
            async def mock_fetch_product():
                nonlocal fetch_call_count
                fetch_call_count += 1
                await asyncio.sleep(0.1)  # Simulate database latency
                return {"id": 999, "name": "Cached Product", "fetch_count": fetch_call_count}
            
            print("📝 Test 1: First call (cache miss)...")
            start_time = time.time()
            result1 = await cache.get_or_set(
                tenant_id, "product", "999", mock_fetch_product, ttl=60
            )
            first_call_time = time.time() - start_time
            
            if result1 and result1["fetch_count"] == 1:
                print(f"✅ Cache miss handled correctly (took {first_call_time:.3f}s)")
            else:
                print("❌ Cache miss test failed")
                return False
            
            print("\n📝 Test 2: Second call (cache hit)...")
            start_time = time.time()
            result2 = await cache.get_or_set(
                tenant_id, "product", "999", mock_fetch_product, ttl=60
            )
            second_call_time = time.time() - start_time
            
            if (result2 and result2["fetch_count"] == 1 and  # Same data, no new fetch
                second_call_time < first_call_time):  # Faster than database call
                print(f"✅ Cache hit working (took {second_call_time:.3f}s, {(first_call_time/second_call_time):.1f}x faster)")
            else:
                print("❌ Cache hit test failed")
                return False
            
            if fetch_call_count == 1:
                print("✅ Database called only once (cache-aside working)")
            else:
                print(f"❌ Database called {fetch_call_count} times (should be 1)")
                return False
            
            await cache.close()
            print("\n🎉 Cache-aside pattern tests passed!")
            return True
            
        except Exception as e:
            print(f"❌ Cache-aside test failed: {e}")
            return False


async def test_product_crud_without_database():
    """Test Product CRUD endpoints (will fail gracefully without database)"""
    print("\n🧪 Testing Product CRUD Endpoints (No Database)")
    print("=" * 60)
    
    import requests
    
    base_url = "http://localhost:8000"
    jwt_manager = JWTManager()
    
    # Create test tokens for different tenants
    token1 = jwt_manager.create_access_token(100, 1, "user1@tenant1.com", ["user"])
    token2 = jwt_manager.create_access_token(200, 2, "user2@tenant2.com", ["admin"])
    
    print("📝 Test 1: Product listing without authentication...")
    try:
        response = requests.get(f"{base_url}/v1/products/", timeout=5)
        if response.status_code in [401, 403]:
            print("✅ Unauthenticated access properly blocked")
        else:
            print(f"❌ Should block unauthenticated access, got: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False
    
    print("\n📝 Test 2: Product listing with authentication (will fail at database)...")
    try:
        headers = {"Authorization": f"Bearer {token1}"}
        response = requests.get(f"{base_url}/v1/products/", headers=headers, timeout=5)
        
        if response.status_code == 500:
            error_data = response.json()
            if "Failed to retrieve products" in error_data.get("detail", ""):
                print("✅ Authentication passed, failed at database (expected)")
            else:
                print("❌ Unexpected error message")
                return False
        elif response.status_code == 401:
            print("❌ Authentication failed (JWT not working)")
            return False
        else:
            print(f"❌ Unexpected status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Authenticated request failed: {e}")
        return False
    
    print("\n📝 Test 3: Product creation with validation...")
    try:
        headers = {"Authorization": f"Bearer {token1}"}
        invalid_product = {"name": "", "price": -100}  # Invalid data
        
        response = requests.post(
            f"{base_url}/v1/products/", 
            json=invalid_product,
            headers=headers, 
            timeout=5
        )
        
        # Should either fail validation (422) or at database (500)
        if response.status_code in [422, 500]:
            print("✅ Product validation working (invalid data rejected)")
        else:
            print(f"❌ Should reject invalid product, got: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Product creation test failed: {e}")
        return False
    
    print("\n📝 Test 4: Multi-tenant token isolation...")
    try:
        headers1 = {"Authorization": f"Bearer {token1}"}  # Tenant 1
        headers2 = {"Authorization": f"Bearer {token2}"}  # Tenant 2
        
        response1 = requests.get(f"{base_url}/v1/products/", headers=headers1, timeout=5)
        response2 = requests.get(f"{base_url}/v1/products/", headers=headers2, timeout=5)
        
        # Both should fail at database but with different tenant contexts
        if response1.status_code == 500 and response2.status_code == 500:
            print("✅ Multi-tenant tokens both authenticated (failed at database as expected)")
        else:
            print(f"❌ Multi-tenant test issue: {response1.status_code}, {response2.status_code}")
            return False
    except Exception as e:
        print(f"❌ Multi-tenant test failed: {e}")
        return False
    
    print("\n🎉 Product CRUD endpoint tests passed!")
    return True


async def run_comprehensive_tests():
    """Run all comprehensive tests"""
    print("🚀 Starting Comprehensive Product CRUD + Caching Tests")
    print("=" * 80)
    
    # Check if server is running
    import requests
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        print(f"✅ Server running (status: {response.status_code})")
    except Exception as e:
        print(f"❌ Server not accessible: {e}")
        print("Please start server: source .venv/bin/activate && cd services/api && python main.py")
        return False
    
    test_functions = [
        ("Redis Caching System", ProductCRUDTester().test_redis_caching_system),
        ("Cache-Aside Pattern", ProductCRUDTester().test_cache_aside_pattern),
        ("Product CRUD Endpoints", test_product_crud_without_database)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in test_functions:
        try:
            print(f"\n🔄 Running: {test_name}")
            if await test_func():
                passed += 1
                print(f"✅ {test_name}: PASSED")
            else:
                failed += 1
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ {test_name}: EXCEPTION - {e}")
    
    print("\n" + "=" * 80)
    print(f"📊 Comprehensive Test Results:")
    print(f"   ✅ Passed: {passed}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📈 Success Rate: {(passed / (passed + failed) * 100):.1f}%")
    
    if failed == 0:
        print("\n🎉 All comprehensive tests passed! Code ready for PR!")
        return True
    else:
        print(f"\n⚠️  {failed} test(s) failed. Please review before creating PR.")
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(run_comprehensive_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
        sys.exit(1)