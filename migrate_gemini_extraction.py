"""
Database migration script to add extracted_text_file_url column to documents table.
Run this script to update your database schema without losing data.
"""
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rilono.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})

def migrate():
    """Add extracted_text_file_url column to documents table if it doesn't exist"""
    with engine.connect() as conn:
        # Check if column exists and add it if it doesn't
        try:
            conn.execute(text("""
                ALTER TABLE documents ADD COLUMN extracted_text_file_url TEXT
            """))
            print("✓ Added 'extracted_text_file_url' column to documents table")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ Column 'extracted_text_file_url' already exists in documents table")
            else:
                print(f"⚠ Error adding 'extracted_text_file_url' column: {e}")
        
        conn.commit()
        print("\n✅ Database migration completed successfully!")

if __name__ == "__main__":
    print("Running database migration for Gemini extraction feature...\n")
    migrate()

