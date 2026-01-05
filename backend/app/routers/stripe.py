from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import os
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.services.stripe_service import StripeService
from app.services.user_service import UserService

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
            success_url=request.success_url,
            cancel_url=request.cancel_url
        )
        return result
    except Exception as e:
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
        result = stripe_service.create_portal_session(
            customer_id=subscription.stripe_customer_id,
            return_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/dashboard"
        )
        return result
    except Exception as e:
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
    if event["type"] == "checkout.session.completed":
        # Subscription created
        session = event["data"]["object"]
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        
        # Find user by email or create customer mapping
        # Update subscription in database
        # This is simplified - you'd want to store customer_id -> user_id mapping
        
    elif event["type"] == "customer.subscription.updated":
        # Subscription updated
        subscription_data = event["data"]["object"]
        # Update subscription status, period, etc.
        
    elif event["type"] == "customer.subscription.deleted":
        # Subscription canceled
        subscription_data = event["data"]["object"]
        # Update subscription status to canceled
        
    return {"status": "success"}

