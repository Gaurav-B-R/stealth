"""
Database migration script to add new columns to existing database.
Run this script to update your database schema without losing data.
"""
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./student_marketplace.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})

def migrate():
    """Add new columns to items table if they don't exist"""
    with engine.connect() as conn:
        # Check if columns exist and add them if they don't
        try:
            # For SQLite, we need to check and add columns one by one
            conn.execute(text("""
                ALTER TABLE items ADD COLUMN address TEXT
            """))
            print("✓ Added 'address' column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ Column 'address' already exists")
            else:
                print(f"⚠ Error adding 'address': {e}")
        
        try:
            conn.execute(text("""
                ALTER TABLE items ADD COLUMN city TEXT
            """))
            print("✓ Added 'city' column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ Column 'city' already exists")
            else:
                print(f"⚠ Error adding 'city': {e}")
        
        try:
            conn.execute(text("""
                ALTER TABLE items ADD COLUMN state TEXT
            """))
            print("✓ Added 'state' column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ Column 'state' already exists")
            else:
                print(f"⚠ Error adding 'state': {e}")
        
        try:
            conn.execute(text("""
                ALTER TABLE items ADD COLUMN zip_code TEXT
            """))
            print("✓ Added 'zip_code' column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ Column 'zip_code' already exists")
            else:
                print(f"⚠ Error adding 'zip_code': {e}")
        
        try:
            conn.execute(text("""
                ALTER TABLE items ADD COLUMN latitude REAL
            """))
            print("✓ Added 'latitude' column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ Column 'latitude' already exists")
            else:
                print(f"⚠ Error adding 'latitude': {e}")
        
        try:
            conn.execute(text("""
                ALTER TABLE items ADD COLUMN longitude REAL
            """))
            print("✓ Added 'longitude' column")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ Column 'longitude' already exists")
            else:
                print(f"⚠ Error adding 'longitude': {e}")
        
        # Create messages table if it doesn't exist
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    sender_id INTEGER NOT NULL,
                    receiver_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    is_read BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(item_id) REFERENCES items (id),
                    FOREIGN KEY(sender_id) REFERENCES users (id),
                    FOREIGN KEY(receiver_id) REFERENCES users (id)
                )
            """))
            print("✓ Created 'messages' table")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("✓ Table 'messages' already exists")
            else:
                print(f"⚠ Error creating 'messages' table: {e}")
        
        # Create item_images table if it doesn't exist
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS item_images (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    image_url VARCHAR NOT NULL,
                    "order" INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(item_id) REFERENCES items (id)
                )
            """))
            print("✓ Created 'item_images' table")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("✓ Table 'item_images' already exists")
            else:
                print(f"⚠ Error creating 'item_images' table: {e}")
        
        # Add profile_picture column to users table
        try:
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN profile_picture TEXT
            """))
            print("✓ Added 'profile_picture' column to users table")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("✓ Column 'profile_picture' already exists in users table")
            else:
                print(f"⚠ Error adding 'profile_picture' column: {e}")
        
        conn.commit()
        print("\n✅ Database migration completed successfully!")

if __name__ == "__main__":
    print("Running database migration...\n")
    migrate()

