#!/usr/bin/env python3
"""
Comprehensive test script for JWT authentication system
"""
import sys
import os
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from packages.security.jwt import JWTManager, TokenData
from packages.security.auth import AuthService


def test_jwt_token_generation():
    """Test JWT token generation and verification"""
    print("🧪 Testing JWT Token Generation and Verification")
    print("=" * 60)
    
    # Create JWT manager
    jwt_manager = JWTManager(
        secret_key="test-secret-key-for-testing-only",
        access_token_expire_minutes=30,
        refresh_token_expire_days=7
    )
    
    # Test data
    user_id = 123
    tenant_id = 456
    email = "test@example.com"
    roles = ["user", "admin"]
    
    # Test 1: Create access token
    print("📝 Test 1: Creating access token...")
    access_token = jwt_manager.create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
        roles=roles
    )
    print(f"✅ Access token created: {access_token[:50]}...")
    
    # Test 2: Verify access token
    print("\n📝 Test 2: Verifying access token...")
    token_data = jwt_manager.verify_token(access_token)
    
    if token_data:
        print(f"✅ Token verified successfully!")
        print(f"   User ID: {token_data.user_id}")
        print(f"   Tenant ID: {token_data.tenant_id}")
        print(f"   Email: {token_data.email}")
        print(f"   Roles: {token_data.roles}")
        print(f"   Expires: {token_data.exp}")
        
        # Validate data
        assert token_data.user_id == user_id
        assert token_data.tenant_id == tenant_id
        assert token_data.email == email
        assert token_data.roles == roles
        print("✅ All token data matches expected values")
    else:
        print("❌ Token verification failed")
        return False
    
    # Test 3: Create refresh token
    print("\n📝 Test 3: Creating refresh token...")
    refresh_token = jwt_manager.create_refresh_token(
        user_id=user_id,
        tenant_id=tenant_id
    )
    print(f"✅ Refresh token created: {refresh_token[:50]}...")
    
    # Test 4: Verify refresh token
    print("\n📝 Test 4: Verifying refresh token...")
    refresh_data = jwt_manager.verify_refresh_token(refresh_token)
    
    if refresh_data:
        print(f"✅ Refresh token verified successfully!")
        print(f"   User ID: {refresh_data['user_id']}")
        print(f"   Tenant ID: {refresh_data['tenant_id']}")
        
        assert refresh_data["user_id"] == user_id
        assert refresh_data["tenant_id"] == tenant_id
        print("✅ Refresh token data matches expected values")
    else:
        print("❌ Refresh token verification failed")
        return False
    
    # Test 5: Test expired token (using past date)
    print("\n📝 Test 5: Testing expired token...")
    expired_token = jwt_manager.create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
        roles=roles,
        expires_delta=timedelta(seconds=-1)  # Already expired
    )
    
    expired_data = jwt_manager.verify_token(expired_token)
    if expired_data is None:
        print("✅ Expired token correctly rejected")
    else:
        print("❌ Expired token was accepted (should have been rejected)")
        return False
    
    # Test 6: Test invalid token
    print("\n📝 Test 6: Testing invalid token...")
    invalid_token = "invalid.jwt.token"
    invalid_data = jwt_manager.verify_token(invalid_token)
    
    if invalid_data is None:
        print("✅ Invalid token correctly rejected")
    else:
        print("❌ Invalid token was accepted (should have been rejected)")
        return False
    
    # Test 7: Test wrong token type (using refresh token as access token)
    print("\n📝 Test 7: Testing wrong token type...")
    refresh_as_access = jwt_manager.verify_token(refresh_token)
    
    if refresh_as_access is None:
        print("✅ Refresh token correctly rejected when used as access token")
    else:
        print("❌ Refresh token was accepted as access token (should have been rejected)")
        return False
    
    print("\n🎉 All JWT token tests passed!")
    return True


def test_password_hashing():
    """Test password hashing functionality"""
    print("\n🧪 Testing Password Hashing")
    print("=" * 60)
    
    # Test password
    plain_password = "test_password_123"
    
    # Test 1: Hash password
    print("📝 Test 1: Hashing password...")
    hashed = AuthService.get_password_hash(plain_password)
    print(f"✅ Password hashed: {hashed[:50]}...")
    
    # Test 2: Verify correct password
    print("\n📝 Test 2: Verifying correct password...")
    is_valid = AuthService.verify_password(plain_password, hashed)
    
    if is_valid:
        print("✅ Correct password verified successfully")
    else:
        print("❌ Correct password verification failed")
        return False
    
    # Test 3: Verify incorrect password
    print("\n📝 Test 3: Testing incorrect password...")
    wrong_password = "wrong_password"
    is_invalid = AuthService.verify_password(wrong_password, hashed)
    
    if not is_invalid:
        print("✅ Incorrect password correctly rejected")
    else:
        print("❌ Incorrect password was accepted")
        return False
    
    # Test 4: Different hashes for same password
    print("\n📝 Test 4: Testing hash uniqueness...")
    hash1 = AuthService.get_password_hash(plain_password)
    hash2 = AuthService.get_password_hash(plain_password)
    
    if hash1 != hash2:
        print("✅ Different hashes generated for same password (salt working)")
    else:
        print("❌ Same hash generated for same password (salt not working)")
        return False
    
    # Both should verify the original password
    if (AuthService.verify_password(plain_password, hash1) and 
        AuthService.verify_password(plain_password, hash2)):
        print("✅ Both hashes verify the original password")
    else:
        print("❌ Hash verification inconsistent")
        return False
    
    print("\n🎉 All password hashing tests passed!")
    return True


def test_token_expiry():
    """Test token expiry functionality"""
    print("\n🧪 Testing Token Expiry")
    print("=" * 60)
    
    jwt_manager = JWTManager(
        secret_key="test-secret-key-for-testing-only",
        access_token_expire_minutes=1  # 1 minute for quick testing
    )
    
    # Test 1: Create token with custom expiry
    print("📝 Test 1: Creating token with 1 second expiry...")
    short_token = jwt_manager.create_access_token(
        user_id=123,
        tenant_id=456,
        email="test@example.com",
        roles=["user"],
        expires_delta=timedelta(seconds=1)
    )
    
    # Test 2: Get token expiry
    print("\n📝 Test 2: Getting token expiry...")
    expiry = jwt_manager.get_token_expiry(short_token)
    
    if expiry:
        print(f"✅ Token expiry retrieved: {expiry}")
        
        # Check if expiry is approximately 1 second from now
        expected_expiry = datetime.now(timezone.utc) + timedelta(seconds=1)
        time_diff = abs((expiry - expected_expiry).total_seconds())
        
        if time_diff < 2:  # Allow 2 seconds tolerance
            print("✅ Token expiry time is correct")
        else:
            print(f"❌ Token expiry time incorrect. Diff: {time_diff} seconds")
            return False
    else:
        print("❌ Could not retrieve token expiry")
        return False
    
    # Test 3: Check if token is not yet expired
    print("\n📝 Test 3: Checking if token is not yet expired...")
    is_expired = jwt_manager.is_token_expired(short_token)
    
    if not is_expired:
        print("✅ Token is not yet expired (as expected)")
    else:
        print("❌ Token shows as expired when it shouldn't be")
        return False
    
    # Test 4: Wait for token to expire and test again
    print("\n📝 Test 4: Waiting for token to expire...")
    import time
    time.sleep(2)  # Wait 2 seconds for 1-second token to expire
    
    is_expired_now = jwt_manager.is_token_expired(short_token)
    
    if is_expired_now:
        print("✅ Token is now expired (as expected)")
    else:
        print("❌ Token should be expired but shows as valid")
        return False
    
    # Test 5: Try to verify expired token
    print("\n📝 Test 5: Trying to verify expired token...")
    expired_data = jwt_manager.verify_token(short_token)
    
    if expired_data is None:
        print("✅ Expired token correctly rejected by verification")
    else:
        print("❌ Expired token was accepted by verification")
        return False
    
    print("\n🎉 All token expiry tests passed!")
    return True


def test_role_based_claims():
    """Test role-based JWT claims"""
    print("\n🧪 Testing Role-Based JWT Claims")
    print("=" * 60)
    
    jwt_manager = JWTManager(secret_key="test-secret-key-for-testing-only")
    
    # Test 1: Token with multiple roles
    print("📝 Test 1: Creating token with multiple roles...")
    roles = ["user", "admin", "moderator"]
    token = jwt_manager.create_access_token(
        user_id=123,
        tenant_id=456,
        email="admin@example.com",
        roles=roles
    )
    
    token_data = jwt_manager.verify_token(token)
    
    if token_data and token_data.roles == roles:
        print(f"✅ Multiple roles preserved: {token_data.roles}")
    else:
        print(f"❌ Roles not preserved correctly. Got: {token_data.roles if token_data else 'None'}")
        return False
    
    # Test 2: Token with no roles (empty list)
    print("\n📝 Test 2: Creating token with no roles...")
    no_roles_token = jwt_manager.create_access_token(
        user_id=123,
        tenant_id=456,
        email="user@example.com",
        roles=[]
    )
    
    no_roles_data = jwt_manager.verify_token(no_roles_token)
    
    if no_roles_data and no_roles_data.roles == []:
        print("✅ Empty roles list preserved")
    else:
        print(f"❌ Empty roles not preserved. Got: {no_roles_data.roles if no_roles_data else 'None'}")
        return False
    
    # Test 3: Token with default roles (None passed)
    print("\n📝 Test 3: Creating token with default roles...")
    default_token = jwt_manager.create_access_token(
        user_id=123,
        tenant_id=456,
        email="default@example.com"
        # roles parameter omitted - should default to empty list
    )
    
    default_data = jwt_manager.verify_token(default_token)
    
    if default_data and default_data.roles == []:
        print("✅ Default roles (empty list) applied correctly")
    else:
        print(f"❌ Default roles not applied. Got: {default_data.roles if default_data else 'None'}")
        return False
    
    print("\n🎉 All role-based claims tests passed!")
    return True


def test_multi_tenant_isolation():
    """Test multi-tenant isolation in JWT claims"""
    print("\n🧪 Testing Multi-Tenant Isolation")
    print("=" * 60)
    
    jwt_manager = JWTManager(secret_key="test-secret-key-for-testing-only")
    
    # Test 1: Different tenants
    print("📝 Test 1: Creating tokens for different tenants...")
    
    # Tenant 1
    token1 = jwt_manager.create_access_token(
        user_id=100,
        tenant_id=1,
        email="user1@tenant1.com",
        roles=["user"]
    )
    
    # Tenant 2
    token2 = jwt_manager.create_access_token(
        user_id=200,
        tenant_id=2,
        email="user2@tenant2.com",
        roles=["admin"]
    )
    
    # Verify both tokens
    data1 = jwt_manager.verify_token(token1)
    data2 = jwt_manager.verify_token(token2)
    
    if (data1 and data2 and 
        data1.tenant_id == 1 and data2.tenant_id == 2 and
        data1.user_id == 100 and data2.user_id == 200):
        print("✅ Multi-tenant tokens created and verified successfully")
        print(f"   Token 1 - Tenant: {data1.tenant_id}, User: {data1.user_id}")
        print(f"   Token 2 - Tenant: {data2.tenant_id}, User: {data2.user_id}")
    else:
        print("❌ Multi-tenant token verification failed")
        return False
    
    # Test 2: Same user ID in different tenants
    print("\n📝 Test 2: Testing same user ID in different tenants...")
    
    same_user_token1 = jwt_manager.create_access_token(
        user_id=999,
        tenant_id=10,
        email="user@tenant10.com",
        roles=["user"]
    )
    
    same_user_token2 = jwt_manager.create_access_token(
        user_id=999,  # Same user ID
        tenant_id=20,  # Different tenant
        email="user@tenant20.com",
        roles=["admin"]
    )
    
    same_data1 = jwt_manager.verify_token(same_user_token1)
    same_data2 = jwt_manager.verify_token(same_user_token2)
    
    if (same_data1 and same_data2 and
        same_data1.user_id == same_data2.user_id == 999 and
        same_data1.tenant_id != same_data2.tenant_id):
        print("✅ Same user ID in different tenants handled correctly")
        print(f"   User 999 in tenant {same_data1.tenant_id}: roles={same_data1.roles}")
        print(f"   User 999 in tenant {same_data2.tenant_id}: roles={same_data2.roles}")
    else:
        print("❌ Same user ID in different tenants test failed")
        return False
    
    print("\n🎉 All multi-tenant isolation tests passed!")
    return True


def run_all_tests():
    """Run all JWT authentication tests"""
    print("🚀 Starting Comprehensive JWT Authentication Tests")
    print("=" * 80)
    
    test_functions = [
        test_jwt_token_generation,
        test_password_hashing,
        test_token_expiry,
        test_role_based_claims,
        test_multi_tenant_isolation
    ]
    
    passed_tests = 0
    failed_tests = 0
    
    for test_func in test_functions:
        try:
            if test_func():
                passed_tests += 1
            else:
                failed_tests += 1
        except Exception as e:
            print(f"❌ Test {test_func.__name__} failed with exception: {e}")
            failed_tests += 1
    
    print("\n" + "=" * 80)
    print(f"📊 Test Summary:")
    print(f"   ✅ Passed: {passed_tests}")
    print(f"   ❌ Failed: {failed_tests}")
    print(f"   📈 Success Rate: {(passed_tests / (passed_tests + failed_tests) * 100):.1f}%")
    
    if failed_tests == 0:
        print("\n🎉 All tests passed! JWT authentication system is working correctly.")
        return True
    else:
        print(f"\n⚠️  {failed_tests} test(s) failed. Please review the output above.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)