"""
Script to add developer email to developer_emails table for testing purposes.
This allows specific email addresses to bypass university domain validation.
Run this once to add your developer email.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from app.models import DeveloperEmail, Base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./student_marketplace.db")

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def add_dev_email():
    """Add developer email to developer_emails table."""
    # Create the table if it doesn't exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        dev_email_address = "23hometool@gmail.com"
        
        # Check if email already exists
        existing = db.query(DeveloperEmail).filter(
            DeveloperEmail.email == dev_email_address.lower()
        ).first()
        
        if existing:
            print(f"✅ {dev_email_address} already exists in developer_emails table.")
            print(f"   University: {existing.university_name}")
            return
        
        # Add developer email
        dev_email = DeveloperEmail(
            email=dev_email_address.lower(),
            university_name="Developer Account (Testing)"
        )
        
        db.add(dev_email)
        db.commit()
        print(f"✅ Successfully added {dev_email_address} to developer_emails table")
        print("   You can now register and login with this email address")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error adding developer email: {str(e)}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    add_dev_email()
