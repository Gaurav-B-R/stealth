from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)  # Made nullable, will use email as username
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    university = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    profile_picture = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String, nullable=True, unique=True, index=True)
    verification_token_expires = Column(DateTime(timezone=True), nullable=True)
    password_reset_token = Column(String, nullable=True, unique=True, index=True)
    password_reset_token_expires = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    items = relationship("Item", back_populates="seller", cascade="all, delete-orphan")

class Item(Base):
    __tablename__ = "items"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    category = Column(String, nullable=True, index=True)
    condition = Column(String, nullable=True)  # new, like_new, good, fair
    image_url = Column(String, nullable=True)  # Deprecated: kept for backward compatibility
    address = Column(String, nullable=True)
    city = Column(String, nullable=True, index=True)
    state = Column(String, nullable=True, index=True)
    zip_code = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_sold = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    seller = relationship("User", back_populates="items")
    images = relationship("ItemImage", back_populates="item", cascade="all, delete-orphan", order_by="ItemImage.order")

class ItemImage(Base):
    __tablename__ = "item_images"
    
    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    image_url = Column(String, nullable=False)
    order = Column(Integer, default=0)  # Order of image display
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    item = relationship("Item", back_populates="images")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    item = relationship("Item")
    sender = relationship("User", foreign_keys=[sender_id])
    receiver = relationship("User", foreign_keys=[receiver_id])

class USUniversity(Base):
    __tablename__ = "us_universities"
    
    # Use email_domain as primary key since the table doesn't have an id column
    email_domain = Column(String, primary_key=True, nullable=False, index=True)
    university_name = Column(String, nullable=False, index=True)
    location = Column(String, nullable=True)

class DeveloperEmail(Base):
    __tablename__ = "developer_emails"
    
    email = Column(String, primary_key=True, nullable=False, index=True)
    university_name = Column(String, nullable=False, default="Developer Account")

