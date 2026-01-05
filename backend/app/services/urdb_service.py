from typing import List, Dict, Any, Optional
import httpx
import asyncio
from pydantic_settings import BaseSettings
from app.services.document_service import DocumentService
from app.services.vector_store_service import VectorStoreService
from app.services.nrel_client import NRELClient


class OpenEISettings(BaseSettings):
    """Settings for OpenEI API (separate from NREL API)."""
    openei_api_key: str
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class URDBService:
    """
    Service for fetching and indexing URDB (Utility Rate Database) data.
    URDB is a comprehensive database of utility rates from OpenEI.
    
    Note: OpenEI requires its own API key, separate from NREL API key.
    Get your API key at: https://apps.openei.org/services/api/signup/
    """
    
    # OpenEI URDB API endpoint
    URDB_BASE_URL = "https://api.openei.org/utility_rates"
    
    def __init__(self, llm_mode: str = "local"):
        self.nrel_client = NRELClient()  # For geocoding only
        self.document_service = DocumentService()
        self.vector_store_service = VectorStoreService(llm_mode=llm_mode)
        
        # Use OpenEI API key (separate from NREL)
        settings = OpenEISettings()
        self.api_key = settings.openei_api_key
        if not self.api_key or self.api_key == "your_openei_api_key_here":
            raise ValueError(
                "OPENEI_API_KEY must be set in environment variables. "
                "Get your API key at: https://apps.openei.org/services/api/signup/"
            )
    
    async def fetch_urdb_by_zip(
        self,
        zip_code: str,
        sector: str = "residential",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch URDB utility rates for a specific zip code.
        
        Args:
            zip_code: 5-digit US zip code
            sector: Sector type - "residential", "commercial", or "industrial"
            limit: Maximum number of results
            
        Returns:
            List of utility rate dictionaries
        """
        async with httpx.AsyncClient() as client:
            params = {
                "api_key": self.api_key,
                "version": "7",
                "format": "json",
                "sector": sector,
                "limit": limit
            }
            
            # Geocode zip code to get lat/long for URDB query
            try:
                latitude, longitude = await self.nrel_client._geocode_zip_code(zip_code)
                params["latitude"] = latitude
                params["longitude"] = longitude
            except Exception as e:
                # Fallback: try with zip code directly
                params["zipcode"] = zip_code
            
            try:
                response = await client.get(
                    self.URDB_BASE_URL,
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                
                # Extract items from response
                if isinstance(data, dict):
                    items = data.get("items", [])
                    if not items and "rates" in data:
                        items = data["rates"]
                    return items if isinstance(items, list) else []
                elif isinstance(data, list):
                    return data
                
                return []
            except Exception as e:
                print(f"Error fetching URDB data for zip {zip_code}: {str(e)}")
                return []
    
    async def fetch_urdb_bulk(
        self,
        zip_codes: List[str],
        sector: str = "residential",
        batch_size: int = 10,
        delay_between_batches: float = 1.0
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch URDB data for multiple zip codes in batches.
        
        Args:
            zip_codes: List of zip codes to fetch
            sector: Sector type
            batch_size: Number of zip codes to process per batch
            delay_between_batches: Delay in seconds between batches (to avoid rate limiting)
            
        Returns:
            Dictionary mapping zip codes to their utility rate data
        """
        results = {}
        total_batches = (len(zip_codes) + batch_size - 1) // batch_size
        
        for i in range(0, len(zip_codes), batch_size):
            batch = zip_codes[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            
            print(f"Processing URDB batch {batch_num}/{total_batches} ({len(batch)} zip codes)...")
            
            # Process batch concurrently
            tasks = [
                self.fetch_urdb_by_zip(zip_code, sector=sector)
                for zip_code in batch
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Store results
            for zip_code, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    print(f"Error fetching URDB for {zip_code}: {str(result)}")
                    results[zip_code] = []
                else:
                    results[zip_code] = result
            
            # Delay between batches to avoid rate limiting
            if i + batch_size < len(zip_codes):
                await asyncio.sleep(delay_between_batches)
        
        return results
    
    async def index_urdb_data(
        self,
        urdb_data: Dict[str, List[Dict[str, Any]]],
        batch_size: int = 50
    ) -> Dict[str, Any]:
        """
        Index URDB data into the vector database.
        
        Args:
            urdb_data: Dictionary mapping zip codes to utility rate data
            batch_size: Number of documents to index per batch
            
        Returns:
            Dictionary with indexing statistics
        """
        index = self.vector_store_service.get_index()
        indexed_count = 0
        skipped_count = 0
        
        all_documents = []
        
        # Convert URDB data to documents
        for zip_code, rates in urdb_data.items():
            if not rates:
                continue
            
            for rate in rates:
                # Convert each rate to a document
                documents = self.document_service.utility_rates_to_documents(
                    utility_rates=rate,
                    location=zip_code
                )
                all_documents.extend(documents)
        
        # Index documents in batches
        total_docs = len(all_documents)
        print(f"Indexing {total_docs} URDB documents...")
        
        for i in range(0, total_docs, batch_size):
            batch = all_documents[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_docs + batch_size - 1) // batch_size
            
            print(f"Indexing batch {batch_num}/{total_batches} ({len(batch)} documents)...")
            
            # Bulk insert documents for better performance
            try:
                # Bulk insert entire batch at once
                index.insert(batch)
                indexed_count += len(batch)
            except Exception as e:
                # If bulk insert fails, fall back to individual inserts for error handling
                print(f"  Warning: Bulk insert failed, falling back to individual inserts: {str(e)[:100]}")
                for doc in batch:
                    try:
                        index.insert(doc)
                        indexed_count += 1
                    except Exception as doc_error:
                        skipped_count += 1
                        if skipped_count <= 5:  # Only print first few errors
                            print(f"  Skipped document: {str(doc_error)[:100]}")
        
        return {
            "total_zip_codes": len(urdb_data),
            "total_documents": total_docs,
            "indexed": indexed_count,
            "skipped": skipped_count,
            "message": f"Successfully indexed {indexed_count} URDB documents"
        }
    
    async def fetch_and_index_urdb_by_zip_codes(
        self,
        zip_codes: List[str],
        sector: str = "residential",
        fetch_batch_size: int = 10,
        index_batch_size: int = 50,
        delay_between_batches: float = 1.0
    ) -> Dict[str, Any]:
        """
        Fetch and index URDB data for a list of zip codes.
        
        Args:
            zip_codes: List of zip codes to process
            sector: Sector type
            fetch_batch_size: Batch size for fetching
            index_batch_size: Batch size for indexing
            delay_between_batches: Delay between fetch batches
            
        Returns:
            Dictionary with results
        """
        print(f"Starting URDB fetch and index for {len(zip_codes)} zip codes...")
        
        # Fetch URDB data
        urdb_data = await self.fetch_urdb_bulk(
            zip_codes=zip_codes,
            sector=sector,
            batch_size=fetch_batch_size,
            delay_between_batches=delay_between_batches
        )
        
        # Index the data
        indexing_results = await self.index_urdb_data(
            urdb_data=urdb_data,
            batch_size=index_batch_size
        )
        
        return {
            "fetch_results": {
                "zip_codes_requested": len(zip_codes),
                "zip_codes_with_data": len([z for z, d in urdb_data.items() if d]),
                "total_rates_fetched": sum(len(rates) for rates in urdb_data.values())
            },
            "indexing_results": indexing_results
        }

