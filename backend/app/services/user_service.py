from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.user import User
from app.models.subscription import Subscription
from typing import Optional
import uuid


class UserService:
    """Service for managing users and their subscriptions."""
    
    @staticmethod
    def get_or_create_user(db: Session, clerk_id: str, email: str) -> User:
        """Get existing user or create a new one."""
        user = db.scalar(select(User).where(User.clerk_id == clerk_id))
        
        if not user:
            user = User(
                id=uuid.uuid4(),
                clerk_id=clerk_id,
                email=email
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            
            # Create free tier subscription
            subscription = Subscription(
                id=uuid.uuid4(),
                user_id=user.id,
                plan="free",
                query_limit=3,
                queries_used=0,
                status="active"
            )
            db.add(subscription)
            db.commit()
        
        return user
    
    @staticmethod
    def get_user_by_clerk_id(db: Session, clerk_id: str) -> Optional[User]:
        """Get user by Clerk ID."""
        return db.scalar(select(User).where(User.clerk_id == clerk_id))
    
    @staticmethod
    def get_user_subscription(db: Session, user_id: uuid.UUID) -> Optional[Subscription]:
        """Get user's subscription."""
        return db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    
    @staticmethod
    def increment_query_count(db: Session, user_id: uuid.UUID) -> bool:
        """Increment query count for user. Returns True if successful, False if limit reached."""
        subscription = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
        
        if not subscription:
            return False
        
        if not subscription.can_make_query():
            return False
        
        subscription.queries_used += 1
        db.commit()
        return True
    
    @staticmethod
    def reset_query_count(db: Session, user_id: uuid.UUID):
        """Reset query count (e.g., for new billing period)."""
        subscription = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
        
        if subscription:
            subscription.queries_used = 0
            db.commit()

