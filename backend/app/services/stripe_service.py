import stripe
from typing import Optional, Dict, Any
from pydantic_settings import BaseSettings


class StripeSettings(BaseSettings):
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_price_id: str  # Price ID for Premium plan
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields from .env file


class StripeService:
    """Service for handling Stripe operations."""
    
    def __init__(self):
        self.settings = StripeSettings()
        stripe.api_key = self.settings.stripe_secret_key
    
    def create_checkout_session(
        self,
        customer_id: Optional[str],
        user_email: str,
        user_id: str,
        success_url: str,
        cancel_url: str
    ) -> Dict[str, Any]:
        """Create a Stripe checkout session."""
        session_params = {
            "payment_method_types": ["card"],
            "line_items": [{
                "price": self.settings.stripe_price_id,
                "quantity": 1,
            }],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {
                "user_id": user_id,
            },
        }
        
        # Stripe only allows one of: customer or customer_email
        # Use customer if we have a customer_id, otherwise use customer_email
        if customer_id:
            session_params["customer"] = customer_id
        else:
            session_params["customer_email"] = user_email
        
        session = stripe.checkout.Session.create(**session_params)
        return {
            "session_id": session.id,
            "url": session.url
        }
    
    def create_portal_session(self, customer_id: str, return_url: str) -> Dict[str, Any]:
        """Create a Stripe customer portal session."""
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return {"url": session.url}
    
    def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel a Stripe subscription."""
        try:
            stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
            return True
        except stripe.error.StripeError as e:
            # Subscription might already be canceled or not found
            return False
    
    def delete_customer(self, customer_id: str) -> bool:
        """Delete a Stripe customer."""
        try:
            stripe.Customer.delete(customer_id)
            return True
        except stripe.error.StripeError as e:
            # Customer might already be deleted or not found
            return False
    
    def verify_webhook(self, payload: bytes, signature: str) -> Dict[str, Any]:
        """Verify Stripe webhook signature."""
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.settings.stripe_webhook_secret
            )
            return event
        except ValueError:
            raise ValueError("Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise ValueError("Invalid signature")

