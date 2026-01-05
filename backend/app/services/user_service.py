from sqlalchemy.orm import Session
from sqlalchemy import select, delete
from app.models.user import User
from app.models.subscription import Subscription
from app.models.query import Query
from app.services.logger_service import get_logger
from app.services.stripe_service import StripeService
from typing import Optional
import uuid


logger = get_logger("user_service")


class UserService:
    """Service for managing users and their subscriptions."""
    
    @staticmethod
    def get_or_create_user(db: Session, clerk_id: str, email: str) -> User:
        """
        Get existing user or create a new one.
        
        First checks by clerk_id, then by email to prevent duplicate accounts
        when Clerk generates different IDs for the same email address.
        """
        # First, try to find user by clerk_id (primary lookup)
        user = db.scalar(select(User).where(User.clerk_id == clerk_id))
        
        if user:
            return user
        
        # If not found by clerk_id, check by email to prevent duplicates
        # This handles cases where Clerk generates different IDs for the same email
        existing_user = db.scalar(select(User).where(User.email == email))
        
        if existing_user:
            # Found user with same email but different clerk_id
            logger.log_error(
                "duplicate_account_detected",
                f"Found existing user with email {email} but different clerk_id. "
                f"Existing clerk_id: {existing_user.clerk_id}, New clerk_id: {clerk_id}. "
                f"Updating clerk_id to match current session.",
                context={
                    "existing_clerk_id": existing_user.clerk_id,
                    "new_clerk_id": clerk_id,
                    "email": email,
                    "user_id": str(existing_user.id)
                }
            )
            
            # Update the clerk_id to the current one (Clerk is the source of truth)
            # This ensures future lookups by clerk_id will find this user
            existing_user.clerk_id = clerk_id
            db.commit()
            db.refresh(existing_user)
            
            return existing_user
        
        # No user found with either clerk_id or email, create new user
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
        
        logger.log_query(
            question="user_created",
            user_id=str(user.id),
            success=True,
            zip_code=None
        )
        
        return user
    
    @staticmethod
    def get_user_by_clerk_id(db: Session, clerk_id: str) -> Optional[User]:
        """Get user by Clerk ID."""
        return db.scalar(select(User).where(User.clerk_id == clerk_id))
    
    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        """Get user by email address."""
        return db.scalar(select(User).where(User.email == email))
    
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
    
    @staticmethod
    def upgrade_to_premium(
        db: Session,
        user_id: str,
        stripe_customer_id: str,
        stripe_subscription_id: str
    ):
        """Upgrade user subscription to premium."""
        subscription = db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(user_id)))
        
        if not subscription:
            logger.log_error("upgrade_subscription_not_found", f"Subscription not found for user {user_id}")
            return
        
        subscription.plan = "premium"
        subscription.query_limit = 999999  # Effectively unlimited
        subscription.queries_used = 0  # Reset on upgrade
        subscription.status = "active"
        subscription.stripe_customer_id = stripe_customer_id
        subscription.stripe_subscription_id = stripe_subscription_id
        
        db.commit()
        logger.log_query(
            question="user_upgraded_to_premium",
            user_id=user_id,
            success=True,
            zip_code=None
        )
    
    @staticmethod
    def downgrade_to_free(db: Session, user_id: str):
        """Downgrade user subscription to free tier."""
        subscription = db.scalar(select(Subscription).where(Subscription.user_id == uuid.UUID(user_id)))
        
        if not subscription:
            logger.log_error("downgrade_subscription_not_found", f"Subscription not found for user {user_id}")
            return
        
        subscription.plan = "free"
        subscription.query_limit = 3
        subscription.queries_used = 0  # Reset on downgrade
        subscription.status = "canceled"
        subscription.stripe_subscription_id = None  # Keep customer_id for potential re-subscription
        
        db.commit()
        logger.log_query(
            question="user_downgraded_to_free",
            user_id=user_id,
            success=True,
            zip_code=None
        )
    
    @staticmethod
    def delete_user_by_clerk_id(db: Session, clerk_id: str) -> bool:
        """
        Delete user and all associated data by Clerk ID.
        
        This method:
        1. Finds the user by clerk_id
        2. Cancels any active Stripe subscription
        3. Deletes Stripe customer (if exists)
        4. Deletes all queries associated with the user
        5. Deletes the subscription associated with the user
        6. Deletes the user record
        
        Returns True if user was found and deleted, False otherwise.
        """
        user = db.scalar(select(User).where(User.clerk_id == clerk_id))
        
        if not user:
            logger.log_error(
                "user_not_found_for_deletion",
                f"User with clerk_id {clerk_id} not found for deletion",
                context={"clerk_id": clerk_id}
            )
            return False
        
        user_id = user.id
        
        try:
            # Get subscription before deletion to check for Stripe subscription
            subscription = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
            
            # Cancel Stripe subscription and delete customer if they exist
            if subscription:
                stripe_service = StripeService()
                
                # Cancel subscription in Stripe if it exists
                if subscription.stripe_subscription_id:
                    try:
                        stripe_service.cancel_subscription(subscription.stripe_subscription_id)
                        logger.log_query(
                            question="stripe_subscription_canceled_on_user_deletion",
                            user_id=str(user_id),
                            success=True,
                            zip_code=None
                        )
                    except Exception as e:
                        logger.log_error(
                            "stripe_subscription_cancel_failed",
                            f"Failed to cancel Stripe subscription {subscription.stripe_subscription_id}: {str(e)}",
                            context={"user_id": str(user_id), "subscription_id": subscription.stripe_subscription_id}
                        )
                
                # Delete Stripe customer if it exists
                if subscription.stripe_customer_id:
                    try:
                        stripe_service.delete_customer(subscription.stripe_customer_id)
                        logger.log_query(
                            question="stripe_customer_deleted_on_user_deletion",
                            user_id=str(user_id),
                            success=True,
                            zip_code=None
                        )
                    except Exception as e:
                        logger.log_error(
                            "stripe_customer_delete_failed",
                            f"Failed to delete Stripe customer {subscription.stripe_customer_id}: {str(e)}",
                            context={"user_id": str(user_id), "customer_id": subscription.stripe_customer_id}
                        )
            
            # Delete all queries associated with the user
            db.execute(delete(Query).where(Query.user_id == user_id))
            
            # Delete subscription associated with the user
            db.execute(delete(Subscription).where(Subscription.user_id == user_id))
            
            # Delete the user
            db.execute(delete(User).where(User.id == user_id))
            
            db.commit()
            
            logger.log_query(
                question="user_deleted",
                user_id=str(user_id),
                success=True,
                zip_code=None
            )
            
            return True
            
        except Exception as e:
            db.rollback()
            logger.log_error(
                "user_deletion_failed",
                f"Failed to delete user with clerk_id {clerk_id}: {str(e)}",
                context={"clerk_id": clerk_id, "user_id": str(user_id)}
            )
            raise

