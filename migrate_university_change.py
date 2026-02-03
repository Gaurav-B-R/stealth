"""
Migration script to add university change fields to users table.
Run this script to add the pending_email, pending_university, 
university_change_token, and university_change_token_expires columns.
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Fix for Render's postgres:// URL (SQLAlchemy requires postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def migrate():
    """Add university change columns to users table."""
    columns_to_add = [
        ("pending_email", "VARCHAR", None),
        ("pending_university", "VARCHAR", None),
        ("university_change_token", "VARCHAR", None),
        ("university_change_token_expires", "TIMESTAMP WITH TIME ZONE", None),
    ]
    
    with engine.connect() as conn:
        for column_name, column_type, default in columns_to_add:
            try:
                # Check if column exists
                result = conn.execute(text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = '{column_name}'
                """))
                
                if result.fetchone() is None:
                    # Add column
                    if default:
                        sql = f"ALTER TABLE users ADD COLUMN {column_name} {column_type} DEFAULT {default}"
                    else:
                        sql = f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                    
                    conn.execute(text(sql))
                    conn.commit()
                    print(f"✅ Added column: {column_name}")
                else:
                    print(f"⏭️  Column already exists: {column_name}")
                    
            except Exception as e:
                print(f"❌ Error adding column {column_name}: {e}")
                conn.rollback()
        
        # Add unique index for university_change_token
        try:
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ix_users_university_change_token 
                ON users (university_change_token) 
                WHERE university_change_token IS NOT NULL
            """))
            conn.commit()
            print("✅ Added unique index for university_change_token")
        except Exception as e:
            print(f"⏭️  Index may already exist: {e}")
            conn.rollback()
    
    print("\n✅ Migration completed successfully!")

if __name__ == "__main__":
    print("Starting university change migration...")
    print(f"Database: {DATABASE_URL[:50]}...")
    migrate()
