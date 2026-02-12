#!/usr/bin/env python
"""
AWS RDS PostgreSQL Setup Helper Script
Helps set up pgvector extension and test database connection
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def setup_pgvector():
    """Create pgvector extension in RDS PostgreSQL"""
    try:
        import psycopg2
        from psycopg2 import sql
        
        # Get database URL from .env
        db_url = os.getenv("DATABASE_URL")
        
        if not db_url:
            print("❌ ERROR: DATABASE_URL not found in .env")
            return False
        
        print(f"📦 Connecting to database...")
        print(f"   URL: {db_url[:50]}...")
        
        # Parse connection string
        # Format: postgresql://user:password@host:port/database
        import urllib.parse
        parsed = urllib.parse.urlparse(db_url)
        
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path.lstrip('/'),
            user=parsed.username,
            password=parsed.password
        )
        
        cur = conn.cursor()
        
        print("✅ Connected to RDS PostgreSQL")
        
        # Create extensions
        print("\n📥 Creating pgvector extension...")
        try:
            cur.execute('CREATE EXTENSION IF NOT EXISTS "pgvector"')
            conn.commit()
            print("✅ pgvector extension created")
        except Exception as e:
            print(f"⚠️  pgvector creation: {e}")
            
        print("📥 Creating uuid-ossp extension...")
        try:
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            conn.commit()
            print("✅ uuid-ossp extension created")
        except Exception as e:
            print(f"⚠️  uuid-ossp creation: {e}")
        
        # Test vector type
        print("\n🧪 Testing vector support...")
        try:
            cur.execute("SELECT '[1,2,3]'::vector")
            result = cur.fetchone()
            print(f"✅ Vector type works: {result[0]}")
        except Exception as e:
            print(f"❌ Vector type failed: {e}")
            return False
        
        cur.close()
        conn.close()
        
        return True
        
    except ImportError:
        print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def create_schema():
    """Create database schema from schema.sql"""
    try:
        from sqlalchemy import create_engine, text
        
        db_url = os.getenv("DATABASE_URL")
        
        if not db_url:
            print("❌ DATABASE_URL not found in .env")
            return False
        
        print("\n📋 Creating database schema...")
        
        engine = create_engine(db_url)
        
        # Read schema file
        schema_path = "database/schema.sql"
        if not os.path.exists(schema_path):
            print(f"❌ Schema file not found: {schema_path}")
            return False
        
        with open(schema_path, 'r') as f:
            schema = f.read()
        
        # Execute schema
        with engine.connect() as conn:
            # Split by semicolon and execute each statement
            statements = schema.split(';')
            for stmt in statements:
                stmt = stmt.strip()
                if stmt:
                    try:
                        conn.execute(text(stmt))
                    except Exception as e:
                        # Some statements might fail if DB was already created
                        if "already exists" not in str(e).lower():
                            print(f"⚠️  {e}")
            
            conn.commit()
        
        print("✅ Database schema created successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error creating schema: {e}")
        return False


def test_connection():
    """Test database connection"""
    try:
        from sqlalchemy import create_engine, text
        
        db_url = os.getenv("DATABASE_URL")
        
        if not db_url:
            print("❌ DATABASE_URL not found in .env")
            return False
        
        print("\n🔌 Testing database connection...")
        
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Connection successful!")
            
            # Check extensions
            result = conn.execute(text("""
                SELECT extname FROM pg_extension 
                WHERE extname IN ('pgvector', 'uuid-ossp')
            """))
            extensions = [row[0] for row in result]
            
            if 'pgvector' in extensions:
                print("✅ pgvector extension found")
            else:
                print("❌ pgvector extension NOT found")
            
            if 'uuid-ossp' in extensions:
                print("✅ uuid-ossp extension found")
            else:
                print("❌ uuid-ossp extension NOT found")
            
            return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


def main():
    """Main setup wizard"""
    print("=" * 60)
    print("🚀 AWS RDS PostgreSQL Setup Helper")
    print("=" * 60)
    
    while True:
        print("\n📝 Choose an option:")
        print("1. Test database connection")
        print("2. Create pgvector extension")
        print("3. Create database schema")
        print("4. Full setup (test → extension → schema)")
        print("5. Exit")
        
        choice = input("\nEnter your choice (1-5): ").strip()
        
        if choice == "1":
            test_connection()
        elif choice == "2":
            setup_pgvector()
        elif choice == "3":
            create_schema()
        elif choice == "4":
            print("\n🔧 Running full setup...\n")
            if test_connection():
                if setup_pgvector():
                    create_schema()
                    print("\n✅ Full setup completed!")
        elif choice == "5":
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice")


if __name__ == "__main__":
    main()
