#!/usr/bin/env python3
"""
RAGline Agent B - Integration Test Runner

Runs all integration tests for the reliability and events layer.
"""

import os
import sys
import subprocess
import time

def run_test_suite():
    """Run all integration tests"""
    print("🧪 RAGline Agent B - Integration Test Suite")
    print("=" * 60)
    
    # Ensure we're in virtual environment
    if not os.environ.get('VIRTUAL_ENV'):
        print("⚠️  Virtual environment not detected")
        print("   Run: source .venv/bin/activate")
        return 1
    
    test_files = [
        ("Health Tasks", "tests/integration/test_health_tasks.py"),
        ("Redis Streams", "tests/integration/test_comprehensive_streams.py"),
        ("Event Schemas", "tests/integration/test_event_schemas.py"),
    ]
    
    passed = 0
    total = len(test_files)
    start_time = time.time()
    
    for test_name, test_file in test_files:
        print(f"\n📋 Running: {test_name}")
        print("-" * 50)
        
        try:
            result = subprocess.run([sys.executable, test_file], 
                                  capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                passed += 1
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
                if result.stderr:
                    print(f"   Error: {result.stderr[:200]}...")
                    
        except subprocess.TimeoutExpired:
            print(f"⏰ {test_name}: TIMEOUT")
        except Exception as e:
            print(f"💥 {test_name}: ERROR - {e}")
    
    duration = time.time() - start_time
    
    print(f"\n" + "=" * 60)
    print("📊 INTEGRATION TEST SUMMARY")
    print("=" * 60)
    print(f"🎯 Tests: {passed}/{total} passed")
    print(f"📈 Success Rate: {(passed/total)*100:.1f}%")
    print(f"⏱️  Duration: {duration:.2f}s")
    
    if passed == total:
        print("\n🎉 All integration tests passed!")
        print("🚀 Agent B implementation ready for production!")
        return 0
    else:
        print(f"\n❌ {total-passed} test(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(run_test_suite())