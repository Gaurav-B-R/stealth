"""
Script to add password reset columns to users table.
Run this once to add the new columns for password reset functionality.
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./student_marketplace.db")

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

def add_password_reset_columns():
    """Add password reset columns to users table."""
    with engine.connect() as conn:
        try:
            # Check if columns already exist
            if "sqlite" in DATABASE_URL.lower():
                # SQLite
                result = conn.execute(text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result]
                
                if "password_reset_token" not in columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN password_reset_token VARCHAR"))
                    print("✅ Added password_reset_token column")
                else:
                    print("✅ password_reset_token column already exists")
                
                if "password_reset_token_expires" not in columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN password_reset_token_expires TIMESTAMP"))
                    print("✅ Added password_reset_token_expires column")
                else:
                    print("✅ password_reset_token_expires column already exists")
                
                conn.commit()
            else:
                # PostgreSQL
                # Check if columns exist
                check_query = text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='users' AND column_name IN ('password_reset_token', 'password_reset_token_expires')
                """)
                result = conn.execute(check_query)
                existing_columns = [row[0] for row in result]
                
                if "password_reset_token" not in existing_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN password_reset_token VARCHAR UNIQUE"))
                    print("✅ Added password_reset_token column")
                else:
                    print("✅ password_reset_token column already exists")
                
                if "password_reset_token_expires" not in existing_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN password_reset_token_expires TIMESTAMP"))
                    print("✅ Added password_reset_token_expires column")
                else:
                    print("✅ password_reset_token_expires column already exists")
                
                conn.commit()
            
            print("\n✅ Password reset columns added successfully!")
            print("   The password reset feature is now ready to use.")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ Error adding password reset columns: {str(e)}")
            raise

if __name__ == "__main__":
    add_password_reset_columns()
