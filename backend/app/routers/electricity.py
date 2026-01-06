from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.services.nrel_client import NRELClient
from app.middleware.auth import get_current_user
from app.models.user import User

router = APIRouter()

# Constants
VALID_SECTORS = ["residential", "commercial", "industrial"]


class UtilityRatesRequest(BaseModel):
    location: str  # Can be zip code, address, or lat/long
    sector: Optional[str] = "residential"  # residential, commercial, or industrial


class ZipCodeUtilityRatesRequest(BaseModel):
    zip_code: str
    sector: Optional[str] = "residential"


@router.post("/utility-rates")
async def get_utility_rates(
    request: UtilityRatesRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Get utility rates (electricity costs) for a specific location.
    
    Requires authentication.
    
    Args:
        location: Location identifier (zip code, address, or lat/long)
                 Examples: "80202", "Denver, CO", "39.7392,-104.9903"
        sector: Sector type - "residential", "commercial", or "industrial"
               (default: "residential")
    
    Returns:
        Dictionary containing utility rate information including:
        - utility_name: Name of the utility company
        - residential_rate: Average residential rate ($/kWh)
        - commercial_rate: Average commercial rate ($/kWh)
        - industrial_rate: Average industrial rate ($/kWh)
        - location: Location information
        - eiaid: EIA utility ID
    
    Note: This API may return data from 2012 and may not be updated.
    Documentation: https://developer.nrel.gov/docs/electricity/utility-rates-v3/
    """
    try:
        # Validate sector
        if request.sector and request.sector.lower() not in VALID_SECTORS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sector. Must be one of: {', '.join(VALID_SECTORS)}"
            )
        
        nrel_client = NRELClient()
        rates = await nrel_client.get_utility_rates(
            location=request.location,
            sector=request.sector or "residential"
        )
        
        return {
            "location": request.location,
            "sector": request.sector or "residential",
            "rates": rates
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/utility-rates/zip")
async def get_utility_rates_by_zip(
    request: ZipCodeUtilityRatesRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Get utility rates (electricity costs) for a zip code.
    
    Requires authentication.
    
    Args:
        zip_code: 5-digit US zip code
        sector: Sector type - "residential", "commercial", or "industrial"
               (default: "residential")
    
    Returns:
        Dictionary containing utility rate information
    """
    try:
        # Validate sector
        if request.sector and request.sector.lower() not in VALID_SECTORS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sector. Must be one of: {', '.join(VALID_SECTORS)}"
            )
        
        # Validate zip code format
        if not request.zip_code.isdigit() or len(request.zip_code) != 5:
            raise HTTPException(
                status_code=400,
                detail="Zip code must be a 5-digit number"
            )
        
        nrel_client = NRELClient()
        rates = await nrel_client.get_utility_rates_by_zip(
            zip_code=request.zip_code,
            sector=request.sector or "residential"
        )
        
        return {
            "zip_code": request.zip_code,
            "sector": request.sector or "residential",
            "rates": rates
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

