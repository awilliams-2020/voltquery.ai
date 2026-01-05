from fastapi import HTTPException, Depends, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.user_service import UserService
from typing import Optional
import httpx


async def verify_clerk_token(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Verify Clerk JWT token and return user.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        # Extract token from "Bearer <token>"
        token = authorization.replace("Bearer ", "")
        
        # Verify token with Clerk (you'll need to set CLERK_SECRET_KEY)
        import os
        clerk_secret_key = os.getenv("CLERK_SECRET_KEY")
        if not clerk_secret_key:
            raise HTTPException(status_code=500, detail="Clerk secret key not configured")
        
        # Verify token with Clerk API
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.clerk.com/v1/tokens/verify",
                headers={
                    "Authorization": f"Bearer {clerk_secret_key}",
                    "Content-Type": "application/json"
                },
                params={"token": token},
                timeout=10.0
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            token_data = response.json()
            clerk_id = token_data.get("sub") or token_data.get("user_id")
            email = token_data.get("email", "")
            
            if not clerk_id:
                raise HTTPException(status_code=401, detail="Invalid token format")
            
            # Get or create user
            user = UserService.get_or_create_user(db, clerk_id, email)
            return user
            
    except httpx.HTTPError:
        # Fallback: verify token locally using JWT
        from jose import jwt
        import os
        
        clerk_secret_key = os.getenv("CLERK_SECRET_KEY")
        if not clerk_secret_key:
            raise HTTPException(status_code=500, detail="Clerk secret key not configured")
        
        try:
            # Decode JWT token
            payload = jwt.decode(token, clerk_secret_key, algorithms=["RS256"])
            clerk_id = payload.get("sub")
            email = payload.get("email", "")
            
            if not clerk_id:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            user = UserService.get_or_create_user(db, clerk_id, email)
            return user
        except jwt.JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


# Simplified version that accepts Clerk user ID from frontend
async def get_current_user(
    x_clerk_user_id: Optional[str] = Header(None),
    x_clerk_email: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Get current user from Clerk headers (simpler approach).
    Frontend sends X-Clerk-User-Id and X-Clerk-Email headers.
    """
    if not x_clerk_user_id:
        raise HTTPException(status_code=401, detail="User ID missing")
    
    email = x_clerk_email or f"{x_clerk_user_id}@example.com"
    user = UserService.get_or_create_user(db, x_clerk_user_id, email)
    return user

