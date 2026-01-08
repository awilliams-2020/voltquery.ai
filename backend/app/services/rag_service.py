from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple
from datetime import timedelta
import json
import re
from llama_index.core import Document
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.response_synthesizers.type import ResponseMode
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
from app.services.nrel_client import NRELClient
from app.services.bcl_client import BCLClient
from app.services.document_service import DocumentService
from app.services.vector_store_service import VectorStoreService
from app.services.llm_service import LLMService
from app.services.location_service import LocationService
from app.services.validators import validate_query_inputs
from app.services.logger_service import get_logger
from app.services.reopt_service import REoptService
from app.services.rag_settings import RAGSettings
from app.services.freshness_checker import FreshnessChecker
from app.services.query_refiner import QueryRefiner
from app.services.retry_service import get_retry_service, RetryConfig
from app.services.cache_service import get_cache_service
import time
import asyncio
import httpx
import hashlib


# RAGService now uses RAGOrchestrator from src.orchestrator for tool management
from src.orchestrator import RAGOrchestrator


class RAGService:
    """
    RAG (Retrieval-Augmented Generation) service that:
    1. Fetches stations from NREL API
    2. Converts them to Documents and embeds into Vector DB
    3. Retrieves relevant context based on user query
    4. Generates natural language response using LLM
    """
    
    def __init__(self, llm_mode: str = "local"):
        self.nrel_client = NRELClient()
        self.bcl_client = BCLClient()
        self.document_service = DocumentService()
        self.vector_store_service = VectorStoreService(llm_mode=llm_mode)
        self.llm_service = LLMService()
        self.location_service = LocationService()
        self.reopt_service = REoptService()
        self.logger = get_logger("rag_service")
        self.settings = RAGSettings()
        
        # Initialize new services
        self.freshness_checker = FreshnessChecker(
            vector_store_service=self.vector_store_service,
            settings=self.settings
        )
        self.query_refiner = QueryRefiner()
        self.retry_service = get_retry_service()
        self.cache_service = get_cache_service()
        
        # Retry configs for different operations
        self.api_retry_config = RetryConfig(
            max_attempts=3,
            initial_delay=1.0,
            max_delay=10.0,
            exponential_base=2.0
        )
    
    def _bulk_insert_documents(self, index, documents: List) -> Tuple[int, int]:
        """
        Bulk insert documents into VectorStoreIndex using the proper LlamaIndex API.
        
        According to LlamaIndex documentation:
        - Documents should be converted to nodes using SimpleNodeParser.get_nodes_from_documents()
        - Bulk inserts should use insert_nodes() method, not insert() with a list
        - insert() is for individual documents, insert_nodes() is for bulk operations
        
        Args:
            index: VectorStoreIndex instance
            documents: List of Document objects
            
        Returns:
            Tuple of (indexed_count, failed_count)
        """
        indexed_count = 0
        failed_count = 0
        
        if not documents or not isinstance(documents, list):
            return 0, 0
        
        # Check if documents is nested (list of lists) and flatten
        if documents and isinstance(documents[0], list):
            documents = [doc for sublist in documents for doc in sublist]
        
        # Validate all items are Document objects
        if not all(isinstance(doc, Document) for doc in documents):
            self.logger.log_error(
                error_type="ValidationError",
                error_message="Invalid document types in bulk insert",
                context={"expected": "Document"}
            )
            return 0, 0
        
        try:
            # Step 1: Convert documents to nodes (required for bulk insert)
            # This is the documented approach per LlamaIndex API
            from llama_index.core.node_parser import SimpleNodeParser
            node_parser = SimpleNodeParser.from_defaults()
            nodes = node_parser.get_nodes_from_documents(documents)
            
            if not nodes:
                self.logger.log_error(
                    error_type="NodeGenerationError",
                    error_message="No nodes generated from documents",
                    context={"doc_count": len(documents)}
                )
                return 0, 0
            
            # Step 2: Use insert_nodes() for bulk insertion (the proper API method)
            # insert_nodes() is designed for bulk operations with nodes
            if hasattr(index, 'insert_nodes'):
                index.insert_nodes(nodes)
                indexed_count = len(nodes)
            else:
                # Fallback: if insert_nodes doesn't exist, try insert with nodes
                # Some versions might support insert() with nodes
                try:
                    index.insert(nodes)
                    indexed_count = len(nodes)
                except Exception:
                    # Final fallback: individual inserts
                    for node in nodes:
                        try:
                            index.insert(node)
                            indexed_count += 1
                        except Exception:
                            failed_count += 1
                            
        except Exception as e:
            error_msg = str(e)
            self.logger.log_error(
                error_type="BulkInsertError",
                error_message=f"Bulk insert failed: {error_msg[:150]}",
                context={"doc_count": len(documents)}
            )
            # Fallback to individual document inserts if node conversion fails
            for doc in documents:
                try:
                    index.insert(doc)
                    indexed_count += 1
                except Exception as doc_error:
                    failed_count += 1
                    if failed_count <= 3:
                        self.logger.log_error(
                            error_type="DocumentInsertError",
                            error_message=f"Failed to insert document: {str(doc_error)[:100]}",
                            context={"doc_id": getattr(doc, 'id_', 'N/A')}
                        )
        
        return indexed_count, failed_count
    
    async def fetch_and_index_stations(
        self, 
        zip_code: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Fetch stations from NREL API and index them into the vector store.
        
        Args:
            zip_code: 5-digit US zip code
            limit: Maximum number of stations to fetch
            
        Returns:
            Dictionary with fetch and indexing results
        """
        # Fetch stations from NREL
        self.logger.log_api_call(
            service="nrel",
            endpoint="get_stations_by_zip",
            method="GET",
            success=True
        )
        stations = await self.nrel_client.get_stations_by_zip(
            zip_code=zip_code,
            limit=limit
        )
        
        if not stations:
            return {
                "zip_code": zip_code,
                "stations_fetched": 0,
                "stations_indexed": 0,
                "message": "No stations found for this zip code"
            }
        
        # Add queried_zip to each station so we can filter by it later
        # (stations returned may have different zip codes than the one queried)
        for station in stations:
            station["queried_zip"] = zip_code
        
        # Convert to Documents
        documents = self.document_service.stations_to_documents(stations)
        
        # Get vector store index
        index = self.vector_store_service.get_index()
        
        # Bulk insert documents (much faster than individual inserts)
        # This allows the embedding model to process multiple texts in batch
        indexed_count = 0
        failed_count = 0
        
        # Validate documents structure
        if not documents or not isinstance(documents, list):
            self.logger.log_error(
                error_type="ValidationError",
                error_message="Invalid documents structure",
                context={"type": str(type(documents)), "zip_code": zip_code}
            )
            return {
                "zip_code": zip_code,
                "stations_fetched": len(stations),
                "stations_indexed": 0,
                "failed": 0,
                "message": "Invalid documents structure"
            }
        
        # Use helper method for bulk insert
        indexed_count, failed_count = self._bulk_insert_documents(index, documents)
        if failed_count > 0:
            self.logger.log_error(
                error_type="IndexingError",
                error_message=f"Some stations failed to index",
                context={"zip_code": zip_code, "indexed": indexed_count, "failed": failed_count}
            )
        
        return {
            "zip_code": zip_code,
            "stations_fetched": len(stations),
            "stations_indexed": indexed_count,
            "failed": failed_count,
            "message": f"Successfully indexed {indexed_count} stations" + (f" ({failed_count} failed)" if failed_count > 0 else "")
        }
    
    async def fetch_and_index_stations_by_state(
        self,
        state: str,
        limit: int = 200
    ) -> Dict[str, Any]:
        """
        Fetch stations by state and index them into the vector store.
        Useful when only state information is available.
        
        Args:
            state: 2-letter US state code (e.g., "OH")
            limit: Maximum number of stations to fetch (default: 200)
            
        Returns:
            Dictionary with fetch and indexing results
        """
        # Fetch stations from NREL
        self.logger.log_api_call(
            service="nrel",
            endpoint="get_stations_by_state",
            method="GET",
            success=True
        )
        stations = await self.nrel_client.get_stations_by_state(
            state=state,
            limit=limit
        )
        
        if not stations:
            return {
                "state": state,
                "stations_fetched": 0,
                "stations_indexed": 0,
                "message": f"No stations found for state {state}"
            }
        
        # Convert to Documents
        documents = self.document_service.stations_to_documents(stations)
        
        # Get vector store index
        index = self.vector_store_service.get_index()
        
        # Bulk insert documents for better performance
        indexed_count = 0
        
        # Validate documents structure
        if not documents or not isinstance(documents, list):
            self.logger.log_error(
                error_type="ValidationError",
                error_message="Invalid documents structure",
                context={"type": str(type(documents))}
            )
            return {
                "state": state,
                "stations_fetched": len(stations),
                "stations_indexed": 0,
                "message": "Invalid documents structure"
            }
        
        # Check if documents is nested (list of lists)
        if documents and isinstance(documents[0], list):
            self.logger.log_error(
                error_type="DataStructureError",
                error_message="Nested list detected, flattening",
                context={"state": state}
            )
            documents = [doc for sublist in documents for doc in sublist]
        
        # Use helper method for bulk insert
        indexed_count, _ = self._bulk_insert_documents(index, documents)
        
        return {
            "state": state,
            "stations_fetched": len(stations),
            "stations_indexed": indexed_count,
            "message": f"Successfully indexed {indexed_count} stations for {state}"
        }
    
    async def _index_utility_rates(
        self,
        utility_rates: Dict[str, Any],
        location: str
    ) -> None:
        """
        Index utility rates into the vector database.
        
        Args:
            utility_rates: Utility rates dictionary from NREL API
            location: Location string (zip code, city, etc.)
        """
        try:
            # Debug: Print what we're trying to index
            # Convert utility rates to documents
            documents = self.document_service.utility_rates_to_documents(
                utility_rates=utility_rates,
                location=location
            )
            
            # Get vector store index
            index = self.vector_store_service.get_index()
            
            # Use helper method for bulk insert
            indexed_count, failed_count = self._bulk_insert_documents(index, documents)
            if failed_count > 0:
                self.logger.log_error(
                    error_type="IndexingError",
                    error_message=f"Some utility rates failed to index",
                    context={"indexed": indexed_count, "failed": failed_count, "location": location}
                )
                
        except Exception as e:
            self.logger.log_error(
                error_type="UtilityRatesIndexingError",
                error_message=f"Error indexing utility rates: {str(e)}",
                context={"location": location}
            )
    
    def _is_building_efficiency_question(self, question: str) -> bool:
        """
        Detect if the question is about building efficiency, codes, or lowering bills.
        
        Args:
            question: User's question
            
        Returns:
            True if question appears to be about building efficiency/codes
        """
        question_lower = question.lower()
        
        # Keywords that indicate building efficiency questions
        building_keywords = [
            "lower bill", "reduce bill", "lower electricity", "reduce electricity",
            "building code", "energy code", "iecc", "ashrae", "building standard",
            "efficiency requirement", "code compliance", "building performance",
            "energy efficiency standard", "building energy code", "building codes",
            "energy standards", "building efficiency", "energy efficiency measure",
            "energy efficiency", "efficiency measures", "efficiency standards",
            "energy retrofit", "improve efficiency", "reduce consumption",
            "how to lower", "how to reduce", "ways to lower", "ways to reduce",
            "lower my", "reduce my", "cut my", "save on", "save money"
        ]
        
        return any(keyword in question_lower for keyword in building_keywords)
    
    async def fetch_and_index_bcl_measures(
        self,
        state: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Fetch BCL (Building Component Library) measures and index them into the vector store.
        
        Args:
            state: Optional state code (e.g., "IL", "CA")
            query: Optional search query
            limit: Maximum number of measures to fetch
            
        Returns:
            Dictionary with fetch and indexing results
        """
        try:
            # Extract key terms from query for better search
            search_query = None
            if query:
                # Extract relevant keywords from query
                query_lower = query.lower()
                keywords = []
                if any(term in query_lower for term in ["code", "standard", "compliance", "iecc", "ashrae"]):
                    keywords.append("energy code")
                if any(term in query_lower for term in ["efficiency", "retrofit", "improve", "reduce", "lower"]):
                    keywords.append("energy efficiency")
                if any(term in query_lower for term in ["building", "residential", "home"]):
                    keywords.append("residential")
                
                # Use first keyword or original query
                search_query = keywords[0] if keywords else query[:50]  # Limit query length
            
            # Search for building code measures
            print(f"[RAGService] bcl_api_call | type=building_codes | query='{search_query[:50] if search_query else 'N/A'}' | state={state}")
            building_codes = await self.bcl_client.search_building_codes(
                query=search_query,
                limit=limit
            )
            
            # Search for energy efficiency measures
            print(f"[RAGService] bcl_api_call | type=efficiency_measures | query='{search_query[:50] if search_query else 'N/A'}' | state={state}")
            efficiency_measures = await self.bcl_client.search_energy_efficiency_measures(
                query=search_query,
                limit=limit
            )
            
            # Combine results
            all_measures = []
            if building_codes:
                all_measures.extend(building_codes)
            if efficiency_measures:
                all_measures.extend(efficiency_measures)
            
            # Remove duplicates by UUID
            seen_uuids = set()
            unique_measures = []
            for measure in all_measures:
                uuid = measure.get("uuid") or measure.get("version_id")
                if uuid and uuid not in seen_uuids:
                    seen_uuids.add(uuid)
                    unique_measures.append(measure)
            
            if not unique_measures:
                return {
                    "state": state,
                    "query": query,
                    "measures_fetched": 0,
                    "measures_indexed": 0,
                    "message": f"No BCL measures found for state {state or 'unknown'}"
                }
            
            # Convert to documents
            documents = self.document_service.bcl_measures_to_documents(
                measures=unique_measures,
                state=state
            )
            
            if not documents:
                return {
                    "state": state,
                    "query": query,
                    "measures_fetched": len(unique_measures),
                    "measures_indexed": 0,
                    "message": "No documents created from BCL measures"
                }
            
            # Get vector store index
            index = self.vector_store_service.get_index()
            
            # Bulk insert documents
            indexed_count = 0
            failed_count = 0
            
            # Validate documents structure
            if not documents or not isinstance(documents, list):
                print(f"[RAGService] ERROR bcl_indexing | invalid_documents | type={type(documents)}")
                return {
                    "state": state,
                    "query": query,
                    "measures_fetched": len(unique_measures) if unique_measures else 0,
                    "measures_indexed": 0,
                    "failed": 0,
                    "message": "Invalid documents structure"
                }
            
            # Check if documents is nested (list of lists)
            if documents and isinstance(documents[0], list):
                print(f"[RAGService] ERROR bcl_indexing | nested_list_detected | flattening")
                documents = [doc for sublist in documents for doc in sublist]
            
            # Use helper method for bulk insert
            indexed_count, failed_count = self._bulk_insert_documents(index, documents)
            if failed_count > 0:
                print(f"[RAGService] bcl_indexing | state={state} | indexed={indexed_count} | failed={failed_count}")
                
            
            return {
                "state": state,
                "query": query,
                "measures_fetched": len(unique_measures),
                "measures_indexed": indexed_count,
                "failed": failed_count,
                "message": f"Successfully indexed {indexed_count} BCL measures" + (f" ({failed_count} failed)" if failed_count > 0 else "")
            }
        except Exception as e:
            print(f"Error fetching and indexing BCL measures: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "state": state,
                "query": query,
                "measures_fetched": 0,
                "measures_indexed": 0,
                "error": str(e),
                "message": f"Failed to fetch and index BCL measures: {str(e)}"
            }
    
    async def _fetch_and_index_utility_rates_if_needed(
        self,
        question: str,
        detected_location_info: Optional[Dict[str, Any]],
        location_to_use: Optional[str]
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Fetch and index utility rates if the question requires it.
        
        Best practice: Checks vector store first, only fetches from API if data doesn't exist.
        
        Args:
            question: User's question
            detected_location_info: Location info extracted from question
            location_to_use: Zip code or location string to use
            
        Returns:
            Tuple of (indexed_zip_code, utility_rates_info)
        """
        indexed_zip_code = None  # Track which zip code was used for indexing
        
        try:
            is_electricity_cost_question = self._is_electricity_cost_question(question)
        except Exception as e:
            print(f"[RAGService] ERROR _is_electricity_cost_question: {str(e)}")
            import traceback
            traceback.print_exc()
            is_electricity_cost_question = False
        
        # Also check if question mentions time-of-use rates or charging costs (needs utility tool)
        question_lower = question.lower()
        requires_utility_for_rates = any(keyword in question_lower for keyword in [
            "charging at", "time-of-use", "off-peak", "peak rate", "charging cost", "savings", "compare",
            "lower bill", "reduce bill", "cut bill", "save on"
        ]) and not is_electricity_cost_question
        
        if is_electricity_cost_question or requires_utility_for_rates:
            city = detected_location_info.get("city") if detected_location_info else None
            state = detected_location_info.get("state") if detected_location_info else None
            zip_code = detected_location_info.get("zip_code") if detected_location_info else None
            print(f"[RAGService] utility_rates_check | question_type={'cost' if is_electricity_cost_question else 'rates'} | location={city or state or zip_code or 'unknown'}")
        
        utility_rates_info = None
        
        # Extract zip code from question if not already detected (for fallback)
        zip_from_question = None
        zip_match = re.search(r'\b\d{5}\b', question)
        if zip_match:
            zip_from_question = zip_match.group(0)
        
        if is_electricity_cost_question or requires_utility_for_rates:
            # Try to get utility rates for the location and index them
            try:
                # Prioritize zip code for more accurate geocoding
                location_for_rates = None
                
                # First priority: zip code from detected location info
                if detected_location_info:
                    location_for_rates = detected_location_info.get("zip_code")
                    if location_for_rates:
                        # Check vector store freshness (best practice: avoid unnecessary API calls)
                        is_fresh, _ = await self.freshness_checker.check_utility_rates_freshness(location_for_rates)
                        if is_fresh:
                            indexed_zip_code = location_for_rates
                            return indexed_zip_code, None
                
                # Second priority: zip code from location_to_use (if it's a zip code)
                if not location_for_rates and location_to_use:
                    # Check if location_to_use is a zip code (5 digits)
                    if location_to_use.isdigit() and len(location_to_use) == 5:
                        location_for_rates = location_to_use
                        # Check vector store freshness (best practice: avoid unnecessary API calls)
                        is_fresh, _ = await self.freshness_checker.check_utility_rates_freshness(location_for_rates)
                        if is_fresh:
                            indexed_zip_code = location_for_rates
                            return indexed_zip_code, None
                
                # Third priority: zip code extracted directly from question (if not already processed)
                if not location_for_rates and zip_from_question:
                    # Check if this zip wasn't already checked via detected_location_info
                    if not (detected_location_info and detected_location_info.get("zip_code") == zip_from_question):
                        location_for_rates = zip_from_question
                        # Check vector store freshness (best practice: avoid unnecessary API calls)
                        is_fresh, _ = await self.freshness_checker.check_utility_rates_freshness(location_for_rates)
                        if is_fresh:
                            indexed_zip_code = location_for_rates
                            return indexed_zip_code, None
                
                # Fourth priority: Try to geocode city/state to get zip code
                if not location_for_rates and detected_location_info:
                    city = detected_location_info.get("city")
                    state = detected_location_info.get("state")
                    if city and state:
                        # Try to lookup zip code from city/state first
                        zip_from_city_state = await self.nrel_client._lookup_zip_from_city_state(city, state)
                        if zip_from_city_state:
                            location_for_rates = zip_from_city_state
                            # Check vector store freshness (best practice: avoid unnecessary API calls)
                            is_fresh, _ = await self.freshness_checker.check_utility_rates_freshness(zip_from_city_state)
                            if is_fresh:
                                indexed_zip_code = zip_from_city_state
                                return indexed_zip_code, None
                        else:
                            # Try to geocode city/state to get coordinates, then use those for utility rates
                            try:
                                # Use NREL client's geocoding to get lat/long
                                lat, lon = await self.nrel_client._geocode_location(f"{city}, {state}")
                                
                                # Try to reverse geocode to get zip code for filtering
                                zip_from_coords = None
                                try:
                                    # Use reverse geocoding to get zip code
                                    async with httpx.AsyncClient(follow_redirects=True) as client:
                                        reverse_params = {
                                            "lat": lat,
                                            "lon": lon,
                                            "format": "json",
                                            "addressdetails": 1,
                                            "limit": 1
                                        }
                                        reverse_response = await client.get(
                                            "https://nominatim.openstreetmap.org/reverse",
                                            params=reverse_params,
                                            headers={"User-Agent": "VoltQuery.ai/1.0"},
                                            timeout=10.0
                                        )
                                        if reverse_response.status_code == 200:
                                            reverse_data = reverse_response.json()
                                            address = reverse_data.get("address", {})
                                            zip_from_coords = address.get("postcode")
                                            if zip_from_coords and len(zip_from_coords) >= 5:
                                                zip_from_coords = zip_from_coords[:5]  # Take first 5 digits
                                                # Check vector store freshness (best practice: avoid unnecessary API calls)
                                                is_fresh, _ = await self.freshness_checker.check_utility_rates_freshness(zip_from_coords)
                                                if is_fresh:
                                                    indexed_zip_code = zip_from_coords
                                                    return indexed_zip_code, None
                                except Exception as reverse_error:
                                    print(f"[RAGService] ERROR reverse_geocode: {str(reverse_error)}")
                                
                                # Use coordinates directly for utility rates API (only if not in vector store)
                                print(f"[RAGService] utility_rates_fetching | lat={lat:.4f} lon={lon:.4f} | source=api")
                                utility_rates_info = await self.nrel_client.get_utility_rates_by_coordinates(
                                    latitude=lat,
                                    longitude=lon,
                                    sector="residential"
                                )
                                # Index utility rates if we got them
                                if utility_rates_info:
                                    if isinstance(utility_rates_info, dict) and utility_rates_info:
                                        if "errors" not in utility_rates_info and "error" not in utility_rates_info:
                                            # Use zip code if available, otherwise use city/state
                                            index_location = zip_from_coords if zip_from_coords else f"{city}, {state}"
                                            await self._index_utility_rates(utility_rates_info, index_location)
                                            # Set indexed_zip_code if we have it
                                            if zip_from_coords:
                                                indexed_zip_code = zip_from_coords
                                                print(f"[RAGService] utility_rates_indexed | zip={indexed_zip_code} | source=coordinates")
                                        else:
                                            print(f"[RAGService] ERROR nrel_api | error={utility_rates_info.get('errors', utility_rates_info.get('error', 'Unknown'))}")
                                            utility_rates_info = None
                                    else:
                                        print(f"[RAGService] ERROR invalid_data | utility_rates_info={utility_rates_info}")
                                        utility_rates_info = None
                                # Skip the rest of the utility rates fetching logic since we already got it
                                location_for_rates = None  # Set to None to skip the normal flow
                            except Exception as geocode_error:
                                print(f"[RAGService] ERROR geocode | city={city} state={state} | error={str(geocode_error)}")
                                # Fall back to using city/state string (may fail)
                                location_for_rates = f"{city}, {state}"
                    elif state:
                        location_for_rates = state
                
                # Final fallback: use location_to_use as-is (if it's not already a zip code we checked)
                if not location_for_rates:
                    if location_to_use and not (location_to_use.isdigit() and len(location_to_use) == 5):
                        # Only use location_to_use if it's not a zip code (zip codes already checked above)
                        location_for_rates = location_to_use
                    elif zip_from_question:
                        # Last resort: use zip_from_question if nothing else worked
                        location_for_rates = zip_from_question
                
                if location_for_rates:
                    print(f"[RAGService] utility_rates_fetching | location={location_for_rates} | source=api")
                    utility_rates_info = await self.nrel_client.get_utility_rates(
                        location=location_for_rates,
                        sector="residential"
                    )
                    
                    # Index utility rates if we got them
                    if utility_rates_info:
                        # Check if utility_rates_info is actually valid data
                        # NREL API might return empty dict or error structure
                        if isinstance(utility_rates_info, dict) and utility_rates_info:
                            # Check if it's not an error response
                            if "errors" not in utility_rates_info and "error" not in utility_rates_info:
                                await self._index_utility_rates(utility_rates_info, location_for_rates)
                                # Track the zip code used for indexing (if it's a zip code)
                                if location_for_rates and location_for_rates.isdigit() and len(location_for_rates) == 5:
                                    indexed_zip_code = location_for_rates
                                    print(f"[RAGService] utility_rates_indexed | zip={indexed_zip_code} | source=api")
                            else:
                                print(f"[RAGService] ERROR nrel_api | error={utility_rates_info.get('errors', utility_rates_info.get('error', 'Unknown'))}")
                                utility_rates_info = None
                        else:
                            print(f"[RAGService] ERROR invalid_data | utility_rates_info={utility_rates_info}")
                            utility_rates_info = None
            except Exception as e:
                # If utility rates fetch fails, continue with query
                print(f"[RAGService] ERROR fetch_utility_rates: {str(e)}")
                import traceback
                traceback.print_exc()
                utility_rates_info = None
        
        if indexed_zip_code:
            print(f"[RAGService] utility_rates_complete | zip={indexed_zip_code} | cached={utility_rates_info is None}")
        
        return indexed_zip_code, utility_rates_info
    
    def _is_electricity_cost_question(self, question: str) -> bool:
        """
        Detect if the question is about electricity costs/utility rates.
        
        Args:
            question: User's question
            
        Returns:
            True if question appears to be about electricity costs
        """
        question_lower = question.lower()
        
        # Keywords that indicate electricity cost questions
        cost_keywords = [
            "electricity cost", "electricity price", "electricity rate",
            "utility cost", "utility price", "utility rate",
            "power cost", "power price", "power rate",
            "energy cost", "energy price", "energy rate",
            "kwh cost", "kwh price", "kwh rate",
            "cost per kwh", "price per kwh", "rate per kwh",
            "how much does electricity cost",
            "what is the electricity rate",
            "electricity bill", "utility bill",
            "lower bill", "reduce bill", "lower electricity bill", "reduce electricity bill",
            "cut bill", "save on electricity", "save on utility"
        ]
        
        return any(keyword in question_lower for keyword in cost_keywords)
    
    def _is_charging_station_question(self, question: str) -> bool:
        """
        Detect if the question is about EV charging stations.
        
        Args:
            question: User's question
            
        Returns:
            True if question appears to be about charging stations
        """
        question_lower = question.lower()
        
        # Keywords that indicate charging station questions
        charging_keywords = [
            "charging station", "charging stations",
            "ev charging", "electric vehicle charging",
            "where can i charge", "where to charge",
            "charger", "chargers",
            "charging location", "charging locations",
            "dc fast charging", "level 2 charging",
            "j1772", "ccs", "chademo", "nema",
            "ev station", "ev stations",
            "electric vehicle station"
        ]
        
        return any(keyword in question_lower for keyword in charging_keywords)
    
    async def bulk_index_state(
        self,
        state: str,
        batch_size: int = 100,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Bulk index all stations for a state.
        
        Args:
            state: 2-letter US state code (e.g., "OH")
            batch_size: Number of stations to process per batch
            limit: Optional limit on total stations to index (for testing)
            
        Returns:
            Dictionary with indexing results
        """
        # Fetch all stations for the state
        # Handle case where limit might be the string 'None' or actual None
        if limit and limit != "None" and str(limit).lower() != "none":
            try:
                limit_int = int(limit)
                stations = await self.nrel_client.get_stations_by_state(
                    state=state,
                    limit=limit_int
                )
            except (ValueError, TypeError):
                # If limit can't be converted to int, fetch all stations
                stations = await self.nrel_client.get_all_stations_by_state(state=state)
        else:
            stations = await self.nrel_client.get_all_stations_by_state(state=state)
        
        if not stations:
            return {
                "state": state,
                "stations_fetched": 0,
                "stations_indexed": 0,
                "message": f"No stations found for state {state}"
            }
        
        total_stations = len(stations)
        indexed_count = 0
        skipped_count = 0
        
        # Get vector store index
        index = self.vector_store_service.get_index()
        
        # Process in batches
        for i in range(0, total_stations, batch_size):
            batch = stations[i:i + batch_size]
            
            # Convert to Documents
            documents = self.document_service.stations_to_documents(batch)
            
            # Validate documents structure
            if not documents or not isinstance(documents, list):
                print(f"[RAGService] ERROR bulk_index_state | invalid_documents | batch={i//batch_size + 1} | type={type(documents)}")
                continue
            
            # Check if documents is nested (list of lists)
            if documents and isinstance(documents[0], list):
                print(f"[RAGService] ERROR bulk_index_state | nested_list_detected | batch={i//batch_size + 1} | flattening")
                documents = [doc for sublist in documents for doc in sublist]
            
            # Use helper method for bulk insert
            batch_indexed, batch_failed = self._bulk_insert_documents(index, documents)
            indexed_count += batch_indexed
            skipped_count += batch_failed
            if batch_failed > 0:
                print(f"[RAGService] bulk_index_state | state={state} | batch={i//batch_size + 1} | indexed={batch_indexed} | failed={batch_failed}")
        
        return {
            "state": state,
            "stations_fetched": total_stations,
            "stations_indexed": indexed_count,
            "skipped": skipped_count,
            "message": f"Successfully indexed {indexed_count} stations for {state}"
        }
    
    def _make_query_cache_key(
        self,
        question: str,
        zip_code: Optional[str],
        top_k: int,
        detected_location_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create cache key for query result.
        
        Args:
            question: User question
            zip_code: Optional explicit zip code parameter
            top_k: Top K value
            detected_location_info: Optional detected location from question parsing
            
        Returns:
            Cache key string
        """
        # Build location identifier from detected location or explicit zip_code
        location_id = None
        if detected_location_info:
            # Prefer zip_code, then city+state, then state
            loc_zip = detected_location_info.get("zip_code")
            loc_city = detected_location_info.get("city")
            loc_state = detected_location_info.get("state")
            
            if loc_zip:
                location_id = f"zip:{loc_zip}"
            elif loc_city and loc_state:
                location_id = f"city:{loc_city.lower()},state:{loc_state.upper()}"
            elif loc_state:
                location_id = f"state:{loc_state.upper()}"
        
        # Fallback to explicit zip_code if no detected location
        if not location_id and zip_code:
            location_id = f"zip:{zip_code}"
        
        cache_data = {
            "question": question.lower().strip(),
            "location": location_id,  # Use location instead of just zip_code
            "top_k": top_k
        }
        cache_json = json.dumps(cache_data, sort_keys=True)
        cache_hash = hashlib.md5(cache_json.encode()).hexdigest()
        return f"rag_query:{cache_hash}"
    
    async def query_stream(
        self,
        question: str,
        zip_code: Optional[str] = None,
        top_k: int = 5,
        use_reranking: bool = False,
        rerank_top_n: int = 3
    ) -> AsyncGenerator[Tuple[str, Dict[str, Any]], None]:
        """
        Process a RAG query with streaming events.
        
        Yields tuples of (event_type, event_data) for SSE streaming.
        
        Event types:
        - status: Progress updates (analyzing, searching, retrieving, preparing, generating, processing, finalizing)
        - tool: Tool call notifications (transportation_tool, utility_tool, solar_production_tool, optimization_tool)
        - chunk: Answer text chunks (if streaming is supported)
        - done: Final response with sources
        - error: Error messages
        """
        query_start_time = time.time()
        tools_used = []
        
        try:
            # Yield immediately to start the HTTP response stream
            yield ("status", {"stage": "analyzing", "message": "Analyzing your question..."})
            await asyncio.sleep(0.01)
            
            # Validate inputs
            is_valid, error_msg = validate_query_inputs(question, zip_code, top_k)
            if not is_valid:
                yield ("error", {"message": f"Invalid input: {error_msg}"})
                return
            
            # Refine query for better retrieval
            refined_question = question  # Default to original question
            try:
                query_refinement = self.query_refiner.refine(question)
                refined_question = query_refinement.get("refined_query", question)
                if refined_question != question:
                    self.logger.log_tool_execution(
                        tool_name="query_refiner",
                        question=question[:200],
                        success=True
                    )
            except Exception as refine_error:
                # If refinement fails, use original question
                self.logger.log_error(
                    error_type="QueryRefinementError",
                    error_message=str(refine_error),
                    context={"question": question[:200]}
                )
                refined_question = question
            
            # Location detection (needed before cache check)
            location_to_use = zip_code
            detected_location_info = None
            
            if not location_to_use:
                yield ("status", {"stage": "searching", "message": "Detecting location from question..."})
                await asyncio.sleep(0.01)
                location_info = await self.location_service.extract_location_from_question(question)
                detected_location_info = location_info
                
                if location_info:
                    location_type = location_info.get("location_type")
                    if location_info.get("state"):
                        normalized_state = self.location_service._normalize_state(location_info.get("state"))
                        if normalized_state:
                            location_info["state"] = normalized_state
                            detected_location_info["state"] = normalized_state
                    
                    # Extract zip code if available
                    extracted_zip = location_info.get("zip_code")
                    if extracted_zip:
                        location_to_use = extracted_zip
                    elif location_type == "city_state":
                        # For city/state, try to geocode to get zip code for station fetching
                        city = location_info.get("city")
                        state = location_info.get("state")
                        if city and state:
                            try:
                                # Try to geocode city/state to get zip code
                                geocoded_zip = await self.location_service.geocode_city_state_to_zip(city, state)
                                if geocoded_zip:
                                    location_to_use = geocoded_zip
                                    # Update detected_location_info with geocoded zip
                                    detected_location_info["zip_code"] = geocoded_zip
                                    location_info["zip_code"] = geocoded_zip
                                    print(f"[RAGService] geocoded_city_state | city={city} state={state} zip={geocoded_zip}")
                                else:
                                    # Fallback: fetch stations by state if geocoding fails
                                    print(f"[RAGService] geocode_failed | city={city} state={state} | falling_back_to_state")
                                    try:
                                        is_fresh, indexed_at = await self.freshness_checker.check_stations_freshness_by_state(state)
                                        if not is_fresh:
                                            if indexed_at:
                                                print(f"[RAGService] stations_check | state={state} | source=vector_store | stale=true")
                                            else:
                                                print(f"[RAGService] stations_check | state={state} | source=vector_store | found=false")
                                            yield ("status", {"stage": "retrieving", "message": f"Fetching stations for {state}..."})
                                            await self.fetch_and_index_stations_by_state(state, limit=200)
                                        else:
                                            print(f"[RAGService] stations_check | state={state} | source=vector_store | fresh=true")
                                    except Exception as e:
                                        print(f"[RAGService] stations_check | state={state} | error={str(e)}")
                                        await self.fetch_and_index_stations_by_state(state, limit=200)
                            except Exception as e:
                                print(f"[RAGService] ERROR geocode_city_state | city={city} state={state} | error={str(e)}")
                                # Fallback to state-level fetching
                                try:
                                    is_fresh, indexed_at = await self.freshness_checker.check_stations_freshness_by_state(state)
                                    if not is_fresh:
                                        yield ("status", {"stage": "retrieving", "message": f"Fetching stations for {state}..."})
                                        await self.fetch_and_index_stations_by_state(state, limit=200)
                                except Exception:
                                    pass
                    elif location_type == "state":
                        state = location_info.get("state")
                        if state:
                            try:
                                is_fresh, indexed_at = await self.freshness_checker.check_stations_freshness_by_state(state)
                                if not is_fresh:
                                    if indexed_at:
                                        print(f"[RAGService] stations_check | state={state} | source=vector_store | stale=true")
                                    else:
                                        print(f"[RAGService] stations_check | state={state} | source=vector_store | found=false")
                                    yield ("status", {"stage": "retrieving", "message": f"Fetching stations for {state}..."})
                                    await self.fetch_and_index_stations_by_state(state, limit=200)
                                else:
                                    print(f"[RAGService] stations_check | state={state} | source=vector_store | fresh=true")
                            except Exception as e:
                                print(f"[RAGService] stations_check | state={state} | error={str(e)}")
                                await self.fetch_and_index_stations_by_state(state, limit=200)
            
            # Check query result cache (cache for 1 hour) - after location detection
            cache_key = self._make_query_cache_key(question, zip_code, top_k, detected_location_info)
            cached_result = await self.cache_service.get(
                cache_key,
                timedelta(hours=1)
            )
            if cached_result:
                self.logger.log_cache(
                    operation="query_cache_hit",
                    key=cache_key,
                    cache_hit=True
                )
                yield ("done", cached_result)
                return
            
            # Check if we need to fetch stations (with freshness check)
            if location_to_use:
                try:
                    is_fresh, indexed_at = await self.freshness_checker.check_stations_freshness(location_to_use)
                    if not is_fresh:
                        if indexed_at:
                            print(f"[RAGService] stations_check | zip={location_to_use} | source=vector_store | stale=true")
                        else:
                            print(f"[RAGService] stations_check | zip={location_to_use} | source=vector_store | found=false")
                        yield ("status", {"stage": "retrieving", "message": f"Fetching stations for zip {location_to_use}..."})
                        await asyncio.sleep(0.01)
                        await self.fetch_and_index_stations(location_to_use)
                    else:
                        print(f"[RAGService] stations_check | zip={location_to_use} | source=vector_store | fresh=true")
                except Exception as e:
                    print(f"[RAGService] stations_check | zip={location_to_use} | source=vector_store | error=check_failed | error={str(e)}")
                    yield ("status", {"stage": "retrieving", "message": f"Fetching stations for zip {location_to_use}..."})
                    await asyncio.sleep(0.01)
                    await self.fetch_and_index_stations(location_to_use)
            
            # Check if we need to fetch and index BCL (building codes) data
            is_building_question = self._is_building_efficiency_question(question)
            if is_building_question:
                state_for_bcl = None
                if detected_location_info:
                    state_for_bcl = detected_location_info.get("state")
                
                if state_for_bcl:
                    # Check vector store freshness (best practice: avoid unnecessary API calls)
                    try:
                        is_fresh, indexed_at = await self.freshness_checker.check_bcl_measures_freshness(state_for_bcl)
                        if not is_fresh:
                            if indexed_at:
                                print(f"[RAGService] bcl_measures_check | state={state_for_bcl} | source=vector_store | stale=true")
                            else:
                                print(f"[RAGService] bcl_measures_check | state={state_for_bcl} | source=vector_store | found=false")
                            yield ("status", {"stage": "retrieving", "message": f"Fetching building efficiency data for {state_for_bcl}..."})
                            print(f"[RAGService] bcl_measures_fetching | state={state_for_bcl} | source=api")
                            bcl_result = await self.fetch_and_index_bcl_measures(
                                state=state_for_bcl,
                                query=question,
                                limit=20
                            )
                            print(f"[RAGService] bcl_measures_indexed | state={state_for_bcl} | source=api | result={bcl_result.get('message', 'Unknown')}")
                        else:
                            print(f"[RAGService] bcl_measures_check | state={state_for_bcl} | source=vector_store | fresh=true")
                    except Exception as e:
                        print(f"[RAGService] ERROR bcl_check: {str(e)}")
                        # Fallback: try to fetch anyway
                        try:
                            yield ("status", {"stage": "retrieving", "message": f"Fetching building efficiency data for {state_for_bcl}..."})
                            print(f"[RAGService] bcl_measures_fetching | state={state_for_bcl} | source=api")
                            bcl_result = await self.fetch_and_index_bcl_measures(
                                state=state_for_bcl,
                                query=question,
                                limit=20
                            )
                            print(f"[RAGService] bcl_measures_indexed | state={state_for_bcl} | source=api | result={bcl_result.get('message', 'Unknown')}")
                        except Exception as fetch_error:
                            print(f"[RAGService] ERROR bcl_fetch: {str(fetch_error)}")
            
            # Get index and LLM
            try:
                index = self.vector_store_service.get_index()
            except Exception as e:
                yield ("error", {"message": f"Failed to initialize vector store: {str(e)}"})
                return
            
            llm = self.llm_service.get_llm()
            
            # Wrap LLM with timeout handling
            class TimeoutLLMWrapper:
                def __init__(self, wrapped_llm):
                    self._wrapped = wrapped_llm
                
                def __getattr__(self, name):
                    if name in ['acomplete', 'complete', 'apredict', 'predict']:
                        return getattr(self, name)
                    return getattr(self._wrapped, name)
                
                async def acomplete(self, prompt, **kwargs):
                    return await self._wrapped.acomplete(prompt, **kwargs)
                
                def complete(self, prompt, **kwargs):
                    return self._wrapped.complete(prompt, **kwargs)
                
                async def apredict(self, prompt, **kwargs):
                    import asyncio
                    return await asyncio.wait_for(
                        self._wrapped.apredict(prompt, **kwargs),
                        timeout=120.0
                    )
                
                def predict(self, prompt, **kwargs):
                    return self._wrapped.predict(prompt, **kwargs)
            
            llm = TimeoutLLMWrapper(llm)
            
            # Set system prompt
            solar_system_prompt = (
                "CRITICAL INSTRUCTIONS:\n"
                "1. When asked about electricity rates, costs, or time-of-use rates, you MUST use the utility_tool to get actual data. "
                "   NEVER make up or estimate electricity rates - always use the tool results.\n"
                "2. When asked about solar energy production, savings, or payback periods, you MUST use the solar_production_tool "
                "   to get actual production data for the specified location and system size. NEVER estimate solar production - always use the tool results.\n"
                "3. When comparing scenarios (e.g., charging at different times vs solar), you MUST:\n"
                "   a) Use utility_tool to get actual electricity rates (including time-of-use rates if available)\n"
                "   b) Use solar_production_tool to get actual solar production data\n"
                "   c) Use the ACTUAL DATA from these tools in your calculations - do not substitute with estimates\n"
                "4. Always cite the tool results in your answer. If a tool returns data, you must use that exact data, not approximations.\n"
                "5. If tool results are not available, clearly state that you could not retrieve the data rather than making up numbers."
            )
            
            if hasattr(llm, "system_prompt") and llm.system_prompt:
                llm.system_prompt = f"{llm.system_prompt}\n\n{solar_system_prompt}"
            else:
                llm.system_prompt = solar_system_prompt
            
            # Build location filters
            initial_top_k = top_k * 2 if use_reranking else top_k
            location_filters = []
            print(f"[RAGService] Building location_filters: detected_location_info={detected_location_info}, location_to_use={location_to_use}")
            if detected_location_info:
                city = detected_location_info.get("city")
                state = detected_location_info.get("state")
                zip_code_val = detected_location_info.get("zip_code") or location_to_use
                print(f"[RAGService] detected_location_info has: city={city}, state={state}, zip_code={detected_location_info.get('zip_code')}, zip_code_val={zip_code_val}")
                
                if zip_code_val:
                    location_filters.append(
                        MetadataFilter(key="queried_zip", value=zip_code_val, operator=FilterOperator.EQ)
                    )
                    print(f"[RAGService] Added queried_zip filter: {zip_code_val}")
                elif city and state:
                    location_filters.append(
                        MetadataFilter(key="city", value=city, operator=FilterOperator.EQ)
                    )
                    location_filters.append(
                        MetadataFilter(key="state", value=state, operator=FilterOperator.EQ)
                    )
                    print(f"[RAGService] Added city/state filters: {city}, {state}")
                elif state:
                    location_filters.append(
                        MetadataFilter(key="state", value=state, operator=FilterOperator.EQ)
                    )
                    print(f"[RAGService] Added state filter: {state}")
            # Also check location_to_use directly if detected_location_info didn't yield a zipcode
            # This handles cases where zipcode is detected but not in detected_location_info structure
            if not location_filters and location_to_use:
                # If location_to_use looks like a zipcode (5 digits), add it
                if isinstance(location_to_use, str) and location_to_use.isdigit() and len(location_to_use) == 5:
                    location_filters.append(
                        MetadataFilter(key="queried_zip", value=location_to_use, operator=FilterOperator.EQ)
                    )
                    print(f"[RAGService] Added zipcode {location_to_use} to location_filters from location_to_use (fallback)")
            
            print(f"[RAGService] Final location_filters: {len(location_filters)} filter(s)")
            for i, f in enumerate(location_filters):
                if hasattr(f, 'key') and hasattr(f, 'value'):
                    print(f"[RAGService]   Filter {i}: key={f.key}, value={f.value}")
            
            # Create retrievers
            transportation_filter_filters = [
                MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ)
            ]
            transportation_filter_filters.extend(location_filters)
            transportation_filter = MetadataFilters(filters=transportation_filter_filters)
            transportation_retriever = VectorIndexRetriever(
                index=index,
                similarity_top_k=initial_top_k,
                filters=transportation_filter
            )
            
            utility_filter_filters = [
                MetadataFilter(key="domain", value="utility", operator=FilterOperator.EQ)
            ]
            utility_filter = MetadataFilters(filters=utility_filter_filters)
            utility_retriever = VectorIndexRetriever(
                index=index,
                similarity_top_k=initial_top_k,
                filters=utility_filter
            )
            
            # Create node postprocessors
            node_postprocessors = []
            if use_reranking:
                try:
                    reranker = LLMRerank(
                        llm=llm,
                        top_n=rerank_top_n
                    )
                    node_postprocessors.append(reranker)
                except Exception:
                    use_reranking = False
            
            # Create query engines
            transportation_query_engine = RetrieverQueryEngine.from_args(
                retriever=transportation_retriever,
                llm=llm,
                node_postprocessors=node_postprocessors
            )
            
            from llama_index.core.prompts import PromptTemplate
            utility_response_synthesizer = get_response_synthesizer(
                llm=llm,
                response_mode=ResponseMode.COMPACT,
                text_qa_template=PromptTemplate(
                    "Context information from utility rate data is below.\n"
                    "---------------------\n"
                    "{context_str}\n"
                    "---------------------\n"
                    "You are a helpful assistant providing utility rate information from a public database. "
                    "This is factual data about electricity rates, not financial advice. "
                    "Provide the utility rate information clearly and accurately.\n"
                    "Query: {query_str}\n"
                    "Answer: "
                )
            )
            
            utility_query_engine = RetrieverQueryEngine.from_args(
                retriever=utility_retriever,
                llm=llm,
                node_postprocessors=node_postprocessors,
                response_synthesizer=utility_response_synthesizer
            )
            
            # Use RAGOrchestrator
            from src.orchestrator import RAGOrchestrator
            orchestrator = RAGOrchestrator(
                llm=llm,
                vector_store_service=self.vector_store_service,
                callback_manager=None,
                enable_observability=True,
                observability_handler_type="silent"  # Use silent handler to avoid verbose prompt/message output
            )
            
            # Fetch and index utility rates BEFORE creating tools (so we can filter by zip)
            # Check if we need utility rates and yield status update BEFORE fetching
            is_electricity_cost_question = self._is_electricity_cost_question(question)
            question_lower = question.lower()
            requires_utility_for_rates = any(keyword in question_lower for keyword in [
                "charging at", "time-of-use", "off-peak", "peak rate", "charging cost", "savings", "compare",
                "lower bill", "reduce bill", "cut bill", "save on"
            ]) and not is_electricity_cost_question
            
            if is_electricity_cost_question or requires_utility_for_rates:
                yield ("status", {"stage": "retrieving", "message": "Fetching utility rates..."})
                await asyncio.sleep(0.01)
            
            indexed_zip_code, utility_rates_info = await self._fetch_and_index_utility_rates_if_needed(
                question=question,
                detected_location_info=detected_location_info,
                location_to_use=location_to_use
            )
            
            # Update location_filters to include zip filter if we indexed utility rates
            # The utility tool uses 'zip' metadata (not 'queried_zip'), so we need to add it separately
            if indexed_zip_code:
                zip_filter = MetadataFilter(key="zip", value=indexed_zip_code, operator=FilterOperator.EQ)
                # Check if zip filter already exists
                if not any(hasattr(f, 'key') and f.key == "zip" and f.value == indexed_zip_code for f in location_filters):
                    location_filters.append(zip_filter)
            
            # Create tools with updated location filters
            # Pass location_filters if we have any filters OR if we have location_to_use (zipcode)
            # This ensures tools get location context even if detected_location_info structure is incomplete
            should_pass_filters = len(location_filters) > 0 or bool(location_to_use and isinstance(location_to_use, str) and location_to_use.isdigit() and len(location_to_use) == 5)
            tools = orchestrator.create_tools(
                top_k=top_k,
                use_reranking=use_reranking,
                rerank_top_n=rerank_top_n,
                location_filters=location_filters if should_pass_filters else None,
                nrel_client=self.nrel_client,
                bcl_client=self.bcl_client,
                location_service=self.location_service,
                reopt_service=self.reopt_service
            )
            
            # Check which tools might be used (is_electricity_cost_question already checked above)
            is_charging_station_question = self._is_charging_station_question(question)
            
            if is_electricity_cost_question or requires_utility_for_rates:
                yield ("tool", {"tool": "utility_tool", "message": "Fetching utility rates..."})
                tools_used.append("utility_tool")
                await asyncio.sleep(0)  # Yield control to allow tool notification to be sent
            
            # Check for other tools
            if any(keyword in question_lower for keyword in ["solar", "solar panel", "solar energy"]):
                yield ("tool", {"tool": "solar_production_tool", "message": "Preparing solar analysis..."})
                tools_used.append("solar_production_tool")
            
            if is_charging_station_question:
                yield ("tool", {"tool": "transportation_tool", "message": "Searching for charging stations..."})
                tools_used.append("transportation_tool")
            
            # Check for building-related questions
            is_building_question = self._is_building_efficiency_question(question)
            if is_building_question or any(keyword in question_lower for keyword in [
                "building energy", "building profile", "building code", "energy code",
                "building efficiency", "building performance", "building standard"
            ]):
                yield ("tool", {"tool": "buildings_tool", "message": "Searching building codes and efficiency standards..."})
                tools_used.append("buildings_tool")
            
            if any(keyword in question_lower for keyword in [
                "investment", "sizing", "roi", "optimal size", "optimal system", "npv",
                "net present value", "financial analysis", "economic analysis", "optimal design",
                "cost-benefit", "payback", "optimize", "optimization"
            ]):
                yield ("tool", {"tool": "optimization_tool", "message": "Running optimization analysis..."})
                tools_used.append("optimization_tool")
            
            # Create SubQuestionQueryEngine
            router_query_engine = orchestrator.create_sub_question_query_engine(tools, use_robust_parser=True)
            
            # Add location context
            location_context = ""
            if detected_location_info:
                location_type = detected_location_info.get("location_type")
                city = detected_location_info.get("city")
                state = detected_location_info.get("state")
                zip_code_val = detected_location_info.get("zip_code") or location_to_use
                
                if location_type == "zip_code" and zip_code_val:
                    location_context = f"\n\nIMPORTANT: The user is specifically asking about locations in zip code {zip_code_val}. Only return results for this zip code area."
                elif location_type == "city_state":
                    if city and state:
                        location_context = f"\n\nIMPORTANT: The user is specifically asking about locations in {city}, {state}. Only return results for {city}, {state}. Do not return results for other cities."
                    elif state:
                        location_context = f"\n\nIMPORTANT: The user is asking about locations in {state}."
                elif location_type == "state":
                    location_context = f"\n\nIMPORTANT: The user is asking about locations in {state}."
            
            completion_instruction = ""
            if "cost" in question.lower() or "compare" in question.lower() or "difference" in question.lower():
                completion_instruction = "\n\nIMPORTANT: Please provide a complete answer with all calculations and comparisons. Do not stop mid-sentence. Include all requested information such as cost comparisons and monthly cost differences."
            
            # Add instruction to include all tool results
            if is_building_question or any(keyword in question.lower() for keyword in ["building energy", "building profile", "building code"]):
                completion_instruction += "\n\nIMPORTANT: If building energy codes, efficiency standards, or building performance data was retrieved, you MUST include this information in your response. Do not omit building-related information."
            
            # Use refined question for better retrieval
            contextual_question = (
                f"{refined_question}"
                f"{location_context}"
                f"{completion_instruction}"
            )
            
            # Retrieve nodes for sources (for fallback if SubQuestionQueryEngine fails)
            # Note: We don't check if nodes exist here because SubQuestionQueryEngine handles
            # tool routing. Some tools (solar, optimization) don't need indexed data.
            yield ("status", {"stage": "searching", "message": "Searching knowledge base..."})
            await asyncio.sleep(0)  # Yield control to allow status update to be sent
            
            trans_nodes = []
            util_nodes = []
            try:
                trans_nodes = transportation_retriever.retrieve(contextual_question)
            except Exception:
                pass
            
            try:
                util_nodes = utility_retriever.retrieve(contextual_question)
            except Exception:
                pass
            
            yield ("status", {"stage": "retrieving", "message": "Retrieving relevant information..."})
            await asyncio.sleep(0)  # Yield control to allow status update to be sent
            
            # Execute query - SubQuestionQueryEngine will route to appropriate tools
            # Don't block execution if trans/util nodes are empty - other tools may still work
            yield ("status", {"stage": "preparing", "message": "Preparing query for AI..."})
            await asyncio.sleep(0)  # Yield control to allow status update to be sent
            
            yield ("status", {"stage": "generating", "message": "Generating response..."})
            await asyncio.sleep(0)  # Yield control to allow status update to be sent
            try:
                response = await asyncio.wait_for(
                    router_query_engine.aquery(contextual_question),
                    timeout=300.0
                )
            except asyncio.TimeoutError:
                yield ("error", {"message": "Query timed out. Please try again with a simpler question."})
                return
            except Exception as e:
                yield ("error", {"message": f"Query failed: {str(e)}"})
                return
            
            yield ("status", {"stage": "processing", "message": "Processing answer..."})
            await asyncio.sleep(0)  # Yield control to allow status update to be sent
            
            # Extract answer text
            answer_text = ""
            try:
                if hasattr(response, "response"):
                    resp_value = response.response
                    if isinstance(resp_value, str):
                        answer_text = resp_value
                    elif isinstance(resp_value, list) and len(resp_value) > 0:
                        first_item = resp_value[0]
                        answer_text = first_item if isinstance(first_item, str) else str(first_item)
                    elif resp_value is not None:
                        if hasattr(resp_value, "response"):
                            try:
                                nested_resp = resp_value.response
                                answer_text = nested_resp if isinstance(nested_resp, str) else str(nested_resp)
                            except:
                                pass
                        if not answer_text and hasattr(resp_value, "text"):
                            answer_text = resp_value.text if resp_value.text is not None else ""
                        if not answer_text:
                            answer_text = str(resp_value) if resp_value is not None else ""
                
                if not answer_text and hasattr(response, "text"):
                    text_value = response.text
                    answer_text = text_value if isinstance(text_value, str) else str(text_value) if text_value is not None else ""
                
                if not answer_text and hasattr(response, "get_response"):
                    try:
                        resp_obj = response.get_response()
                        if isinstance(resp_obj, str):
                            answer_text = resp_obj
                        elif hasattr(resp_obj, "response"):
                            answer_text = resp_obj.response if isinstance(resp_obj.response, str) else str(resp_obj.response)
                        elif hasattr(resp_obj, "text"):
                            answer_text = resp_obj.text if resp_obj.text is not None else ""
                        else:
                            answer_text = str(resp_obj) if resp_obj is not None else ""
                    except:
                        pass
                
                if not answer_text:
                    answer_text = str(response) if response is not None else ""
            except Exception:
                answer_text = ""
            
            # Clean up answer text
            if answer_text:
                answer_text = answer_text.strip()
                answer_text = re.sub(r'^Response\s*\d*:\s*', '', answer_text, flags=re.IGNORECASE)
                # Remove LaTeX math notation (escaped brackets)
                answer_text = re.sub(r'\\\[', '', answer_text)  # Remove \[
                answer_text = re.sub(r'\\\]', '', answer_text)  # Remove \]
                answer_text = re.sub(r'\\\(', '', answer_text)  # Remove \( (inline math)
                answer_text = re.sub(r'\\\)', '', answer_text)  # Remove \) (inline math)
                answer_text = answer_text.strip()
            
            # Get source nodes and extract tools actually used
            final_nodes = []
            try:
                if hasattr(response, "source_nodes") and response.source_nodes:
                    actual_source_nodes = []
                    for node in response.source_nodes:
                        node_text = ""
                        try:
                            if hasattr(node, "text"):
                                node_text = node.text or ""
                            elif hasattr(node, "node") and hasattr(node.node, "text"):
                                node_text = node.node.text or ""
                            elif hasattr(node, "get_content"):
                                node_text = node.get_content() or ""
                            else:
                                node_text = str(node) if node else ""
                        except:
                            node_text = str(node) if node else ""
                        
                        if node_text:
                            node_text_lower = node_text.lower()
                            if ("sub question:" in node_text_lower or 
                                "sub_question" in node_text_lower or
                                node_text.startswith("Sub question:")):
                                continue
                        
                        if hasattr(node, "metadata"):
                            metadata = node.metadata or {}
                            if isinstance(metadata, dict):
                                if any(key in str(metadata).lower() for key in ["sub_question", "subquestion"]):
                                    continue
                                
                                # Extract tool name from metadata if available
                                tool_name = metadata.get("tool_name") or metadata.get("tool")
                                if tool_name and tool_name not in tools_used:
                                    tools_used.append(tool_name)
                                
                                # Detect tool usage from domain metadata
                                domain = metadata.get("domain")
                                if domain == "buildings" and "buildings_tool" not in tools_used:
                                    tools_used.append("buildings_tool")
                                elif domain == "utility" and "utility_tool" not in tools_used:
                                    tools_used.append("utility_tool")
                                elif domain == "transportation" and "transportation_tool" not in tools_used:
                                    tools_used.append("transportation_tool")
                        
                        actual_source_nodes.append(node)
                    
                    if actual_source_nodes:
                        final_nodes = actual_source_nodes[:top_k]
            except:
                pass
            
            # Also check response text for tool mentions (fallback detection)
            if answer_text:
                answer_lower = answer_text.lower()
                if any(keyword in answer_lower for keyword in ["building code", "energy code", "building efficiency", "building standard", "iecc", "ashrae"]):
                    if "buildings_tool" not in tools_used:
                        tools_used.append("buildings_tool")
            
            if not final_nodes:
                if is_charging_station_question and trans_nodes:
                    final_nodes = trans_nodes[:top_k]
                elif is_electricity_cost_question and util_nodes:
                    final_nodes = util_nodes[:top_k]
                elif len(trans_nodes) >= len(util_nodes) and trans_nodes:
                    final_nodes = trans_nodes[:top_k]
                elif util_nodes:
                    final_nodes = util_nodes[:top_k]
            
            yield ("status", {"stage": "finalizing", "message": "Finalizing response..."})
            await asyncio.sleep(0)  # Yield control to allow status update to be sent
            
            # Build final response
            response_time_ms = (time.time() - query_start_time) * 1000
            
            response_data = {
                "question": question,
                "answer": answer_text if answer_text else "I couldn't generate a response. Please try rephrasing your question.",
                "sources": [
                    {
                        "text": (
                            (node.text[:200] + "..." if len(node.text) > 200 else node.text)
                            if hasattr(node, "text") and node.text
                            else str(node)[:200] + "..." if len(str(node)) > 200 else str(node)
                        ),
                        "metadata": node.metadata if hasattr(node, "metadata") else {}
                    }
                    for node in final_nodes
                ],
                "num_sources": len(final_nodes),
                "reranked": use_reranking and len(final_nodes) > 0
            }
            
            if detected_location_info:
                response_data["detected_location"] = {
                    "type": detected_location_info.get("location_type"),
                    "zip_code": detected_location_info.get("zip_code"),
                    "city": detected_location_info.get("city"),
                    "state": detected_location_info.get("state")
                }
            
            if utility_rates_info:
                response_data["utility_rates"] = utility_rates_info
            
            # Log query completion
            
            self.logger.log_query(
                question=question,
                tools_used=tools_used,
                response_time_ms=response_time_ms,
                success=True,
                num_sources=len(final_nodes),
                zip_code=zip_code or detected_location_info.get("zip_code") if detected_location_info else None
            )
            
            # Cache query result
            try:
                await self.cache_service.set(cache_key, response_data)
            except Exception as cache_error:
                # Don't fail if caching fails
                self.logger.log_error(
                    error_type="CacheError",
                    error_message=f"Failed to cache query result: {str(cache_error)}"
                )
            
            # Emit final response
            yield ("done", response_data)
            
        except Exception as e:
            error_msg = str(e)
            response_time_ms = (time.time() - query_start_time) * 1000
            
            self.logger.log_error(
                error_type=type(e).__name__,
                error_message=error_msg,
                context={
                    "question": question,
                    "tools_used": tools_used,
                    "response_time_ms": response_time_ms
                }
            )
            yield ("error", {"message": error_msg})


