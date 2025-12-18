from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None  # Optional, will be auto-generated from email if not provided
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None
    profile_picture: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None
    profile_picture: Optional[str] = None

class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class ItemImageResponse(BaseModel):
    id: int
    image_url: str
    order: int
    
    class Config:
        from_attributes = True

class ItemBase(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: Optional[str] = None
    condition: Optional[str] = None
    image_url: Optional[str] = None  # Deprecated: kept for backward compatibility
    image_urls: Optional[List[str]] = None  # For creating items with multiple images
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class ItemCreate(ItemBase):
    pass

class ItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    condition: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: Optional[List[str]] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_sold: Optional[bool] = None

class ItemResponse(ItemBase):
    id: int
    seller_id: int
    seller: UserResponse
    is_sold: bool
    images: List[ItemImageResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    item_id: int
    receiver_id: int
    content: str

class MessageResponse(BaseModel):
    id: int
    item_id: int
    sender_id: int
    receiver_id: int
    content: str
    is_read: bool
    created_at: datetime
    sender: UserResponse
    receiver: UserResponse
    
    class Config:
        from_attributes = True

class ConversationResponse(BaseModel):
    other_user: UserResponse
    item: ItemResponse
    last_message: Optional[MessageResponse] = None
    unread_count: int = 0
    
    class Config:
        from_attributes = True

class UniversityInfo(BaseModel):
    university_name: Optional[str] = None
    email_domain: str
    is_valid: bool

