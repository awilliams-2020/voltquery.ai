from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, func
from typing import List
from app.models.query import Query
from app.models.user import User
from app.middleware.auth import get_current_user
from app.database import get_db
from app.services.user_service import UserService
from pydantic import BaseModel

router = APIRouter()


class QueryHistoryItem(BaseModel):
    id: str
    question: str
    answer: str
    zip_code: str | None
    sources_count: int
    created_at: str


@router.get("/history/queries")
async def get_query_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0
):
    """Get user's query history."""
    queries = db.scalars(
        select(Query)
        .where(Query.user_id == current_user.id)
        .order_by(desc(Query.created_at))
        .limit(limit)
        .offset(offset)
    ).all()
    
    return [
        QueryHistoryItem(
            id=str(q.id),
            question=q.question,
            answer=q.answer,
            zip_code=q.zip_code,
            sources_count=q.sources_count,
            created_at=q.created_at.isoformat() if q.created_at else ""
        )
        for q in queries
    ]


@router.get("/history/stats")
async def get_query_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's query statistics."""
    subscription = UserService.get_user_subscription(db, current_user.id)
    total_queries = db.scalar(
        select(func.count(Query.id)).where(Query.user_id == current_user.id)
    ) or 0
    
    return {
        "total_queries": total_queries,
        "queries_used": subscription.queries_used if subscription else 0,
        "queries_remaining": subscription.get_remaining_queries() if subscription else 0,
        "query_limit": subscription.query_limit if subscription else 3,
        "plan": subscription.plan if subscription else "free"
    }

