from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.nrel_client import NRELClient

router = APIRouter()


class ZipCodeRequest(BaseModel):
    zip_code: str


@router.post("/fetch-stations")
async def fetch_stations(request: ZipCodeRequest):
    """
    Fetch EV charging stations for a given zip code using the NREL API.
    """
    try:
        nrel_client = NRELClient()
        stations = await nrel_client.get_stations_by_zip(request.zip_code)
        return {"zip_code": request.zip_code, "stations": stations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

