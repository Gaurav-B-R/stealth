"""
Migration script to add documentation preference fields to users table.
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Fix for Render's postgres:// URL
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def migrate():
    """Add documentation preference columns to users table."""
    columns_to_add = [
        ("preferred_country", "VARCHAR", "'United States'"),
        ("preferred_intake", "VARCHAR", None),
        ("preferred_year", "INTEGER", None),
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
    
    print("\n✅ Migration completed successfully!")

if __name__ == "__main__":
    print("Starting documentation preferences migration...")
    migrate()
