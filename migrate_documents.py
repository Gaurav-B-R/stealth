"""
Migration script to add document upload functionality
Adds is_admin, is_developer columns to users table
Creates documents table
"""
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import os
from dotenv import load_dotenv

load_dotenv()

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rilono.db")

# Create engine
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def migrate():
    """Run migration to add document support"""
    print("Starting migration...")
    
    with engine.connect() as conn:
        # Check if we're using SQLite or PostgreSQL
        is_sqlite = DATABASE_URL.startswith("sqlite")
        
        try:
            # Add is_admin and is_developer columns to users table if they don't exist
            if is_sqlite:
                # SQLite doesn't support ALTER COLUMN easily, so we check first
                result = conn.execute("PRAGMA table_info(users)")
                columns = [row[1] for row in result]
                
                if 'is_admin' not in columns:
                    print("Adding is_admin column to users table...")
                    conn.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
                    conn.commit()
                
                if 'is_developer' not in columns:
                    print("Adding is_developer column to users table...")
                    conn.execute("ALTER TABLE users ADD COLUMN is_developer BOOLEAN DEFAULT 0")
                    conn.commit()
            else:
                # PostgreSQL
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
                    conn.commit()
                    print("Added is_admin column to users table")
                except Exception as e:
                    if "already exists" in str(e) or "duplicate column" in str(e).lower():
                        print("is_admin column already exists, skipping...")
                    else:
                        raise
                
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_developer BOOLEAN DEFAULT FALSE"))
                    conn.commit()
                    print("Added is_developer column to users table")
                except Exception as e:
                    if "already exists" in str(e) or "duplicate column" in str(e).lower():
                        print("is_developer column already exists, skipping...")
                    else:
                        raise
            
            # Create documents table
            print("Creating documents table...")
            if is_sqlite:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        filename VARCHAR NOT NULL,
                        original_filename VARCHAR NOT NULL,
                        file_url VARCHAR NOT NULL,
                        file_size INTEGER NOT NULL,
                        file_type VARCHAR,
                        document_type VARCHAR,
                        country VARCHAR,
                        intake VARCHAR,
                        year INTEGER,
                        description TEXT,
                        is_processed BOOLEAN DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        filename VARCHAR NOT NULL,
                        original_filename VARCHAR NOT NULL,
                        file_url VARCHAR NOT NULL,
                        file_size INTEGER NOT NULL,
                        file_type VARCHAR,
                        document_type VARCHAR,
                        country VARCHAR,
                        intake VARCHAR,
                        year INTEGER,
                        description TEXT,
                        is_processed BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                """))
            conn.commit()
            print("Documents table created successfully")
            
            # Create indexes
            print("Creating indexes...")
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at)"))
                conn.commit()
                print("Indexes created successfully")
            except Exception as e:
                print(f"Note: Some indexes may already exist: {e}")
            
            print("\n✅ Migration completed successfully!")
            print("\nNext steps:")
            print("1. Set R2_DOCUMENTS_BUCKET environment variable (default: 'documents')")
            print("2. Ensure R2 credentials are configured (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY)")
            print("3. To grant admin access to a user, update their is_admin or is_developer field in the database")
            
        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            conn.rollback()
            raise

if __name__ == "__main__":
    migrate()

