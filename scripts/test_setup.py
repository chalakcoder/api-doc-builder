#!/usr/bin/env python3
"""
Test script to verify the development setup.
"""
import sys
import traceback
from pathlib import Path

def test_imports():
    """Test that all required modules can be imported."""
    print("🧪 Testing imports...")
    
    try:
        from app.main import create_app
        print("✅ Main application imports successful")
    except Exception as e:
        print(f"❌ Main application import failed: {e}")
        return False
    
    try:
        from app.core.exceptions import SpecDocumentationAPIError
        print("✅ Exception handling imports successful")
    except Exception as e:
        print(f"❌ Exception handling import failed: {e}")
        return False
    
    try:
        from app.db.database import engine
        print("✅ Database imports successful")
    except Exception as e:
        print(f"❌ Database import failed: {e}")
        return False
    
    return True

def test_database():
    """Test database connection."""
    print("\n🗄️  Testing database connection...")
    
    try:
        from app.db.database import check_database_connection
        if check_database_connection():
            print("✅ Database connection successful")
            return True
        else:
            print("❌ Database connection failed")
            return False
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

def test_redis():
    """Test Redis connection (with fallback)."""
    print("\n🔴 Testing Redis connection...")
    
    try:
        from app.jobs.job_manager import JobManager
        manager = JobManager()
        manager.redis_client.ping()
        print("✅ Redis connection successful")
        return True
    except Exception as e:
        print(f"⚠️  Redis test: {e} (using fallback)")
        return True  # Fallback is acceptable

def test_app_creation():
    """Test FastAPI app creation."""
    print("\n🚀 Testing app creation...")
    
    try:
        from app.main import create_app
        app = create_app()
        print("✅ FastAPI app created successfully")
        return True
    except Exception as e:
        print(f"❌ App creation failed: {e}")
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("🔍 Running setup verification tests...\n")
    
    tests = [
        ("Import Tests", test_imports),
        ("Database Test", test_database),
        ("Redis Test", test_redis),
        ("App Creation Test", test_app_creation),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} crashed: {e}")
            results.append((test_name, False))
    
    print("\n📊 Test Results:")
    print("=" * 50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name:<20} {status}")
        if result:
            passed += 1
    
    print("=" * 50)
    print(f"Tests passed: {passed}/{len(results)}")
    
    if passed == len(results):
        print("\n🎉 All tests passed! Your setup is ready.")
        print("\n📋 Next steps:")
        print("   1. Start the server: uvicorn app.main:app --reload")
        print("   2. Visit: http://localhost:8000/docs")
        return 0
    else:
        print(f"\n⚠️  {len(results) - passed} test(s) failed. Check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())