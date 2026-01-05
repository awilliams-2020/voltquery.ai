from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from app.services.urdb_service import URDBService
from app.services.llm_service import LLMService
from app.middleware.auth import get_current_user
from app.models.user import User

router = APIRouter()
llm_service = LLMService()


class URDBFetchRequest(BaseModel):
    zip_codes: List[str]  # List of zip codes to fetch
    sector: Optional[str] = "residential"  # residential, commercial, or industrial
    fetch_batch_size: Optional[int] = 10  # Batch size for fetching
    index_batch_size: Optional[int] = 50  # Batch size for indexing
    delay_between_batches: Optional[float] = 1.0  # Delay to avoid rate limiting


class URDBFetchByStateRequest(BaseModel):
    state: str  # 2-letter state code
    sector: Optional[str] = "residential"
    fetch_batch_size: Optional[int] = 10
    index_batch_size: Optional[int] = 50
    delay_between_batches: Optional[float] = 1.0
    limit: Optional[int] = None  # Optional limit for testing


# Store background task status
background_task_status = {}


async def fetch_and_index_urdb_background(
    task_id: str,
    zip_codes: List[str],
    sector: str,
    fetch_batch_size: int,
    index_batch_size: int,
    delay_between_batches: float,
    llm_mode: str
):
    """
    Background task to fetch and index URDB data.
    """
    try:
        background_task_status[task_id] = {
            "status": "running",
            "progress": 0,
            "message": f"Starting URDB fetch for {len(zip_codes)} zip codes..."
        }
        
        urdb_service = URDBService(llm_mode=llm_mode)
        
        result = await urdb_service.fetch_and_index_urdb_by_zip_codes(
            zip_codes=zip_codes,
            sector=sector,
            fetch_batch_size=fetch_batch_size,
            index_batch_size=index_batch_size,
            delay_between_batches=delay_between_batches
        )
        
        background_task_status[task_id] = {
            "status": "completed",
            "progress": 100,
            "message": "URDB indexing completed successfully",
            "result": result
        }
    except Exception as e:
        background_task_status[task_id] = {
            "status": "failed",
            "progress": 0,
            "message": f"URDB indexing failed: {str(e)}",
            "error": str(e)
        }


@router.post("/urdb/fetch")
async def fetch_urdb(
    request: URDBFetchRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Start a background task to fetch and index URDB data for specified zip codes.
    
    Requires authentication.
    
    This is a long-running task that will:
    1. Fetch utility rate data from URDB for each zip code
    2. Index the data into the vector database with zip code metadata
    3. Make the data searchable via RAG queries
    
    Returns immediately with a task ID. Use /api/urdb/status/{task_id} to check progress.
    """
    import uuid
    
    # Validate zip codes
    invalid_zips = [z for z in request.zip_codes if not z.isdigit() or len(z) != 5]
    if invalid_zips:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid zip codes: {invalid_zips}. Zip codes must be 5-digit numbers."
        )
    
    # Validate sector
    valid_sectors = ["residential", "commercial", "industrial"]
    if request.sector and request.sector.lower() not in valid_sectors:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sector. Must be one of: {', '.join(valid_sectors)}"
        )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Initialize task status
    background_task_status[task_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Task queued, waiting to start...",
        "zip_codes_count": len(request.zip_codes)
    }
    
    # Start background task
    llm_mode = llm_service.settings.llm_mode
    background_tasks.add_task(
        fetch_and_index_urdb_background,
        task_id=task_id,
        zip_codes=request.zip_codes,
        sector=request.sector or "residential",
        fetch_batch_size=request.fetch_batch_size or 10,
        index_batch_size=request.index_batch_size or 50,
        delay_between_batches=request.delay_between_batches or 1.0,
        llm_mode=llm_mode
    )
    
    return {
        "task_id": task_id,
        "status": "queued",
        "message": f"URDB fetch task started for {len(request.zip_codes)} zip codes",
        "check_status_url": f"/api/urdb/status/{task_id}"
    }


@router.post("/urdb/fetch-by-state")
async def fetch_urdb_by_state(
    request: URDBFetchByStateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    Start a background task to fetch and index URDB data for all zip codes in a state.
    
    Requires authentication.
    
    This will:
    1. Generate a list of zip codes for the state (or use a sample if limit is set)
    2. Fetch URDB data for each zip code
    3. Index the data into the vector database
    
    Note: This can take a very long time for large states. Use limit parameter for testing.
    """
    import uuid
    
    # Validate state
    if len(request.state) != 2:
        raise HTTPException(
            status_code=400,
            detail="State code must be 2 letters (e.g., OH, CA, NY)"
        )
    
    # Generate zip codes for the state
    # For now, we'll use a simple approach: generate common zip code ranges
    # In production, you'd want to use a zip code database
    zip_codes = _generate_zip_codes_for_state(request.state.upper(), request.limit)
    
    if not zip_codes:
        raise HTTPException(
            status_code=400,
            detail=f"Could not generate zip codes for state {request.state}"
        )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Initialize task status
    background_task_status[task_id] = {
        "status": "queued",
        "progress": 0,
        "message": f"Task queued for state {request.state}, {len(zip_codes)} zip codes",
        "state": request.state.upper(),
        "zip_codes_count": len(zip_codes)
    }
    
    # Start background task
    llm_mode = llm_service.settings.llm_mode
    background_tasks.add_task(
        fetch_and_index_urdb_background,
        task_id=task_id,
        zip_codes=zip_codes,
        sector=request.sector or "residential",
        fetch_batch_size=request.fetch_batch_size or 10,
        index_batch_size=request.index_batch_size or 50,
        delay_between_batches=request.delay_between_batches or 1.0,
        llm_mode=llm_mode
    )
    
    return {
        "task_id": task_id,
        "status": "queued",
        "message": f"URDB fetch task started for state {request.state.upper()} ({len(zip_codes)} zip codes)",
        "check_status_url": f"/api/urdb/status/{task_id}"
    }


@router.get("/urdb/status/{task_id}")
async def get_urdb_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get the status of a URDB background task.
    
    Requires authentication.
    """
    if task_id not in background_task_status:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found"
        )
    
    return background_task_status[task_id]


def _generate_zip_codes_for_state(state: str, limit: Optional[int] = None) -> List[str]:
    """
    Generate a list of zip codes for a state.
    
    This is a simplified implementation. In production, you'd want to use
    a comprehensive zip code database or API.
    
    For now, we'll use common zip code ranges for major states.
    """
    # Common zip code ranges by state (first 3 digits)
    state_ranges = {
        "CA": list(range(900, 962)) + list(range(940, 962)),
        "NY": list(range(100, 150)) + list(range(120, 150)),
        "TX": list(range(750, 800)) + list(range(770, 800)),
        "FL": list(range(320, 350)) + list(range(330, 350)),
        "IL": list(range(600, 630)) + list(range(606, 630)),
        "PA": list(range(150, 200)) + list(range(190, 200)),
        "OH": list(range(430, 460)) + list(range(440, 460)),
        "GA": list(range(300, 320)) + list(range(303, 320)),
        "NC": list(range(270, 290)) + list(range(275, 290)),
        "MI": list(range(480, 500)) + list(range(481, 500)),
    }
    
    # If state not in ranges, generate a sample
    if state not in state_ranges:
        # Use a generic approach: generate zip codes starting with state-specific prefix
        # This is a fallback - in production use a proper zip code database
        prefixes = [str(i).zfill(3) for i in range(100, 1000)]
        zip_codes = [f"{prefix}00" for prefix in prefixes[:100]]  # Sample
    else:
        prefixes = [str(p).zfill(3) for p in state_ranges[state]]
        zip_codes = [f"{prefix}00" for prefix in prefixes]
    
    # Apply limit if specified
    if limit:
        zip_codes = zip_codes[:limit]
    
    return zip_codes

