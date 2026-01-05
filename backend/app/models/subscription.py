from sqlalchemy import Column, String, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import uuid


class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True, index=True)
    stripe_customer_id = Column(String, unique=True, index=True)
    stripe_subscription_id = Column(String, unique=True, index=True)
    plan = Column(String, default="free")  # "free", "pro", "enterprise"
    query_limit = Column(Integer, default=5)  # Free tier: 5 queries
    queries_used = Column(Integer, default=0)
    status = Column(String, default="active")  # "active", "canceled", "past_due"
    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationship
    user = relationship("User", backref="subscription")
    
    def __repr__(self):
        return f"<Subscription(id={self.id}, user_id={self.user_id}, plan={self.plan}, queries_used={self.queries_used}/{self.query_limit})>"
    
    def can_make_query(self) -> bool:
        """Check if user can make a query based on their subscription."""
        return self.queries_used < self.query_limit
    
    def get_remaining_queries(self) -> int:
        """Get remaining queries for the user."""
        return max(0, self.query_limit - self.queries_used)

