"""
Database migration script to add is_valid and validation_message columns to documents table.
Run this script to update your database schema without losing data.
"""
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rilono.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})

def migrate():
    """Add is_valid and validation_message columns to documents table if they don't exist"""
    with engine.connect() as conn:
        # Check if is_valid column exists and add it if it doesn't
        try:
            conn.execute(text("""
                ALTER TABLE documents ADD COLUMN is_valid BOOLEAN
            """))
            print("✓ Added 'is_valid' column to documents table")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print("✓ Column 'is_valid' already exists in documents table")
            else:
                print(f"⚠ Error adding 'is_valid' column: {e}")
        
        # Check if validation_message column exists and add it if it doesn't
        try:
            conn.execute(text("""
                ALTER TABLE documents ADD COLUMN validation_message TEXT
            """))
            print("✓ Added 'validation_message' column to documents table")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print("✓ Column 'validation_message' already exists in documents table")
            else:
                print(f"⚠ Error adding 'validation_message' column: {e}")
        
        conn.commit()
        print("\n✅ Database migration completed successfully!")

if __name__ == "__main__":
    print("Running database migration for document validation fields...\n")
    migrate()
