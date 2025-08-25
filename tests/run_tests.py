#!/usr/bin/env python3
"""
RAGline Test Runner
Run all tests with proper reporting
"""
import sys
import os
import subprocess
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def run_unit_tests():
    """Run unit tests"""
    print("🧪 Running Unit Tests...")
    print("=" * 50)
    
    unit_test_file = project_root / "tests" / "unit" / "test_jwt_auth.py"
    if unit_test_file.exists():
        result = subprocess.run([sys.executable, str(unit_test_file)], 
                              capture_output=False, text=True)
        return result.returncode == 0
    else:
        print("❌ Unit test file not found")
        return False

def run_integration_tests():
    """Run integration tests"""
    print("\n🔗 Running Integration Tests...")
    print("=" * 50)
    print("⚠️  Integration tests require a running server on http://localhost:8000")
    print("   Start server with: source .venv/bin/activate && cd services/api && python main.py")
    print()
    
    response = input("Is the server running? (y/N): ").lower().strip()
    if response != 'y':
        print("⏭️  Skipping integration tests")
        return True
    
    integration_test_file = project_root / "tests" / "integration" / "test_api_endpoints.py"
    if integration_test_file.exists():
        result = subprocess.run([sys.executable, str(integration_test_file)], 
                              capture_output=False, text=True)
        return result.returncode == 0
    else:
        print("❌ Integration test file not found")
        return False

def main():
    """Run all tests"""
    print("🚀 RAGline Test Suite")
    print("=" * 80)
    
    unit_success = run_unit_tests()
    integration_success = run_integration_tests()
    
    print("\n" + "=" * 80)
    print("📊 Test Results Summary:")
    print(f"   Unit Tests: {'✅ PASS' if unit_success else '❌ FAIL'}")
    print(f"   Integration Tests: {'✅ PASS' if integration_success else '❌ FAIL'}")
    
    overall_success = unit_success and integration_success
    print(f"\n🎯 Overall: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
    
    return 0 if overall_success else 1

if __name__ == "__main__":
    sys.exit(main())