from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any, AsyncGenerator
from app.services.rag_service import RAGService
from app.services.llm_service import LLMService
from app.services.user_service import UserService
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.query import Query
from app.database import get_db
import uuid
import json
import asyncio

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


class IndexStationsRequest(BaseModel):
    zip_code: str
    limit: int = 50


class BulkIndexStateRequest(BaseModel):
    state: str  # 2-letter state code (e.g., "OH")
    batch_size: int = 100
    limit: Optional[int] = None  # Optional limit for testing


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


def format_sse_event(event_type: str, data: Any) -> str:
    """Format data as Server-Sent Event."""
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {json_data}\n\n"


@router.post("/rag/query-stream")
async def rag_query_stream(
    request: RAGQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Perform a RAG query with Server-Sent Events (SSE) streaming.
    
    Streams progress updates and answer chunks in real-time for better UX.
    Uses SSE format: event: <type>\ndata: <json>\n\n
    
    Event types:
    - status: Progress updates (analyzing, searching, retrieving, preparing, generating, processing, finalizing)
    - tool: Tool call notifications (transportation_tool, utility_tool, etc.)
    - chunk: Answer text chunks as they're generated
    - done: Final response with sources
    - error: Error messages
    """
    async def generate_stream() -> AsyncGenerator[str, None]:
        final_result = None
        try:
            # Yield immediately to start HTTP response stream BEFORE any heavy work
            # This ensures FastAPI sends response headers immediately
            yield format_sse_event("status", {"stage": "analyzing", "message": "Starting query..."})
            await asyncio.sleep(0.01)  # Yield control to allow headers to be sent
            
            # Check query limit
            subscription = UserService.get_user_subscription(db, current_user.id)
            if not subscription:
                yield format_sse_event("error", {"message": "Subscription not found"})
                return
            
            if not subscription.can_make_query():
                remaining = subscription.get_remaining_queries()
                yield format_sse_event("error", {
                    "message": f"Query limit reached. You have {remaining} queries remaining. Please upgrade to continue."
                })
                return
            
            # Process query with streaming (status updates come from rag_service)
            llm_mode = llm_service.settings.llm_mode
            rag_service = RAGService(llm_mode=llm_mode)
            
            # Stream the query processing
            async for event_type, event_data in rag_service.query_stream(
                question=request.question,
                zip_code=request.zip_code,
                top_k=request.top_k
            ):
                # Capture final result for history saving
                if event_type == "done":
                    final_result = event_data
                # Format and yield SSE event immediately
                sse_event = format_sse_event(event_type, event_data)
                yield sse_event
                # Yield control to event loop to ensure FastAPI flushes immediately
                await asyncio.sleep(0.01)
            
            # Increment query count and save to history if we got a result
            if final_result:
                UserService.increment_query_count(db, current_user.id)
                
                # Save query to history
                zipcode_for_history = request.zip_code
                detected_location = final_result.get("detected_location")
                if detected_location and isinstance(detected_location, dict):
                    detected_zip = detected_location.get("zip_code")
                    if detected_zip:
                        zipcode_for_history = detected_zip
                
                try:
                    query_record = Query(
                        id=uuid.uuid4(),
                        user_id=current_user.id,
                        question=request.question,
                        answer=final_result.get("answer", ""),
                        zip_code=zipcode_for_history,
                        sources_count=final_result.get("num_sources", 0),
                        sources_data=final_result.get("sources", [])
                    )
                    db.add(query_record)
                    db.commit()
                except Exception as db_error:
                    error_msg = str(db_error)
                    # Log but don't fail the stream if history save fails
                    if "does not exist" in error_msg and "queries" in error_msg:
                        yield format_sse_event("error", {
                            "message": "Warning: Could not save query to history. Database table 'queries' does not exist."
                        })
            
        except HTTPException as e:
            yield format_sse_event("error", {"message": e.detail})
        except Exception as e:
            yield format_sse_event("error", {"message": str(e)})
    
    # NOTE: Traefik does NOT buffer by default - it streams responses.
    # If buffering is happening, check:
    # 1. Is Traefik Buffering middleware explicitly enabled? (Check Traefik config)
    # 2. Test direct backend access (bypass Traefik) to isolate the issue
    # 3. Check FastAPI/uvicorn logs to see when generator starts vs when headers are sent
    #
    # If Traefik Buffering middleware IS enabled, disable it with:
    #   labels:
    #     - "traefik.http.services.backend.buffering.maxRequestBodyBytes=0"
    #     - "traefik.http.services.backend.buffering.maxResponseBodyBytes=0"
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering in nginx (Traefik ignores this)
            "X-Content-Type-Options": "nosniff",
        }
    )

