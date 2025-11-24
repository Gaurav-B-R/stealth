from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from app.database import get_db
from app import models, schemas
from app.auth import get_current_active_user

router = APIRouter(prefix="/api/items", tags=["items"])

@router.post("/", response_model=schemas.ItemResponse, status_code=status.HTTP_201_CREATED)
def create_item(
    item: schemas.ItemCreate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a new item listing"""
    db_item = models.Item(**item.dict(), seller_id=current_user.id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@router.get("/", response_model=List[schemas.ItemResponse])
def get_items(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    category: Optional[str] = None,
    search: Optional[str] = None,
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    sold_only: bool = False,
    db: Session = Depends(get_db)
):
    """Get all items with optional filtering"""
    query = db.query(models.Item)
    
    # Filter by sold status
    if not sold_only:
        query = query.filter(models.Item.is_sold == False)
    
    # Filter by category
    if category:
        query = query.filter(models.Item.category == category)
    
    # Search in title and description
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.Item.title.ilike(search_term),
                models.Item.description.ilike(search_term)
            )
        )
    
    # Price range filtering
    if min_price is not None:
        query = query.filter(models.Item.price >= min_price)
    if max_price is not None:
        query = query.filter(models.Item.price <= max_price)
    
    items = query.order_by(models.Item.created_at.desc()).offset(skip).limit(limit).all()
    return items

@router.get("/{item_id}", response_model=schemas.ItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db)):
    """Get a specific item by ID"""
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@router.put("/{item_id}", response_model=schemas.ItemResponse)
def update_item(
    item_id: int,
    item_update: schemas.ItemUpdate,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update an item (only by the seller)"""
    db_item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    if db_item.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this item")
    
    update_data = item_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_item, field, value)
    
    db.commit()
    db.refresh(db_item)
    return db_item

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: int,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete an item (only by the seller)"""
    db_item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    if db_item.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this item")
    
    db.delete(db_item)
    db.commit()
    return None

@router.get("/my/listings", response_model=List[schemas.ItemResponse])
def get_my_items(
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all items listed by the current user"""
    items = db.query(models.Item).filter(models.Item.seller_id == current_user.id).order_by(models.Item.created_at.desc()).all()
    return items

