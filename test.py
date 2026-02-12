"""Test database connection for Acadia IQ"""
import psycopg2
from urllib.parse import urlparse, unquote
import os
from dotenv import load_dotenv
from urllib.parse import urlparse
import os



load_dotenv()

# Get DATABASE_URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
parsed = urlparse(DATABASE_URL)
safe = DATABASE_URL.replace(parsed.password, "****") if parsed.password else DATABASE_URL
print("DATABASE_URL (masked):", safe)
print("CWD:", os.getcwd())

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL not found in environment variables")
    print("Please create a .env file with your DATABASE_URL")
    exit(1)

# Check if it's still a placeholder
if "<Password>" in DATABASE_URL or "<password>" in DATABASE_URL.lower():
    print("❌ ERROR: DATABASE_URL contains placeholder '<Password>'")
    print("\n🔧 FIX: Replace <Password> with your actual password")
    print("\nYour current DATABASE_URL (from .env):")
    print(DATABASE_URL)
    print("\nShould look like:")
    print("postgresql+psycopg2://acadia_app:YourActualPassword@host:5432/acadiaiq?sslmode=require")
    print("\n💡 If password has special characters (@, :, /, etc.), use encode_password.py")
    exit(1)

print(f"Testing connection to database...")

# Parse the URL
parsed = urlparse(DATABASE_URL)

# Extract password and decode if URL-encoded
password = unquote(parsed.password) if parsed.password else None

print(f"\n📋 Connection details:")
print(f"  Protocol: {parsed.scheme}")
print(f"  Host: {parsed.hostname}")
print(f"  Port: {parsed.port or 5432}")
print(f"  User: {parsed.username}")
print(f"  Database: {parsed.path[1:] if parsed.path else 'default'}")
print(f"  Password: {'*' * len(parsed.password) if parsed.password else '❌ MISSING'}")

# Check for sslmode
if 'sslmode' in DATABASE_URL:
    print(f"  SSL Mode: ✅ Enabled (secure)")
else:
    print(f"  SSL Mode: ⚠️  Not specified (recommend adding ?sslmode=require)")

# Try to connect
print("\n🔌 Attempting connection...")
try:
    # SQLAlchemy format may have +psycopg2, so we need to handle that
    # Convert to pure psycopg2 format
    clean_url = DATABASE_URL.replace('postgresql+psycopg2://', 'postgresql://')
    
    conn = psycopg2.connect(clean_url)
    print("\n✅ SUCCESS: Connected to database!")
    
    # Test query
    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    version = cursor.fetchone()
    print(f"\n📊 PostgreSQL version:")
    print(f"   {version[0][:80]}...")
    
    # Check current database
    cursor.execute("SELECT current_database();")
    current_db = cursor.fetchone()[0]
    print(f"\n💾 Connected to database: {current_db}")
    
    if current_db != 'acadiaiq':
        print(f"   ⚠️  WARNING: Expected 'acadiaiq' but got '{current_db}'")
    
    # Check for pgvector extension
    cursor.execute("SELECT * FROM pg_extension WHERE extname = 'vector';")
    has_vector = cursor.fetchone()
    if has_vector:
        print("\n✅ pgvector extension is installed")
    else:
        print("\n⚠️  WARNING: pgvector extension not found")
        print("   You need to install it:")
        print("   CREATE EXTENSION IF NOT EXISTS vector;")
    
    # Check for uuid-ossp extension
    cursor.execute("SELECT * FROM pg_extension WHERE extname = 'uuid-ossp';")
    has_uuid = cursor.fetchone()
    if has_uuid:
        print("✅ uuid-ossp extension is installed")
    else:
        print("⚠️  WARNING: uuid-ossp extension not found")
        print("   You need to install it:")
        print("   CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
    
    # Check if tables exist
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('users', 'documents', 'document_chunks', 'chat_sessions', 'chat_messages')
        ORDER BY table_name;
    """)
    tables = cursor.fetchall()
    
    print(f"\n📊 Database tables:")
    if tables:
        for table in tables:
            print(f"   ✅ {table[0]}")
        
        # Check if we need to initialize
        if len(tables) < 5:
            print(f"\n⚠️  Only {len(tables)} tables found (expected 5+)")
            print("   Run: python -c \"from config.database import init_db; init_db()\"")
    else:
        print("   ⚠️  No application tables found")
        print("   Run: python -c \"from config.database import init_db; init_db()\"")
    
    cursor.close()
    conn.close()
    
    print("\n" + "="*60)
    print("✅ DATABASE CONNECTION TEST PASSED!")
    print("="*60)
    print("\n🚀 Next steps:")
    print("   1. If tables missing, run: python -c \"from config.database import init_db; init_db()\"")
    print("   2. Start your app: streamlit run app.py")
    print("="*60)
    
except psycopg2.OperationalError as e:
    error_msg = str(e)
    print(f"\n❌ CONNECTION FAILED:")
    print(f"   {error_msg}")
    print("\n🔧 Possible fixes:")
    
    if "password authentication failed" in error_msg:
        print("   1. ❌ Password is incorrect")
        print("      → Double-check your password in .env file")
        print("      → Make sure you replaced <Password> with actual password")
        print("      → If password has special chars, run: python encode_password.py")
    
    elif "timeout" in error_msg or "could not connect" in error_msg:
        print("   1. ❌ Cannot reach database server")
        print("      → Check RDS security group allows your IP")
        print("      → Verify RDS is running and publicly accessible")
        print("      → Check your internet connection")
    
    elif "database" in error_msg and "does not exist" in error_msg:
        print("   1. ❌ Database 'acadiaiq' doesn't exist")
        print("      → Connect with master user and create it:")
        print("         CREATE DATABASE acadiaiq;")
        print("      → Or change DATABASE_URL to use 'postgres' database")
    
    elif "role" in error_msg and "does not exist" in error_msg:
        print("   1. ❌ User 'acadia_app' doesn't exist")
        print("      → Connect with master user (postgres) and create it:")
        print("         CREATE USER acadia_app WITH PASSWORD 'your_password';")
        print("         GRANT ALL PRIVILEGES ON DATABASE acadiaiq TO acadia_app;")
        print("      → Or change DATABASE_URL to use 'postgres' user")
    
    else:
        print("   1. Check your .env file has correct DATABASE_URL")
        print("   2. Verify RDS endpoint is correct")
        print("   3. Check RDS security group")
        print("   4. Ensure database and user exist")
    
    exit(1)
    
except Exception as e:
    print(f"\n❌ UNEXPECTED ERROR: {str(e)}")
    import traceback
    traceback.print_exc()
    exit(1)
