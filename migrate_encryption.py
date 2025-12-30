"""
Migration script to add Zero-Knowledge encryption support
Adds encryption_salt column to users table
Adds encrypted_file_key column to documents table
"""
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./student_marketplace.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})

def migrate():
    """Run migration to add encryption support"""
    print("Starting Zero-Knowledge encryption migration...")
    
    with engine.connect() as conn:
        is_sqlite = DATABASE_URL.startswith("sqlite")
        
        try:
            # Add encryption_salt column to users table
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result]
                
                if 'encryption_salt' not in columns:
                    print("Adding encryption_salt column to users table...")
                    conn.execute(text("ALTER TABLE users ADD COLUMN encryption_salt VARCHAR"))
                    conn.commit()
                    print("✓ Added encryption_salt column")
                else:
                    print("✓ encryption_salt column already exists")
            else:
                # PostgreSQL
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN encryption_salt VARCHAR"))
                    conn.commit()
                    print("✓ Added encryption_salt column to users table")
                except Exception as e:
                    if "already exists" in str(e) or "duplicate column" in str(e).lower():
                        print("✓ encryption_salt column already exists")
                    else:
                        raise
            
            # Add encrypted_file_key column to documents table
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(documents)"))
                columns = [row[1] for row in result]
                
                if 'encrypted_file_key' not in columns:
                    print("Adding encrypted_file_key column to documents table...")
                    conn.execute(text("ALTER TABLE documents ADD COLUMN encrypted_file_key TEXT"))
                    conn.commit()
                    print("✓ Added encrypted_file_key column")
                else:
                    print("✓ encrypted_file_key column already exists")
            else:
                # PostgreSQL
                try:
                    conn.execute(text("ALTER TABLE documents ADD COLUMN encrypted_file_key TEXT"))
                    conn.commit()
                    print("✓ Added encrypted_file_key column to documents table")
                except Exception as e:
                    if "already exists" in str(e) or "duplicate column" in str(e).lower():
                        print("✓ encrypted_file_key column already exists")
                    else:
                        raise
            
            conn.commit()
            print("\n✅ Zero-Knowledge encryption migration completed successfully!")
            print("\nImportant Notes:")
            print("1. New documents will be encrypted with Zero-Knowledge architecture")
            print("2. Users must provide their password to upload and download documents")
            print("3. Even admins cannot decrypt documents without the user's password")
            print("4. If a user forgets their password, their encrypted documents cannot be recovered")
            print("5. Existing documents (without encrypted_file_key) will remain unencrypted for backward compatibility")
            
        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            conn.rollback()
            raise

if __name__ == "__main__":
    migrate()



