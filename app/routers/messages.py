from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user

router = APIRouter(prefix="/api/messages", tags=["messages"])

@router.post("/", response_model=schemas.MessageResponse, status_code=status.HTTP_201_CREATED)
def send_message(
    message: schemas.MessageCreate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Send a message about an item"""
    # Verify item exists
    item = db.query(models.Item).filter(models.Item.id == message.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Verify receiver exists
    receiver = db.query(models.User).filter(models.User.id == message.receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")
    
    # Verify user is not messaging themselves
    if current_user.id == message.receiver_id:
        raise HTTPException(status_code=400, detail="Cannot send message to yourself")
    
    # Check if this is a new conversation or a reply
    existing_conversation = db.query(models.Message).filter(
        and_(
            models.Message.item_id == message.item_id,
            or_(
                and_(models.Message.sender_id == current_user.id, models.Message.receiver_id == message.receiver_id),
                and_(models.Message.sender_id == message.receiver_id, models.Message.receiver_id == current_user.id)
            )
        )
    ).first()
    
    # If it's a new conversation, verify the sender is not the seller
    # (Sellers can reply to existing conversations, but buyers initiate conversations)
    if not existing_conversation and current_user.id == item.seller_id:
        raise HTTPException(
            status_code=400, 
            detail="Sellers cannot initiate conversations about their own items. Wait for buyers to message you first."
        )
    
    # Create message
    db_message = models.Message(
        item_id=message.item_id,
        sender_id=current_user.id,
        receiver_id=message.receiver_id,
        content=message.content
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

@router.get("/conversations", response_model=List[schemas.ConversationResponse])
def get_conversations(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all conversations for the current user"""
    # Get all messages involving the current user
    all_messages = db.query(models.Message).filter(
        or_(
            models.Message.sender_id == current_user.id,
            models.Message.receiver_id == current_user.id
        )
    ).order_by(models.Message.created_at.desc()).all()
    
    # Group by (item_id, other_user_id)
    conversations_dict = {}
    
    for message in all_messages:
        # Determine the other user
        if message.sender_id == current_user.id:
            other_user_id = message.receiver_id
        else:
            other_user_id = message.sender_id
        
        key = (message.item_id, other_user_id)
        
        # Only keep the first (most recent) message for each conversation
        if key not in conversations_dict:
            conversations_dict[key] = message
    
    conversations = []
    
    for (item_id, other_user_id), last_message in conversations_dict.items():
        # Get the other user
        other_user = db.query(models.User).filter(models.User.id == other_user_id).first()
        if not other_user:
            continue
        
        # Get the item
        item = db.query(models.Item).filter(models.Item.id == item_id).first()
        if not item:
            continue
        
        # Count unread messages
        unread_count = db.query(models.Message).filter(
            and_(
                models.Message.item_id == item_id,
                models.Message.receiver_id == current_user.id,
                models.Message.sender_id == other_user_id,
                models.Message.is_read == False
            )
        ).count()
        
        # Create response object (using model_validate for Pydantic v2)
        conv_response = schemas.ConversationResponse(
            other_user=schemas.UserResponse.model_validate(other_user),
            item=schemas.ItemResponse.model_validate(item),
            last_message=schemas.MessageResponse.model_validate(last_message) if last_message else None,
            unread_count=unread_count
        )
        conversations.append(conv_response)
    
    # Sort by last message time (most recent first)
    conversations.sort(key=lambda x: x.last_message.created_at if x.last_message else datetime.min, reverse=True)
    
    return conversations

@router.get("/conversation/{item_id}/{other_user_id}", response_model=List[schemas.MessageResponse])
def get_conversation_messages(
    item_id: int,
    other_user_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all messages in a conversation"""
    # Verify user is part of this conversation
    messages = db.query(models.Message).filter(
        and_(
            models.Message.item_id == item_id,
            or_(
                and_(models.Message.sender_id == current_user.id, models.Message.receiver_id == other_user_id),
                and_(models.Message.sender_id == other_user_id, models.Message.receiver_id == current_user.id)
            )
        )
    ).order_by(models.Message.created_at.asc()).all()
    
    # Mark messages as read
    for message in messages:
        if message.receiver_id == current_user.id and not message.is_read:
            message.is_read = True
    
    db.commit()
    
    return messages

@router.get("/unread-count", response_model=dict)
def get_unread_count(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get total unread message count"""
    count = db.query(models.Message).filter(
        and_(
            models.Message.receiver_id == current_user.id,
            models.Message.is_read == False
        )
    ).count()
    
    return {"unread_count": count}

@router.delete("/conversation/{item_id}/{other_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    item_id: int,
    other_user_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete all messages in a conversation"""
    # Verify user is part of this conversation
    messages = db.query(models.Message).filter(
        and_(
            models.Message.item_id == item_id,
            or_(
                and_(models.Message.sender_id == current_user.id, models.Message.receiver_id == other_user_id),
                and_(models.Message.sender_id == other_user_id, models.Message.receiver_id == current_user.id)
            )
        )
    ).all()
    
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Delete all messages in the conversation
    for message in messages:
        db.delete(message)
    
    db.commit()
    return None

