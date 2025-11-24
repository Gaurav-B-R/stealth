from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    university: Optional[str] = None
    phone: Optional[str] = None

class UserCreate(UserBase):
    password: str

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

