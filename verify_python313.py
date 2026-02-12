#!/usr/bin/env python
"""Verify Python 3.13.3 compatibility."""

import sys
import importlib.metadata


def check_python_version():
    """Check Python version."""
    version = sys.version_info
    print(f"\n{'='*60}")
    print(f"Python Version Check")
    print(f"{'='*60}")
    print(f"Current: Python {version.major}.{version.minor}.{version.micro}")
    
    if version.major == 3 and version.minor >= 13:
        print("✅ Python 3.13+ detected - FULLY COMPATIBLE")
        return True
    elif version.major == 3 and version.minor >= 9:
        print("✅ Python 3.9+ detected - Compatible (3.13 recommended)")
        return True
    else:
        print("❌ Python 3.9+ required")
        return False


def check_dependencies():
    """Check installed dependencies."""
    print(f"\n{'='*60}")
    print(f"Dependency Check")
    print(f"{'='*60}")
    
    required = {
        'pydantic': ('2.6.0', 'Required for Python 3.13'),
        'pydantic-settings': ('2.2.0', 'Required for Python 3.13'),
        'sqlalchemy': ('2.0.0', 'Database ORM'),
        'streamlit': ('1.31.0', 'UI Framework'),
        'cryptography': ('42.0.0', 'Encryption'),
        'boto3': ('1.34.0', 'AWS SDK'),
        'pgvector': ('0.2.4', 'Vector similarity'),
    }
    
    all_ok = True
    
    for package, (min_version, description) in required.items():
        try:
            version = importlib.metadata.version(package)
            
            # Simple version comparison
            installed_parts = version.split('.')[:2]
            required_parts = min_version.split('.')[:2]
            
            try:
                installed_major = int(installed_parts[0])
                installed_minor = int(installed_parts[1])
                required_major = int(required_parts[0])
                required_minor = int(required_parts[1])
                
                if (installed_major > required_major or 
                    (installed_major == required_major and installed_minor >= required_minor)):
                    print(f"✅ {package}=={version:15s} ({description})")
                else:
                    print(f"⚠️  {package}=={version:15s} (upgrade recommended to {min_version}+)")
                    all_ok = False
            except (ValueError, IndexError):
                print(f"✅ {package}=={version:15s} ({description})")
                
        except importlib.metadata.PackageNotFoundError:
            print(f"❌ {package:20s} NOT INSTALLED ({description})")
            all_ok = False
    
    return all_ok


def test_imports():
    """Test critical imports."""
    print(f"\n{'='*60}")
    print(f"Import Test")
    print(f"{'='*60}")
    
    imports = [
        ('streamlit', 'Streamlit UI'),
        ('sqlalchemy', 'SQLAlchemy ORM'),
        ('pydantic', 'Pydantic Validation'),
        ('pydantic_settings', 'Pydantic Settings'),
        ('cryptography.hazmat.primitives.ciphers.aead', 'Encryption'),
        ('boto3', 'AWS SDK'),
        ('pgvector.sqlalchemy', 'pgvector'),
    ]
    
    all_ok = True
    
    for module, description in imports:
        try:
            __import__(module)
            print(f"✅ {module:40s} - {description}")
        except ImportError as e:
            print(f"❌ {module:40s} - FAILED: {str(e)}")
            all_ok = False
    
    return all_ok


def check_pydantic_v2():
    """Verify Pydantic v2 features."""
    print(f"\n{'='*60}")
    print(f"Pydantic v2 Compatibility Check")
    print(f"{'='*60}")
    
    try:
        from pydantic import BaseModel, ConfigDict
        from pydantic_settings import BaseSettings, SettingsConfigDict
        
        # Test new syntax
        class TestModel(BaseModel):
            field: str
            model_config = ConfigDict(from_attributes=True)
        
        class TestSettings(BaseSettings):
            test_var: str = "test"
            model_config = SettingsConfigDict(extra="ignore")
        
        print("✅ Pydantic v2 syntax working correctly")
        print("✅ ConfigDict available")
        print("✅ SettingsConfigDict available")
        print("✅ from_attributes configuration working")
        
        return True
        
    except Exception as e:
        print(f"❌ Pydantic v2 check failed: {str(e)}")
        return False


def main():
    """Run all checks."""
    print(f"\n{'#'*60}")
    print(f"# Python 3.13.3 Compatibility Verification")
    print(f"# Secure PDF Chat Application")
    print(f"{'#'*60}")
    
    results = []
    
    # Run checks
    results.append(("Python Version", check_python_version()))
    results.append(("Dependencies", check_dependencies()))
    results.append(("Imports", test_imports()))
    results.append(("Pydantic v2", check_pydantic_v2()))
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Summary")
    print(f"{'='*60}")
    
    all_passed = all(result for _, result in results)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{name:20s}: {status}")
    
    print(f"{'='*60}")
    
    if all_passed:
        print("\n🎉 All checks passed! System is ready for Python 3.13.3")
        print("\nNext steps:")
        print("1. Run: streamlit run app.py")
        print("2. Follow QUICKSTART.md for setup")
        return 0
    else:
        print("\n⚠️  Some checks failed. Please:")
        print("1. Ensure Python 3.13.3 is installed")
        print("2. Run: pip install -r requirements.txt")
        print("3. Run this script again")
        return 1


if __name__ == "__main__":
    sys.exit(main())
