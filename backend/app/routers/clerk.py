from fastapi import APIRouter, HTTPException, Request, Depends, Response
from sqlalchemy.orm import Session
import os
import json
from app.database import get_db
from app.services.user_service import UserService
from app.services.logger_service import get_logger

logger = get_logger("clerk_router")

router = APIRouter()


@router.get("/clerk/webhook")
async def clerk_webhook_get():
    """GET endpoint for Clerk webhook verification."""
    webhook_secret = os.getenv("CLERK_WEBHOOK_SECRET")
    return {
        "status": "ok",
        "message": "Webhook endpoint is accessible",
        "webhook_secret_configured": bool(webhook_secret)
    }


def verify_clerk_webhook(payload: bytes, headers: dict) -> dict:
    """
    Verify Clerk webhook signature using svix.
    
    Args:
        payload: Raw request body bytes
        headers: Dictionary with svix-signature, svix-id, and svix-timestamp
        
    Returns:
        Parsed JSON event data as dict
        
    Raises:
        HTTPException: If verification fails or secret is missing
    """
    try:
        import svix
    except ImportError:
        logger.log_error(
            "svix_not_installed",
            "svix library not installed. Install it with: pip install svix"
        )
        raise HTTPException(
            status_code=500,
            detail="svix library not installed"
        )
    
    webhook_secret = os.getenv("CLERK_WEBHOOK_SECRET")
    if not webhook_secret:
        logger.log_error(
            "clerk_webhook_secret_missing",
            "CLERK_WEBHOOK_SECRET environment variable not set"
        )
        raise HTTPException(
            status_code=500,
            detail="CLERK_WEBHOOK_SECRET environment variable not set"
        )
    
    try:
        wh = svix.Webhook(webhook_secret)
        verified_payload = wh.verify(payload, headers)
        
        # Parse the verified payload
        if isinstance(verified_payload, bytes):
            parsed = json.loads(verified_payload.decode("utf-8"))
        elif isinstance(verified_payload, str):
            parsed = json.loads(verified_payload)
        elif isinstance(verified_payload, dict):
            parsed = verified_payload
        else:
            parsed = json.loads(str(verified_payload))
        
        if not isinstance(parsed, dict):
            raise ValueError(f"Parsed payload is not a dict, got {type(parsed)}")
        
        return parsed
            
    except svix.WebhookVerificationError as e:
        logger.log_error(
            "clerk_webhook_verification_failed",
            f"Webhook verification failed: {str(e)}",
            context={"error_type": type(e).__name__}
        )
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {str(e)}")
    except json.JSONDecodeError as e:
        logger.log_error(
            "clerk_webhook_json_decode_error",
            f"Invalid JSON payload: {str(e)}",
            context={"payload_preview": str(payload[:200]) if len(payload) > 200 else str(payload)}
        )
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {str(e)}")
    except Exception as e:
        logger.log_error(
            "clerk_webhook_verification_unexpected_error",
            f"Unexpected error during webhook verification: {str(e)}",
            context={"error_type": type(e).__name__}
        )
        raise HTTPException(status_code=500, detail=f"Webhook verification error: {str(e)}")


@router.post("/clerk/webhook")
async def clerk_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Clerk webhook events.
    
    Processes user.deleted events and deletes the corresponding user
    from the database along with all associated data.
    """
    try:
        payload = await request.body()
    except Exception as e:
        logger.log_error(
            "clerk_webhook_payload_read_error",
            f"Failed to read request body: {str(e)}",
            context={"error_type": type(e).__name__}
        )
        raise HTTPException(status_code=400, detail=f"Failed to read request body: {str(e)}")
    
    # Extract svix headers
    svix_signature = request.headers.get("svix-signature")
    svix_id = request.headers.get("svix-id")
    svix_timestamp = request.headers.get("svix-timestamp")
    
    if not svix_signature:
        logger.log_error(
            "clerk_webhook_missing_signature",
            "Clerk webhook request missing signature header",
            context={"available_headers": list(request.headers.keys())}
        )
        raise HTTPException(status_code=400, detail="Missing webhook signature")
    
    # Build headers dict for svix.verify()
    svix_headers = {}
    if svix_signature:
        svix_headers["svix-signature"] = svix_signature
    if svix_id:
        svix_headers["svix-id"] = svix_id
    if svix_timestamp:
        svix_headers["svix-timestamp"] = svix_timestamp
    
    # Verify webhook signature
    try:
        event_data = verify_clerk_webhook(payload, svix_headers)
        if not isinstance(event_data, dict):
            raise ValueError(f"verify_clerk_webhook returned non-dict type: {type(event_data)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.log_error(
            "clerk_webhook_verification_error",
            f"Failed to verify Clerk webhook: {str(e)}",
            context={
                "error_type": type(e).__name__,
                "svix_id": svix_id
            }
        )
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {str(e)}")
    
    # Extract event information
    event_type = event_data.get("type")
    user_data = event_data.get("data", {})
    clerk_id = user_data.get("id") if isinstance(user_data, dict) else None
    
    logger.log_query(
        question="clerk_webhook_event_received",
        user_id=clerk_id or "unknown",
        success=True,
        zip_code=None
    )
    
    # Handle event types
    try:
        if event_type == "user.deleted":
            if not clerk_id:
                logger.log_error(
                    "clerk_webhook_missing_user_id",
                    "user.deleted event missing user ID",
                    context={
                        "event_type": event_type,
                        "event_data_keys": list(event_data.keys())
                    }
                )
                return Response(
                    content=json.dumps({"status": "error", "message": "Missing user ID in event"}),
                    status_code=200,
                    media_type="application/json"
                )
            
            # Delete user from database
            deleted = UserService.delete_user_by_clerk_id(db, clerk_id)
            
            if deleted:
                logger.log_query(
                    question="user_deleted_via_clerk_webhook",
                    user_id=clerk_id,
                    success=True,
                    zip_code=None
                )
                return Response(
                    content=json.dumps({
                        "status": "success",
                        "message": f"User {clerk_id} deleted successfully",
                        "clerk_id": clerk_id
                    }),
                    status_code=200,
                    media_type="application/json"
                )
            else:
                logger.log_error(
                    "clerk_webhook_user_not_found",
                    f"User with clerk_id {clerk_id} not found in database",
                    context={"clerk_id": clerk_id}
                )
                # Return success to prevent Clerk from retrying
                return Response(
                    content=json.dumps({
                        "status": "success",
                        "message": f"User {clerk_id} not found in database",
                        "clerk_id": clerk_id
                    }),
                    status_code=200,
                    media_type="application/json"
                )
        
        else:
            # Log unhandled event types but don't fail
            logger.log_query(
                question=f"clerk_webhook_unhandled_event_{event_type}",
                user_id=clerk_id or "unknown",
                success=True,
                zip_code=None
            )
            return Response(
                content=json.dumps({
                    "status": "success",
                    "message": f"Unhandled event type: {event_type}",
                    "event_type": event_type
                }),
                status_code=200,
                media_type="application/json"
            )
    
    except Exception as e:
        logger.log_error(
            "clerk_webhook_processing_error",
            f"Error processing Clerk webhook: {str(e)}",
            context={
                "event_type": event_type,
                "clerk_id": clerk_id,
                "error_type": type(e).__name__
            }
        )
        # Return 200 OK with error status to prevent Clerk from retrying
        return Response(
            content=json.dumps({
                "status": "error",
                "message": str(e),
                "event_type": event_type
            }),
            status_code=200,
            media_type="application/json"
        )
