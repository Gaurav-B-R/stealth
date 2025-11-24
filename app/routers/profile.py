from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user

router = APIRouter(prefix="/api/profile", tags=["profile"])

@router.get("/", response_model=schemas.UserResponse)
def get_profile(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get current user's profile"""
    return current_user

@router.put("/", response_model=schemas.UserResponse)
def update_profile(
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update current user's profile"""
    update_data = user_update.dict(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(current_user, field, value)
    
    db.commit()
    db.refresh(current_user)
    return current_user

@router.get("/{user_id}", response_model=schemas.UserResponse)
def get_user_profile(
    user_id: int,
    db: Session = Depends(get_db)
):
    """Get a user's public profile (limited info)"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Return public profile (exclude sensitive info)
    return user

@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete the current user's account and all associated data"""
    user_id = current_user.id
    
    # Delete all messages where user is sender or receiver
    db.query(models.Message).filter(
        (models.Message.sender_id == user_id) | (models.Message.receiver_id == user_id)
    ).delete()
    
    # Items and ItemImages will be deleted automatically due to cascade="all, delete-orphan"
    # But we need to delete the user explicitly
    db.delete(current_user)
    db.commit()
    
    return None

