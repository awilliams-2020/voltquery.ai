from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any
from app.services.rag_service import RAGService
from app.services.llm_service import LLMService
from app.services.user_service import UserService
from app.middleware.auth import get_current_user
from app.models.user import User
from app.database import get_db
import uuid

router = APIRouter()
llm_service = LLMService()


class RAGQueryRequest(BaseModel):
    question: str
    zip_code: Optional[str] = None
    top_k: int = 5


class DetectedLocation(BaseModel):
    type: Optional[str] = None
    zip_code: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None


class RAGQueryResponse(BaseModel):
    question: str
    answer: str
    sources: list
    num_sources: int
    detected_location: Optional[DetectedLocation] = None
    reranked: Optional[bool] = None
    utility_rates: Optional[Dict[str, Any]] = None


class IndexStationsRequest(BaseModel):
    zip_code: str
    limit: int = 50


class BulkIndexStateRequest(BaseModel):
    state: str  # 2-letter state code (e.g., "OH")
    batch_size: int = 100
    limit: Optional[int] = None  # Optional limit for testing


@router.post("/rag/query", response_model=RAGQueryResponse)
async def rag_query(
    request: RAGQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Perform a RAG query: retrieve relevant EV charging stations and generate a natural language response.
    
    Requires authentication. Checks query limit before processing.
    
    Location determination strategy:
    1. If zip_code is provided, stations will be fetched from NREL and indexed first.
    2. If zip_code is NOT provided, the system will attempt to extract location information 
       from the question using LLM (e.g., "Denver", "Colorado", "80202", "stations in CA").
    3. If location is detected:
       - Zip code: Fetches stations for that zip code
       - State: Fetches stations for that state (up to 200 stations)
       - City+State: Fetches stations for that state (up to 200 stations)
    4. If no location is found, the query uses existing indexed data.
    
    Example questions:
    - "Where can I charge my Tesla?" (uses existing indexed data)
    - "Find charging stations with DC fast charging in Denver" (detects "Denver")
    - "What stations are available in Colorado?" (detects "Colorado" state)
    - "Show me stations near 80202" (detects zip code "80202")
    - "What's the electricity cost in Denver?" (fetches utility rates)
    - "How much does electricity cost per kWh in 80202?" (fetches utility rates)
    """
    try:
        # Check query limit
        subscription = UserService.get_user_subscription(db, current_user.id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        if not subscription.can_make_query():
            remaining = subscription.get_remaining_queries()
            raise HTTPException(
                status_code=403,
                detail=f"Query limit reached. You have {remaining} queries remaining. Please upgrade to continue."
            )
        
        # Process query
        llm_mode = llm_service.settings.llm_mode
        rag_service = RAGService(llm_mode=llm_mode)
        
        result = await rag_service.query(
            question=request.question,
            zip_code=request.zip_code,
            top_k=request.top_k
        )
        
        # Increment query count
        UserService.increment_query_count(db, current_user.id)
        
        # Save query to history
        # Use detected zipcode if available, otherwise use provided zipcode
        zipcode_for_history = request.zip_code
        detected_location = result.get("detected_location")
        if detected_location and isinstance(detected_location, dict):
            detected_zip = detected_location.get("zip_code")
            if detected_zip:
                zipcode_for_history = detected_zip
        
        from app.models.query import Query
        try:
            query_record = Query(
                id=uuid.uuid4(),
                user_id=current_user.id,
                question=request.question,
                answer=result["answer"],
                zip_code=zipcode_for_history,
                sources_count=result["num_sources"],
                sources_data=result.get("sources", [])
            )
            db.add(query_record)
            db.commit()
        except Exception as db_error:
            error_msg = str(db_error)
            # Check if it's a missing table error
            if "does not exist" in error_msg and "queries" in error_msg:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Database table 'queries' does not exist. "
                        "Please run the migration script: migrations/002_create_saas_tables.sql "
                        "in your Supabase SQL Editor. "
                        "See migrations/README.md for instructions."
                    )
                )
            # Re-raise other database errors
            raise HTTPException(status_code=500, detail=f"Database error: {error_msg}")
        
        return RAGQueryResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/index-stations")
async def index_stations(request: IndexStationsRequest):
    """
    Fetch stations from NREL API and index them into the vector database.
    This is useful for pre-populating the database or refreshing data.
    """
    try:
        llm_mode = llm_service.settings.llm_mode
        rag_service = RAGService(llm_mode=llm_mode)
        
        result = await rag_service.fetch_and_index_stations(
            zip_code=request.zip_code,
            limit=request.limit
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/bulk-index-state")
async def bulk_index_state(request: BulkIndexStateRequest):
    """
    Bulk index all EV charging stations for a state.
    
    This endpoint downloads all stations for a target state and bulk embeds them.
    Perfect for local development where you can "over-index" without cost concerns.
    
    Example:
    - State: "OH" (Ohio)
    - This will fetch ALL stations in Ohio and index them
    
    Note: For large states, this may take a while. Use limit parameter for testing.
    """
    try:
        if len(request.state) != 2:
            raise HTTPException(
                status_code=400,
                detail="State code must be 2 letters (e.g., OH, CA, NY)"
            )
        
        llm_mode = llm_service.settings.llm_mode
        rag_service = RAGService(llm_mode=llm_mode)
        
        result = await rag_service.bulk_index_state(
            state=request.state.upper(),
            batch_size=request.batch_size,
            limit=request.limit
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

