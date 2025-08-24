from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db, get_current_active_user
from app.core.database import User as UserModel
from app.schemas.user import User, UserUpdate
from app.core.auth import get_password_hash

router = APIRouter()

@router.get("/profile", response_model=User)
async def get_user_profile(current_user: UserModel = Depends(get_current_active_user)):
    """Get current user profile"""
    return current_user

@router.put("/profile", response_model=User)
async def update_user_profile(
    user_update: UserUpdate,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update current user profile"""
    
    # Update fields
    for field, value in user_update.dict(exclude_unset=True).items():
        if field == "password" and value:
            value = get_password_hash(value)
        setattr(current_user, field, value)
    
    db.commit()
    db.refresh(current_user)
    
    return current_user

@router.delete("/profile")
async def delete_user_profile(
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete current user profile (soft delete)"""
    
    current_user.is_active = False
    db.commit()
    
    return {"message": "User profile deactivated successfully"}
