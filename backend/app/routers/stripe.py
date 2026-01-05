from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import os
import stripe
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.subscription import Subscription
from app.services.stripe_service import StripeService
from app.services.user_service import UserService
from app.services.logger_service import get_logger

logger = get_logger("stripe_router")

router = APIRouter()
stripe_service = StripeService()


class CreateCheckoutRequest(BaseModel):
    success_url: str
    cancel_url: str


@router.post("/stripe/create-checkout")
async def create_checkout(
    request: CreateCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session for subscription."""
    subscription = UserService.get_user_subscription(db, current_user.id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    try:
        result = stripe_service.create_checkout_session(
            customer_id=subscription.stripe_customer_id,
            user_email=current_user.email,
            user_id=str(current_user.id),
            success_url=request.success_url,
            cancel_url=request.cancel_url
        )
        return result
    except Exception as e:
        logger.log_error("checkout_session_creation_failed", str(e), context={"user_id": str(current_user.id)})
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stripe/create-portal")
async def create_portal(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create Stripe customer portal session."""
    subscription = UserService.get_user_subscription(db, current_user.id)
    
    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    try:
        frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')
        result = stripe_service.create_portal_session(
            customer_id=subscription.stripe_customer_id,
            return_url=f"{frontend_url}/subscription"
        )
        return result
    except Exception as e:
        logger.log_error("portal_session_creation_failed", str(e), context={"user_id": str(current_user.id)})
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stripe/cancel-subscription")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel subscription and downgrade to free tier."""
    subscription = UserService.get_user_subscription(db, current_user.id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    if subscription.plan != "premium":
        raise HTTPException(status_code=400, detail="No active premium subscription to cancel")
    
    try:
        # Cancel subscription in Stripe if it exists
        if subscription.stripe_subscription_id:
            # Cancel at end of billing period so user gets full value
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                cancel_at_period_end=True
            )
            # Update status to indicate cancellation is scheduled
            subscription.status = "canceled"
            db.commit()
            
            logger.log_query(
                question="subscription_cancel_scheduled",
                user_id=str(current_user.id),
                success=True,
                zip_code=None
            )
            
            return {
                "status": "success", 
                "message": "Subscription will be canceled at the end of the current billing period. You'll continue to have access until then."
            }
        else:
            # No Stripe subscription, just downgrade in our system
            UserService.downgrade_to_free(db=db, user_id=str(current_user.id))
            return {"status": "success", "message": "Subscription canceled successfully"}
    except stripe.error.StripeError as e:
        logger.log_error("stripe_cancel_failed", str(e), context={"user_id": str(current_user.id)})
        raise HTTPException(status_code=500, detail=f"Failed to cancel subscription: {str(e)}")
    except Exception as e:
        logger.log_error("cancel_subscription_failed", str(e), context={"user_id": str(current_user.id)})
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """Handle Stripe webhook events."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    
    try:
        event = stripe_service.verify_webhook(payload, signature)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Handle different event types
    try:
        if event["type"] == "checkout.session.completed":
            # Subscription created - upgrade user to premium
            session = event["data"]["object"]
            customer_id = session.get("customer")
            subscription_id = session.get("subscription")
            user_id = session.get("metadata", {}).get("user_id")
            
            if not user_id:
                logger.log_error("webhook_missing_user_id", "checkout.session.completed missing user_id in metadata")
                return {"status": "error", "message": "Missing user_id in metadata"}
            
            # Update user subscription to premium
            UserService.upgrade_to_premium(
                db=db,
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id
            )
            
            logger.log_query(
                question="subscription_upgraded",
                user_id=user_id,
                success=True,
                zip_code=None
            )
            
        elif event["type"] == "customer.subscription.updated":
            # Subscription updated (e.g., billing period renewed)
            subscription_data = event["data"]["object"]
            stripe_subscription_id = subscription_data.get("id")
            customer_id = subscription_data.get("customer")
            subscription_status = subscription_data.get("status", "active")
            
            # Find subscription by Stripe subscription ID
            subscription = db.scalar(
                select(Subscription).where(Subscription.stripe_subscription_id == stripe_subscription_id)
            )
            
            if subscription:
                previous_status = subscription.status
                subscription.status = subscription_status
                
                # Only reset queries if subscription was reactivated (status changed to active)
                # The invoice.payment_succeeded event handles monthly renewals
                if (subscription.plan == "premium" 
                    and subscription_status == "active" 
                    and previous_status != "active"):
                    # Reset queries on reactivation (e.g., after payment issue resolved)
                    subscription.queries_used = 0
                    logger.log_query(
                        question="queries_reset_on_subscription_reactivation",
                        user_id=str(subscription.user_id),
                        success=True,
                        zip_code=None
                    )
                
                db.commit()
                
                logger.log_query(
                    question="subscription_updated",
                    user_id=str(subscription.user_id),
                    success=True,
                    zip_code=None
                )
        
        elif event["type"] == "customer.subscription.deleted":
            # Subscription canceled - downgrade to free
            subscription_data = event["data"]["object"]
            stripe_subscription_id = subscription_data.get("id")
            
            # Find subscription by Stripe subscription ID
            subscription = db.scalar(
                select(Subscription).where(Subscription.stripe_subscription_id == stripe_subscription_id)
            )
            
            if subscription:
                UserService.downgrade_to_free(db=db, user_id=str(subscription.user_id))
                
                logger.log_query(
                    question="subscription_canceled",
                    user_id=str(subscription.user_id),
                    success=True,
                    zip_code=None
                )
        
        elif event["type"] == "invoice.payment_succeeded":
            # Payment succeeded - reset queries for premium users on new billing period
            invoice = event["data"]["object"]
            stripe_subscription_id = invoice.get("subscription")
            billing_reason = invoice.get("billing_reason")
            
            if stripe_subscription_id:
                subscription = db.scalar(
                    select(Subscription).where(Subscription.stripe_subscription_id == stripe_subscription_id)
                )
                
                if subscription and subscription.plan == "premium":
                    # Reset query count for new billing period
                    # billing_reason values:
                    # - subscription_create: Initial subscription payment
                    # - subscription_cycle: Monthly renewal payment
                    # - subscription_update: Subscription plan change
                    # We reset on all of these to ensure queries reset monthly
                    if billing_reason in ["subscription_cycle", "subscription_create", "subscription_update"]:
                        subscription.queries_used = 0
                        db.commit()
                        
                        logger.log_query(
                            question="queries_reset_on_payment",
                            user_id=str(subscription.user_id),
                            success=True,
                            zip_code=None
                        )
        
    except Exception as e:
        logger.log_error("webhook_processing_error", str(e), context={"event_type": event.get("type")})
        # Don't raise exception - return success to Stripe to prevent retries
        # Log the error for manual investigation
    
    return {"status": "success"}

