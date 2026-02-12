"""
Migration script to consolidate duplicate dev users created due to unstable clerk_user_id.

This script:
1. Identifies groups of users with similar dev_user_* clerk_user_ids
2. For each group, keeps the OLDEST user (first created)
3. Migrates all chat sessions/messages to the kept user
4. Deletes the duplicate users

⚠️ BACKUP YOUR DATABASE BEFORE RUNNING THIS SCRIPT!

Usage:
    python consolidate_duplicate_users.py --dry-run    # Preview changes
    python consolidate_duplicate_users.py --execute    # Apply changes
"""

import os
import sys
import argparse
from sqlalchemy import create_engine, text
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from config.database import _sanitize_db_url


def consolidate_duplicates(dry_run=True):
    """Consolidate duplicate dev users."""
    
    safe_db_url = _sanitize_db_url(settings.DATABASE_URL)
    engine = create_engine(safe_db_url)
    
    print("=" * 80)
    print("🔄 CONSOLIDATING DUPLICATE DEV USERS")
    print("=" * 80)
    print()
    
    if dry_run:
        print("⚠️  DRY RUN MODE - No changes will be made")
    else:
        print("🔥 EXECUTE MODE - Changes will be applied!")
        response = input("Are you sure you want to proceed? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return
    
    print()
    
    with engine.begin() as conn:  # Use begin() for transaction
        # 1. Find all dev_user_ users
        print("1️⃣  Finding all dev_user_ accounts...")
        print("-" * 80)
        
        result = conn.execute(text("""
            SELECT 
                user_id, 
                clerk_user_id, 
                tenant_id,
                email,
                created_at,
                (SELECT COUNT(*) FROM chat_sessions WHERE user_id = u.user_id AND is_deleted = false) as session_count
            FROM users u
            WHERE clerk_user_id LIKE 'dev_user_%' OR clerk_user_id LIKE 'dev_%'
            ORDER BY created_at ASC
        """))
        
        all_dev_users = result.fetchall()
        print(f"Found {len(all_dev_users)} dev user accounts")
        print()
        
        if not all_dev_users:
            print("✅ No dev users to consolidate")
            return
        
        # 2. Group users that should be consolidated
        # Strategy: Ask user to provide email mapping
        print("2️⃣  Identifying which users belong together...")
        print("-" * 80)
        
        # For now, let's just show what we have
        for user in all_dev_users:
            print(f"user_id: {str(user[0])[:8]}... | "
                  f"clerk: {user[1][:25]} | "
                  f"tenant: {str(user[2])[:8]}... | "
                  f"email: {user[3] or '(null)'} | "
                  f"created: {user[4]} | "
                  f"sessions: {user[5]}")
        
        print()
        print("3️⃣  Consolidation Strategy...")
        print("-" * 80)
        print("""
Since we don't have plaintext emails yet, we need to:

OPTION 1 - Manual Email Assignment:
    You provide the real email for each user, and we consolidate by email.
    
OPTION 2 - Keep All as Separate Users:
    Update their clerk_user_ids to be stable based on their existing tenant_id.
    
OPTION 3 - Delete and Start Fresh:
    Delete all dev users and let them re-authenticate with stable IDs.

Which option would you like?
1) Manual email assignment (recommended if you know the emails)
2) Keep all separate with stable IDs  
3) Delete all dev users
        """)
        
        if dry_run:
            print()
            print("⚠️  DRY RUN - No action taken")
            print()
            print("To consolidate users:")
            print("1. Identify which email belongs to which user")
            print("2. Run: python consolidate_duplicate_users.py --execute")
            return
        
        # Interactive mode
        choice = input("Enter choice (1/2/3): ").strip()
        
        if choice == "1":
            print()
            print("📧 MANUAL EMAIL ASSIGNMENT MODE")
            print("-" * 80)
            
            # Let user assign emails
            email_mapping = {}
            
            for user in all_dev_users:
                user_id = str(user[0])
                clerk_id = user[1]
                sessions = user[5]
                
                print(f"\nUser: {user_id[:8]}... | clerk: {clerk_id[:25]} | {sessions} sessions")
                email = input(f"Enter real email for this user (or 'skip'): ").strip()
                
                if email and email != 'skip':
                    email_mapping[user_id] = email.lower()
            
            print()
            print(f"Got {len(email_mapping)} email assignments")
            
            # Group users by email
            from collections import defaultdict
            email_groups = defaultdict(list)
            
            for user in all_dev_users:
                user_id = str(user[0])
                if user_id in email_mapping:
                    email = email_mapping[user_id]
                    email_groups[email].append(user)
            
            # For each email group, keep oldest user and migrate others
            for email, users in email_groups.items():
                if len(users) <= 1:
                    continue  # No duplicates
                
                # Sort by created_at (oldest first)
                users = sorted(users, key=lambda u: u[4])
                keep_user = users[0]
                duplicate_users = users[1:]
                
                print(f"\n📧 Email: {email}")
                print(f"   Keeping: {str(keep_user[0])[:8]}... (created {keep_user[4]})")
                print(f"   Consolidating {len(duplicate_users)} duplicates:")
                
                for dup in duplicate_users:
                    print(f"      - {str(dup[0])[:8]}... ({dup[5]} sessions)")
                
                # Migrate chat sessions
                for dup in duplicate_users:
                    dup_user_id = dup[0]
                    dup_tenant_id = dup[2]
                    keep_tenant_id = keep_user[2]
                    
                    # Update chat_sessions
                    result = conn.execute(text("""
                        UPDATE chat_sessions
                        SET user_id = :keep_user_id,
                            tenant_id = :keep_tenant_id
                        WHERE user_id = :dup_user_id
                    """), {
                        "keep_user_id": keep_user[0],
                        "keep_tenant_id": keep_tenant_id,
                        "dup_user_id": dup_user_id
                    })
                    print(f"         Migrated {result.rowcount} sessions")
                    
                    # Update documents
                    result = conn.execute(text("""
                        UPDATE documents
                        SET user_id = :keep_user_id,
                            tenant_id = :keep_tenant_id
                        WHERE user_id = :dup_user_id
                    """), {
                        "keep_user_id": keep_user[0],
                        "keep_tenant_id": keep_tenant_id,
                        "dup_user_id": dup_user_id
                    })
                    print(f"         Migrated {result.rowcount} documents")
                
                # Update the kept user with plaintext email and stable clerk_id
                import hashlib
                email_hash = hashlib.md5(email.encode()).hexdigest()[:12]
                stable_clerk_id = f"dev_{email_hash}"
                
                conn.execute(text("""
                    UPDATE users
                    SET email = :email,
                        clerk_user_id = :clerk_id
                    WHERE user_id = :user_id
                """), {
                    "email": email,
                    "clerk_id": stable_clerk_id,
                    "user_id": keep_user[0]
                })
                print(f"   Updated kept user: email={email}, clerk_id={stable_clerk_id}")
                
                # Delete duplicate users
                for dup in duplicate_users:
                    conn.execute(text("""
                        DELETE FROM users WHERE user_id = :user_id
                    """), {"user_id": dup[0]})
                
                print(f"   ✅ Consolidated {len(duplicate_users)} duplicates into one user")
        
        elif choice == "2":
            print()
            print("🔧 STABLE ID MODE - Updating all dev users with stable clerk_user_ids")
            print("-" * 80)
            
            for user in all_dev_users:
                user_id = user[0]
                tenant_id = user[2]
                old_clerk_id = user[1]
                
                # Generate stable ID from tenant_id
                import hashlib
                tenant_hash = hashlib.md5(str(tenant_id).encode()).hexdigest()[:12]
                new_clerk_id = f"dev_{tenant_hash}"
                
                conn.execute(text("""
                    UPDATE users
                    SET clerk_user_id = :new_clerk_id
                    WHERE user_id = :user_id
                """), {
                    "new_clerk_id": new_clerk_id,
                    "user_id": user_id
                })
                
                print(f"Updated {str(user_id)[:8]}...: {old_clerk_id} → {new_clerk_id}")
            
            print()
            print("✅ All dev users updated with stable clerk_user_ids")
        
        elif choice == "3":
            print()
            print("🗑️  DELETE ALL MODE - Removing all dev users")
            print("-" * 80)
            
            confirm = input("⚠️  This will delete ALL dev user data! Type 'DELETE' to confirm: ")
            if confirm != "DELETE":
                print("Aborted.")
                return
            
            # Delete will CASCADE to chat_sessions, messages, documents
            result = conn.execute(text("""
                DELETE FROM users 
                WHERE clerk_user_id LIKE 'dev_user_%' OR clerk_user_id LIKE 'dev_%'
            """))
            
            print(f"✅ Deleted {result.rowcount} dev users (and all their data via CASCADE)")
        
        else:
            print("Invalid choice. Aborted.")
            return
    
    print()
    print("=" * 80)
    print("✅ CONSOLIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consolidate duplicate dev users")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    parser.add_argument("--execute", action="store_true", help="Apply changes to database")
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("Error: Must specify either --dry-run or --execute")
        sys.exit(1)
    
    consolidate_duplicates(dry_run=args.dry_run)
