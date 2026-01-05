from typing import List, Dict, Any, Optional
import json
import re
from llama_index.core import Document
from llama_index.core.query_engine import RetrieverQueryEngine, SubQuestionQueryEngine, BaseQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.tools import QueryEngineTool
from llama_index.core.settings import Settings
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.response_synthesizers.type import ResponseMode
from llama_index.core.question_gen.llm_generators import LLMQuestionGenerator
from llama_index.core.question_gen.output_parser import SubQuestionOutputParser
from llama_index.core.output_parsers.base import StructuredOutput
from llama_index.core.question_gen.types import SubQuestion
from llama_index.core.types import BaseOutputParser
from llama_index.core.schema import NodeWithScore, TextNode, QueryBundle
from llama_index.core.base.response.schema import Response
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
from llama_index.core.callbacks.base import CallbackManager
from app.services.nrel_client import NRELClient
from app.services.document_service import DocumentService
from app.services.vector_store_service import VectorStoreService
from app.services.llm_service import LLMService
from app.services.location_service import LocationService
from app.services.validators import validate_query_inputs, InputValidator
from app.services.logger_service import get_logger
from app.services.reopt_service import REoptService
import time


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
        self.document_service = DocumentService()
        self.vector_store_service = VectorStoreService(llm_mode=llm_mode)
        self.llm_service = LLMService()
        self.location_service = LocationService()
        self.reopt_service = REoptService()
        self.logger = get_logger("rag_service")
    
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
        try:
            # Bulk insert all documents at once for better performance
            index.insert(documents)
            indexed_count = len(documents)
        except Exception as e:
            # If bulk insert fails, fall back to individual inserts for error handling
            print(f"Warning: Bulk insert failed, falling back to individual inserts: {str(e)}")
            for doc in documents:
                try:
                    index.insert(doc)
                    indexed_count += 1
                except Exception as doc_error:
                    failed_count += 1
                    print(f"Warning: Failed to insert document {doc.id_}: {str(doc_error)}")
                    if failed_count <= 3:  # Print first few errors
                        import traceback
                        traceback.print_exc()
        
        if failed_count > 0:
            print(f"Warning: {failed_count} out of {len(documents)} documents failed to index")
        
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
        try:
            # Bulk insert all documents at once
            index.insert(documents)
            indexed_count = len(documents)
        except Exception as e:
            # If bulk insert fails, fall back to individual inserts
            print(f"Warning: Bulk insert failed, falling back to individual inserts: {str(e)}")
            for doc in documents:
                try:
                    index.insert(doc)
                    indexed_count += 1
                except Exception:
                    # Skip duplicates or errors
                    pass
        
        return {
            "state": state,
            "stations_fetched": len(stations),
            "stations_indexed": indexed_count,
            "message": f"Successfully indexed {indexed_count} stations for {state}"
        }
    
    async def query(
        self,
        question: str,
        zip_code: Optional[str] = None,
        top_k: int = 5,
        use_reranking: bool = False,  # Default to False for faster responses
        rerank_top_n: int = 3
    ) -> Dict[str, Any]:
        """
        Process a RAG query with input validation.
        
        Args:
            question: User question
            zip_code: Optional zip code
            top_k: Number of results to return
            use_reranking: Whether to use LLM reranking
            rerank_top_n: Number of results to rerank
            
        Returns:
            Dictionary with answer, sources, and metadata
        """
        # Track query start time for logging
        query_start_time = time.time()
        tools_used = []
        
        # Validate inputs
        is_valid, error_msg = validate_query_inputs(question, zip_code, top_k)
        if not is_valid:
            response_time_ms = (time.time() - query_start_time) * 1000
            self.logger.log_query(
                question=question,
                response_time_ms=response_time_ms,
                success=False,
                error=f"Validation error: {error_msg}",
                zip_code=zip_code
            )
            return {
                "question": question,
                "answer": f"Invalid input: {error_msg}. Please check your question and try again.",
                "sources": [],
                "num_sources": 0,
                "error": error_msg
            }
        """
        Perform RAG query: retrieve relevant stations and generate response.
        
        Args:
            question: User's question (e.g., "Where can I charge my Tesla?")
            zip_code: Optional zip code to fetch and index stations first
            top_k: Number of relevant documents to retrieve initially (before reranking)
            use_reranking: Whether to use LLM-based reranking (default: True)
            rerank_top_n: Number of documents to return after reranking (default: 3)
            
        Returns:
            Dictionary with answer and metadata
        """
        # Determine location to use for fetching stations
        location_to_use = zip_code
        detected_location_info = None
        
        # If zip code not provided, try to extract location from question
        if not location_to_use:
            location_info = await self.location_service.extract_location_from_question(question)
            detected_location_info = location_info
            
            if location_info:
                location_type = location_info.get("location_type")
                
                # Normalize state to 2-letter code if present
                if location_info.get("state"):
                    normalized_state = self.location_service._normalize_state(location_info.get("state"))
                    if normalized_state:
                        location_info["state"] = normalized_state
                        detected_location_info["state"] = normalized_state
                
                # Always try to extract zip_code first if available, regardless of location_type
                extracted_zip = location_info.get("zip_code")
                if extracted_zip:
                    location_to_use = extracted_zip
                elif location_type == "zip_code":
                    # Use extracted zip code
                    location_to_use = location_info.get("zip_code")
                elif location_type == "state":
                    # Check if we already have stations for this state before fetching
                    state = location_info.get("state")
                    if state:
                        try:
                            index = self.vector_store_service.get_index()
                            test_retriever = VectorIndexRetriever(
                                index=index,
                                similarity_top_k=1,
                                filters=MetadataFilters(filters=[
                                    MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ),
                                    MetadataFilter(key="state", value=state, operator=FilterOperator.EQ)
                                ])
                            )
                            test_nodes = test_retriever.retrieve("charging station")
                            if not test_nodes or len(test_nodes) == 0:
                                print(f"No stations found for state {state}, fetching from NREL...")
                                await self.fetch_and_index_stations_by_state(state, limit=200)
                            else:
                                print(f"Found existing stations for state {state}, skipping fetch/index")
                        except Exception:
                            # If check fails, fetch stations as fallback
                            await self.fetch_and_index_stations_by_state(state, limit=200)
                elif location_type == "city_state":
                    # For city+state, try to get zip code first, then fetch stations
                    city = location_info.get("city")
                    state = location_info.get("state")
                    if city and state:
                        # Try to lookup zip code from city/state using multiple methods
                        zip_from_city_state = await self.nrel_client._lookup_zip_from_city_state(city, state)
                        if not zip_from_city_state:
                            # Fallback: try geocoding city/state to get zip code
                            zip_from_city_state = await self.location_service.geocode_city_state_to_zip(city, state)
                        
                        if zip_from_city_state:
                            location_to_use = zip_from_city_state
                            # Update detected_location_info with the zip code we found
                            detected_location_info["zip_code"] = zip_from_city_state
                            detected_location_info["location_type"] = "zip_code"
                        else:
                            # Fall back to fetching by state if zip lookup fails
                            # But keep city/state info for filtering
                            if state:
                                try:
                                    index = self.vector_store_service.get_index()
                                    test_retriever = VectorIndexRetriever(
                                        index=index,
                                        similarity_top_k=1,
                                        filters=MetadataFilters(filters=[
                                            MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ),
                                            MetadataFilter(key="state", value=state, operator=FilterOperator.EQ)
                                        ])
                                    )
                                    test_nodes = test_retriever.retrieve("charging station")
                                    if not test_nodes or len(test_nodes) == 0:
                                        print(f"No stations found for state {state}, fetching from NREL...")
                                        await self.fetch_and_index_stations_by_state(state, limit=200)
                                    else:
                                        print(f"Found existing stations for state {state}, skipping fetch/index")
                                except Exception:
                                    await self.fetch_and_index_stations_by_state(state, limit=200)
                    elif state:
                        # Only state available, fetch by state
                        try:
                            index = self.vector_store_service.get_index()
                            test_retriever = VectorIndexRetriever(
                                index=index,
                                similarity_top_k=1,
                                filters=MetadataFilters(filters=[
                                    MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ),
                                    MetadataFilter(key="state", value=state, operator=FilterOperator.EQ)
                                ])
                            )
                            test_nodes = test_retriever.retrieve("charging station")
                            if not test_nodes or len(test_nodes) == 0:
                                print(f"No stations found for state {state}, fetching from NREL...")
                                await self.fetch_and_index_stations_by_state(state, limit=200)
                            else:
                                print(f"Found existing stations for state {state}, skipping fetch/index")
                        except Exception:
                            await self.fetch_and_index_stations_by_state(state, limit=200)
        
        # If zip code available (either provided or extracted), check if we need to fetch stations
        # Only fetch if we don't already have stations for this location
        if location_to_use:
            # Quick check: try to retrieve nodes first to see if data exists
            # This avoids expensive fetch/index operations if data already exists
            try:
                index = self.vector_store_service.get_index()
                test_retriever = VectorIndexRetriever(
                    index=index,
                    similarity_top_k=1,
                    filters=MetadataFilters(filters=[
                        MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ),
                        MetadataFilter(key="queried_zip", value=location_to_use, operator=FilterOperator.EQ)
                    ])
                )
                # Try a quick retrieval to see if we have data
                test_nodes = test_retriever.retrieve("charging station")
                if not test_nodes or len(test_nodes) == 0:
                    # No data found, fetch and index stations
                    print(f"No stations found for zip {location_to_use}, fetching from NREL...")
                    await self.fetch_and_index_stations(location_to_use)
                else:
                    print(f"Found existing stations for zip {location_to_use}, skipping fetch/index")
            except Exception as e:
                # If check fails, fetch stations as fallback
                print(f"Warning: Could not check for existing stations: {str(e)}, fetching new stations...")
                await self.fetch_and_index_stations(location_to_use)
        
        # Get the index and LLM
        try:
            index = self.vector_store_service.get_index()
        except Exception as e:
            raise ValueError(
                f"Failed to initialize vector store index. "
                f"Make sure Supabase is configured and the table exists. Error: {str(e)}"
            )
        
        llm = self.llm_service.get_llm()
        
        # Wrap LLM with timeout handling for SubQuestionQueryEngine
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
                # Add timeout wrapper for LLM call (120 seconds)
                import asyncio
                return await asyncio.wait_for(
                    self._wrapped.apredict(prompt, **kwargs),
                    timeout=120.0
                )
            
            def predict(self, prompt, **kwargs):
                return self._wrapped.predict(prompt, **kwargs)
        
        llm = TimeoutLLMWrapper(llm)
        
        # Set system prompt for solar savings and EV cost offsetting questions
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
        
        # Append to existing system prompt if one exists, otherwise set it
        if hasattr(llm, "system_prompt") and llm.system_prompt:
            llm.system_prompt = f"{llm.system_prompt}\n\n{solar_system_prompt}"
        else:
            llm.system_prompt = solar_system_prompt
        
        # Create domain-filtered retrievers
        initial_top_k = top_k * 2 if use_reranking else top_k
        
        # Build location filters if we have location information
        # Note: Transportation uses queried_zip, utility tool will convert to zip automatically
        location_filters = []
        if detected_location_info:
            city = detected_location_info.get("city")
            state = detected_location_info.get("state")
            zip_code = detected_location_info.get("zip_code") or location_to_use
            
            # Add location-based filters
            if zip_code:
                # Transportation filter: use queried_zip (for stations fetched by zip)
                # Utility tool will automatically convert queried_zip to zip
                location_filters.append(
                    MetadataFilter(key="queried_zip", value=zip_code, operator=FilterOperator.EQ)
                )
            elif city and state:
                # Filter by city and state
                location_filters.append(
                    MetadataFilter(key="city", value=city, operator=FilterOperator.EQ)
                )
                location_filters.append(
                    MetadataFilter(key="state", value=state, operator=FilterOperator.EQ)
                )
            elif state:
                # Filter by state only
                location_filters.append(
                    MetadataFilter(key="state", value=state, operator=FilterOperator.EQ)
                )
        
        # Transportation domain retriever (EV stations)
        transportation_filter_filters = [
            MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ)
        ]
        # Add location filters if available
        transportation_filter_filters.extend(location_filters)
        
        transportation_filter = MetadataFilters(filters=transportation_filter_filters)
        transportation_retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=initial_top_k,
            filters=transportation_filter
        )
        
        # Utility domain retriever (utility rates)
        # We'll add zip filter after we know which zip code was used for indexing
        utility_filter_filters = [
            MetadataFilter(key="domain", value="utility", operator=FilterOperator.EQ)
        ]
        
        utility_filter = MetadataFilters(filters=utility_filter_filters)
        utility_retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=initial_top_k,
            filters=utility_filter
        )
        
        # Track which zip code was used for indexing utility rates
        indexed_zip_code = None
        
        # Create reranker if enabled
        # Note: We'll disable reranking later if we detect single domain only
        node_postprocessors = []
        if use_reranking:
            try:
                reranker = LLMRerank(
                    llm=llm,
                    top_n=rerank_top_n
                )
                node_postprocessors.append(reranker)
            except Exception as e:
                print(f"Warning: Failed to create reranker: {str(e)}, continuing without reranking")
                use_reranking = False
        
        # Create domain-specific query engines
        transportation_query_engine = RetrieverQueryEngine.from_args(
            retriever=transportation_retriever,
            llm=llm,
            node_postprocessors=node_postprocessors
        )
        
        # Create custom response synthesizer for utility tool to prevent safety filter issues
        from llama_index.core.response_synthesizers import get_response_synthesizer
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
        
        # Create QueryEngineTool objects for routing with explicit names
        # The names must match what the LLM will use in sub-question tool_name fields
        transportation_tool = QueryEngineTool.from_defaults(
            query_engine=transportation_query_engine,
            name="transportation_tool",  # Explicit name for SubQuestionQueryEngine
            description=(
                "TRANSPORTATION DOMAIN: Use this ONLY for questions about finding EV charging stations, "
                "electric vehicle charging locations, charger types (J1772, CCS, CHAdeMO, NEMA), "
                "DC fast charging, Level 2 charging, station networks, where to charge, charging locations, "
                "and EV infrastructure locations. "
                "Use this when the question asks WHERE to charge or WHERE charging stations are located. "
                "Use this when the question contains words like 'charging station', 'charging stations', "
                "'where can I charge', 'where to charge', 'charger location', 'charging location', "
                "'nearest charging station', 'find charging stations'. "
                "DO NOT use this for questions about charging COSTS, charging RATES, charging SAVINGS, "
                "'charging at [time]', electricity costs, utility rates, or power prices. "
                "Those questions should use utility_tool instead."
            )
        )
        
        utility_tool = QueryEngineTool.from_defaults(
            query_engine=utility_query_engine,
            name="utility_tool",  # Explicit name for SubQuestionQueryEngine
            description=(
                "UTILITY DOMAIN: Use this for questions about electricity rates, utility costs, "
                "electricity prices, utility providers, cost per kWh, price per kWh, residential "
                "electricity costs, commercial electricity rates, industrial rates, utility bills, "
                "time-of-use rates, off-peak rates, peak rates, charging costs, charging at specific times "
                "(e.g., 'charging at 11 PM'), charging savings, and utility company information. "
                "Use this when the question contains words like 'electricity cost', 'utility cost', "
                "'electricity rate', 'utility rate', 'electricity price', 'power cost', 'energy cost', "
                "'kwh cost', 'charging at [time]', 'charging cost', 'charging savings', 'time-of-use', "
                "'off-peak', 'peak rate', 'compare savings', or 'monthly savings'. "
                "IMPORTANT: Questions about 'charging at 11 PM' or 'charging costs' are about electricity "
                "rates/costs, NOT about finding charging stations. Use utility_tool for these. "
                "NOTE: The data source provides flat rates (residential, commercial, industrial) but may not "
                "include time-of-use rate schedules. If time-of-use rates are requested but not found, "
                "use the available flat residential rate for calculations. "
                "DO NOT use this for charging station locations - use transportation_tool for that."
            )
        )
        
        # Use RAGOrchestrator to create tools and SubQuestionQueryEngine
        orchestrator = RAGOrchestrator(
            llm=llm,
            vector_store_service=self.vector_store_service,
            callback_manager=None,
            enable_observability=True
        )
        
        # Create tools using orchestrator
        tools = orchestrator.create_tools(
            top_k=top_k,
            use_reranking=use_reranking,
            rerank_top_n=rerank_top_n,
            location_filters=location_filters if detected_location_info else None,
            nrel_client=self.nrel_client,
            location_service=self.location_service,
            reopt_service=self.reopt_service
        )
        
        # Extract tool references for compatibility with existing code
        transportation_tool = next((t for t in tools if t.metadata.name == "transportation_tool"), None)
        utility_tool = next((t for t in tools if t.metadata.name == "utility_tool"), None)
        solar_production_tool = next((t for t in tools if t.metadata.name == "solar_production_tool"), None)
        optimization_tool = next((t for t in tools if t.metadata.name == "optimization_tool"), None)
        
        # Check if we need to fetch and index utility rates BEFORE creating SubQuestionQueryEngine
        # This ensures utility data is available when the tool is called
        is_electricity_cost_question = self._is_electricity_cost_question(question)
        is_charging_station_question = self._is_charging_station_question(question)
        # Also check if question mentions time-of-use rates or charging costs (needs utility tool)
        question_lower = question.lower()
        requires_utility_for_rates = any(keyword in question_lower for keyword in [
            "charging at", "time-of-use", "off-peak", "peak rate", "charging cost", "savings", "compare"
        ]) and not is_electricity_cost_question
        utility_rates_info = None
        
        # Extract zip code from question if not already detected
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
                        print(f"Using zip code from detected location: {location_for_rates}")
                
                # Second priority: zip code from location_to_use (if it's a zip code)
                if not location_for_rates and location_to_use:
                    # Check if location_to_use is a zip code (5 digits)
                    if location_to_use.isdigit() and len(location_to_use) == 5:
                        location_for_rates = location_to_use
                        print(f"Using zip code from location_to_use: {location_for_rates}")
                
                # Third priority: Try to geocode city/state to get zip code
                if not location_for_rates and detected_location_info:
                    city = detected_location_info.get("city")
                    state = detected_location_info.get("state")
                    if city and state:
                        # Try to lookup zip code from city/state first
                        zip_from_city_state = await self.nrel_client._lookup_zip_from_city_state(city, state)
                        if zip_from_city_state:
                            # Use zip code for utility rates (most reliable)
                            location_for_rates = zip_from_city_state
                            print(f"Found zip code {zip_from_city_state} for {city}, {state}")
                        else:
                            # Try to geocode city/state to get coordinates, then use those for utility rates
                            try:
                                # Use NREL client's geocoding to get lat/long
                                lat, lon = await self.nrel_client._geocode_location(f"{city}, {state}")
                                # Use coordinates directly for utility rates API
                                utility_rates_info = await self.nrel_client.get_utility_rates_by_coordinates(
                                    latitude=lat,
                                    longitude=lon,
                                    sector="residential"
                                )
                                # Index utility rates if we got them
                                if utility_rates_info:
                                    if isinstance(utility_rates_info, dict) and utility_rates_info:
                                        if "errors" not in utility_rates_info and "error" not in utility_rates_info:
                                            await self._index_utility_rates(utility_rates_info, f"{city}, {state}")
                                        else:
                                            print(f"Warning: NREL API returned error for utility rates: {utility_rates_info}")
                                            utility_rates_info = None
                                    else:
                                        print(f"Warning: Invalid utility rates data received: {utility_rates_info}")
                                        utility_rates_info = None
                                # Skip the rest of the utility rates fetching logic since we already got it
                                location_for_rates = None  # Set to None to skip the normal flow
                            except Exception as geocode_error:
                                print(f"Warning: Failed to geocode {city}, {state} for utility rates: {str(geocode_error)}")
                                # Fall back to using city/state string (may fail)
                                location_for_rates = f"{city}, {state}"
                                print(f"Warning: Using city/state for geocoding (may fail): {location_for_rates}")
                    elif state:
                        location_for_rates = state
                        print(f"Warning: Using state for geocoding (may fail): {location_for_rates}")
                
                # Final fallback: use location_to_use as-is
                if not location_for_rates:
                    location_for_rates = location_to_use
                
                if location_for_rates:
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
                            else:
                                print(f"Warning: NREL API returned error for utility rates: {utility_rates_info}")
                                utility_rates_info = None
                        else:
                            print(f"Warning: Invalid utility rates data received: {utility_rates_info}")
                            utility_rates_info = None
            except Exception as e:
                # If utility rates fetch fails, continue with query
                print(f"Warning: Failed to fetch utility rates for {location_for_rates}: {str(e)}")
                utility_rates_info = None
        
        # Also try to fetch utility rates if zip code was found in question but not yet fetched
        if not utility_rates_info and zip_from_question:
            try:
                print(f"Attempting to fetch utility rates for zip {zip_from_question} found in question")
                utility_rates_info = await self.nrel_client.get_utility_rates(
                    location=zip_from_question,
                    sector="residential"
                )
                if utility_rates_info and isinstance(utility_rates_info, dict) and utility_rates_info:
                    if "errors" not in utility_rates_info and "error" not in utility_rates_info:
                        await self._index_utility_rates(utility_rates_info, zip_from_question)
                        indexed_zip_code = zip_from_question
                        print(f"Successfully indexed utility rates for zip {zip_from_question}")
                    else:
                        print(f"Warning: NREL API returned error for utility rates: {utility_rates_info}")
            except Exception as e:
                print(f"Warning: Failed to fetch utility rates for zip {zip_from_question}: {str(e)}")
        
        # Update utility retriever filter to use the zip code that was actually indexed
        # This ensures the retriever can find the documents we just indexed
        if indexed_zip_code:
            print(f"Updating utility retriever filter to use indexed zip code: {indexed_zip_code}")
            utility_filter_filters_updated = [
                MetadataFilter(key="domain", value="utility", operator=FilterOperator.EQ),
                MetadataFilter(key="zip", value=indexed_zip_code, operator=FilterOperator.EQ)
            ]
            utility_filter_updated = MetadataFilters(filters=utility_filter_filters_updated)
            utility_retriever = VectorIndexRetriever(
                index=index,
                similarity_top_k=initial_top_k,
                filters=utility_filter_updated
            )
            # Recreate utility query engine with updated retriever (use same response synthesizer)
            utility_query_engine = RetrieverQueryEngine.from_args(
                retriever=utility_retriever,
                llm=llm,
                node_postprocessors=node_postprocessors,
                response_synthesizer=utility_response_synthesizer
            )
            # Recreate utility tool with updated query engine
            utility_tool = QueryEngineTool.from_defaults(
                query_engine=utility_query_engine,
                name="utility_tool",
                description=(
                    "UTILITY DOMAIN: Use this for questions about electricity rates, utility costs, "
                    "electricity prices, utility providers, cost per kWh, price per kWh, residential "
                    "electricity costs, commercial electricity rates, industrial rates, utility bills, "
                    "time-of-use rates, off-peak rates, peak rates, charging costs, and utility company information. "
                    "Use this when the question contains words like 'electricity cost', 'utility cost', "
                    "'electricity rate', 'utility rate', 'electricity price', 'power cost', 'energy cost', "
                    "'kwh cost', 'charging at [time]', 'time-of-use', 'off-peak', or 'peak rate'. "
                    "NOTE: The data source provides flat rates (residential, commercial, industrial) but may not "
                    "include time-of-use rate schedules. If time-of-use rates are requested but not found, "
                    "use the available flat residential rate for calculations. "
                    "DO NOT use this for charging station locations - use transportation_tool for that."
                )
            )
        
        # Now create SubQuestionQueryEngine AFTER utility rates are fetched and indexed
        import sys
        import time as time_module
        sqe_create_start = time_module.time()
        
        # Create SubQuestionQueryEngine using orchestrator
        router_query_engine = orchestrator.create_sub_question_query_engine(tools, use_robust_parser=True)
        
        sqe_create_elapsed = time_module.time() - sqe_create_start
        
        # Use router query engine instead of single query engine
        query_engine = router_query_engine
        
        # Track which tools might be used based on question analysis
        if is_electricity_cost_question or requires_utility_for_rates:
            if "utility_tool" not in tools_used:
                tools_used.append("utility_tool")
        if any(keyword in question.lower() for keyword in ["solar", "solar panel", "solar energy", "solar production", "solar system"]):
            if "solar_production_tool" not in tools_used:
                tools_used.append("solar_production_tool")
        if is_charging_station_question:
            if "transportation_tool" not in tools_used:
                tools_used.append("transportation_tool")
        if any(keyword in question.lower() for keyword in [
            "investment", "sizing", "roi", "optimal size", "optimal system", "npv",
            "net present value", "financial analysis", "economic analysis", "optimal design",
            "cost-benefit", "payback", "optimize", "optimization"
        ]):
            if "optimization_tool" not in tools_used:
                tools_used.append("optimization_tool")
        
        # Add location context if available
        location_context = ""
        if detected_location_info:
            location_type = detected_location_info.get("location_type")
            city = detected_location_info.get("city")
            state = detected_location_info.get("state")
            zip_code = detected_location_info.get("zip_code") or location_to_use
            
            if location_type == "zip_code" and zip_code:
                location_context = f"\n\nIMPORTANT: The user is specifically asking about locations in zip code {zip_code}. Only return results for this zip code area."
            elif location_type == "city_state":
                if city and state:
                    location_context = f"\n\nIMPORTANT: The user is specifically asking about locations in {city}, {state}. Only return results for {city}, {state}. Do not return results for other cities."
                elif state:
                    location_context = f"\n\nIMPORTANT: The user is asking about locations in {state}."
            elif location_type == "state":
                location_context = f"\n\nIMPORTANT: The user is asking about locations in {state}."
        
        # Add instruction to ensure complete answers for complex questions
        completion_instruction = ""
        if "cost" in question.lower() or "compare" in question.lower() or "difference" in question.lower():
            completion_instruction = "\n\nIMPORTANT: Please provide a complete answer with all calculations and comparisons. Do not stop mid-sentence. Include all requested information such as cost comparisons and monthly cost differences."
        
        contextual_question = (
            f"{question}"
            f"{location_context}"
            f"{completion_instruction}"
        )
        
        # Retrieve nodes from both domains for sources
        # Note: RouterQueryEngine doesn't expose nodes directly, so we retrieve them manually
        # Use contextual_question which includes location context
        trans_nodes = []
        util_nodes = []
        try:
            trans_nodes = transportation_retriever.retrieve(contextual_question)
        except Exception as e:
            print(f"Warning: Failed to retrieve transportation nodes: {str(e)}")
            pass
        
        try:
            util_nodes = utility_retriever.retrieve(contextual_question)
        except Exception as e:
            print(f"Warning: Failed to retrieve utility nodes: {str(e)}")
            pass
        
        # Check if we have any data before querying
        if not trans_nodes and not util_nodes:
            return {
                "question": question,
                "answer": "No relevant information found in the indexed data. Please index stations or utility rates first.",
                "sources": [],
                "num_sources": 0
            }
        
        # For electricity cost questions, re-retrieve utility nodes after indexing to ensure they're available
        if is_electricity_cost_question and utility_rates_info:
            try:
                util_nodes = utility_retriever.retrieve(question)
            except Exception:
                pass
        
        # Check if question requires tools that don't use vector store (like solar_production_tool)
        # or requires multiple tools even if we only have nodes from one domain
        requires_solar_tool = any(keyword in question.lower() for keyword in [
            "solar", "solar panel", "solar energy", "solar production", "solar generation",
            "solar savings", "solar offset", "solar payback", "photovoltaic", "pv system"
        ])
        requires_utility_tool = is_electricity_cost_question or any(keyword in question.lower() for keyword in [
            "electricity rate", "utility rate", "cost per kwh", "time-of-use", "off-peak", "peak rate",
            "charging cost", "charging at"
        ])
        
        # If we only have nodes from one domain, skip SubQuestionQueryEngine and use single domain directly
        # UNLESS the question requires solar or utility tools (which don't rely on vector store nodes)
        # This avoids issues with empty responses from one tool causing IndexError
        single_domain_only = (trans_nodes and not util_nodes) or (util_nodes and not trans_nodes)
        # Don't use single domain if we need solar or utility tools
        if requires_solar_tool or requires_utility_tool:
            single_domain_only = False
        
        response = None
        
        if single_domain_only:
            use_reranking = False
            print("Warning: Single domain detected, using single domain query engine directly")
            # Create query engines without reranking to avoid IndexError issues
            # The original query engines may have reranking enabled which can cause problems
            single_domain_postprocessors = []  # No reranking for single domain
            single_domain_transportation_engine = RetrieverQueryEngine.from_args(
                retriever=transportation_retriever,
                llm=llm,
                node_postprocessors=single_domain_postprocessors
            )
            
            single_domain_utility_engine = RetrieverQueryEngine.from_args(
                retriever=utility_retriever,
                llm=llm,
                node_postprocessors=single_domain_postprocessors
            )
            
            # Skip SubQuestionQueryEngine and use appropriate single domain engine
            try:
                if trans_nodes:
                    print("Using transportation query engine (single domain, no reranking)")
                    response = await single_domain_transportation_engine.aquery(contextual_question)
                elif util_nodes:
                    print("Using utility query engine (single domain, no reranking)")
                    response = await single_domain_utility_engine.aquery(contextual_question)
                else:
                    # Should not happen, but handle gracefully
                    raise ValueError("No nodes available for single domain query")
            except Exception as single_domain_error:
                error_type = type(single_domain_error).__name__
                error_msg = str(single_domain_error)
                print(f"Warning: Single domain query engine failed: {error_type}: {error_msg}")
                # Try to generate a basic answer from nodes if query engine fails
                if trans_nodes or util_nodes:
                    print("Attempting to generate basic answer from retrieved nodes...")
                    fallback_nodes = trans_nodes[:top_k] if trans_nodes else util_nodes[:top_k]
                    basic_answer = self._generate_basic_answer_from_nodes(
                        question, fallback_nodes, trans_nodes, util_nodes, is_charging_station_question,
                        is_electricity_cost_question, detected_location_info, utility_rates_info
                    )
                    return {
                        "question": question,
                        "answer": basic_answer,
                        "sources": [
                            {
                                "text": (
                                    (node.text[:200] + "..." if len(node.text) > 200 else node.text)
                                    if hasattr(node, "text") and node.text
                                    else str(node)[:200] + "..." if len(str(node)) > 200 else str(node)
                                ),
                                "metadata": node.metadata if hasattr(node, "metadata") else {}
                            }
                            for node in fallback_nodes
                        ],
                        "num_sources": len(fallback_nodes),
                        "reranked": False
                    }
                # Fall through to error handling below - treat as if SubQuestionQueryEngine failed
                response = None
        
        # Execute query using SubQuestionQueryEngine if single domain query didn't succeed
        # SubQuestionQueryEngine handles both simple single-domain and complex multi-domain questions
        if response is None:
            import sys
            import time as time_module
            import asyncio
            
            # Use SubQuestionQueryEngine (no bypass logic needed - orchestrator handles everything)
            sqe_start_time = time_module.time()
            try:
                response = await asyncio.wait_for(
                    router_query_engine.aquery(contextual_question),
                    timeout=300.0  # 5 minute timeout for LLM + tool calls
                )
                sqe_elapsed = time_module.time() - sqe_start_time
            except asyncio.TimeoutError:
                sqe_elapsed = time_module.time() - sqe_start_time
                print(f"ERROR: SubQuestionQueryEngine.aquery() timed out after {sqe_elapsed:.2f}s (300s limit)", flush=True)
                print(f"ERROR: SubQuestionQueryEngine.aquery() timed out after {sqe_elapsed:.2f}s (300s limit)", file=sys.stderr, flush=True)
                sys.stdout.flush()
                sys.stderr.flush()
                raise ValueError(
                    f"Query timed out after {sqe_elapsed:.2f} seconds. "
                    "Ollama appears to be unresponsive. Please restart Ollama with: sudo systemctl restart ollama"
                )
            except asyncio.CancelledError:
                sqe_elapsed = time_module.time() - sqe_start_time
                print(f"ERROR: SubQuestionQueryEngine.aquery() was cancelled after {sqe_elapsed:.2f}s", flush=True)
                print(f"ERROR: SubQuestionQueryEngine.aquery() was cancelled after {sqe_elapsed:.2f}s", file=sys.stderr, flush=True)
                sys.stdout.flush()
                sys.stderr.flush()
                raise ValueError(
                    f"Query was cancelled after {sqe_elapsed:.2f} seconds. "
                    "Ollama appears to be unresponsive. Please restart Ollama with: sudo systemctl restart ollama"
                )
            except (IndexError, AttributeError, TypeError, ValueError) as e:
                # If SubQuestionQueryEngine fails (e.g., empty responses, invalid sub-questions), fallback to single domain
                error_msg = str(e)
                print(f"Warning: SubQuestionQueryEngine failed with {type(e).__name__}: {error_msg}")
                print(f"Falling back to single domain query engine...")
                
                # Determine which domain to use for fallback
                # Try to use a query engine without reranking if reranking was causing issues
                fallback_success = False
                try:
                    # Create fallback query engines without reranking to avoid processing errors
                    fallback_transportation_engine = RetrieverQueryEngine.from_args(
                        retriever=transportation_retriever,
                        llm=llm,
                        node_postprocessors=[]  # No reranking for fallback
                    )
                    
                    fallback_utility_engine = RetrieverQueryEngine.from_args(
                        retriever=utility_retriever,
                        llm=llm,
                        node_postprocessors=[]  # No reranking for fallback
                    )
                    
                    if is_charging_station_question and trans_nodes:
                        print("Using transportation query engine for fallback (no reranking)")
                        response = await fallback_transportation_engine.aquery(contextual_question)
                        fallback_success = True
                    elif is_electricity_cost_question and util_nodes:
                        print("Using utility query engine for fallback (no reranking)")
                        response = await fallback_utility_engine.aquery(contextual_question)
                        fallback_success = True
                    elif len(trans_nodes) >= len(util_nodes) and trans_nodes:
                        print("Using transportation query engine for fallback (more nodes, no reranking)")
                        response = await fallback_transportation_engine.aquery(contextual_question)
                        fallback_success = True
                    elif util_nodes:
                        print("Using utility query engine for fallback (no reranking)")
                        response = await fallback_utility_engine.aquery(contextual_question)
                        fallback_success = True
                    
                    if not fallback_success:
                        # If no suitable fallback, return a helpful error message
                        return {
                            "question": question,
                            "answer": (
                                "I encountered an error processing your question. "
                                "This might be because the question doesn't match the available data domains "
                                "(transportation/EV charging or utility rates). "
                                "Please try rephrasing your question or ensure relevant data is indexed."
                            ),
                            "sources": [],
                            "num_sources": 0
                        }
                except Exception as fallback_error:
                            error_type = type(fallback_error).__name__
                            error_msg = str(fallback_error)
                            print(f"Warning: Fallback query engine also failed: {error_type}: {error_msg}")
                            
                            # Provide specific message for timeout errors
                            if "timeout" in error_msg.lower() or "ConnectTimeout" in error_type or "Timeout" in error_type:
                                return {
                                    "question": question,
                                    "answer": (
                                        "The query timed out. This might be due to network issues or the LLM service being slow. "
                                        "Some sub-questions may have returned empty responses. "
                                        "Please try again with a simpler question or check your network connection."
                                    ),
                                    "sources": [],
                                    "num_sources": 0
                                }
                            
                            # For ValueError related to int conversion, try to return a basic answer from retrieved nodes
                            if "invalid literal for int()" in error_msg or "ValueError" in error_type:
                                print("Warning: Detected int conversion error, attempting to return basic answer from nodes")
                                # Try to generate a basic answer from the retrieved nodes
                                if trans_nodes or util_nodes:
                                    fallback_nodes = trans_nodes[:top_k] if trans_nodes else util_nodes[:top_k]
                                    basic_answer = self._generate_basic_answer_from_nodes(
                                        question, fallback_nodes, trans_nodes, util_nodes, is_charging_station_question, 
                                        is_electricity_cost_question, detected_location_info, utility_rates_info
                                    )
                                    return {
                                        "question": question,
                                        "answer": basic_answer,
                                        "sources": [
                                            {
                                                "text": (
                                                    (node.text[:200] + "..." if len(node.text) > 200 else node.text)
                                                    if hasattr(node, "text") and node.text
                                                    else str(node)[:200] + "..." if len(str(node)) > 200 else str(node)
                                                ),
                                                "metadata": node.metadata if hasattr(node, "metadata") else {}
                                            }
                                            for node in fallback_nodes
                                        ],
                                        "num_sources": len(fallback_nodes),
                                        "reranked": False
                                    }
                            
                            # Return a helpful error message instead of raising
                            return {
                                "question": question,
                                "answer": (
                                    "I encountered an error processing your complex question. "
                                    "Some sub-questions may have returned empty responses, or there was a processing error. "
                                    "Please try asking a simpler question or ensure relevant data is indexed."
                                ),
                                "sources": [],
                                "num_sources": 0
                            }
            except Exception as e:
                # For other exceptions (like ConnectTimeout), log and return error message
                error_type = type(e).__name__
                error_msg = str(e)
                response_time_ms = (time.time() - query_start_time) * 1000
                
                self.logger.log_error(
                    error_type=error_type,
                    error_message=error_msg,
                    context={
                        "question": question,
                        "tools_used": tools_used,
                        "response_time_ms": response_time_ms
                    }
                )
                
                # Provide specific message for timeout errors
                if "timeout" in error_msg.lower() or "ConnectTimeout" in error_type or "Timeout" in error_type:
                    self.logger.log_query(
                        question=question,
                        tools_used=tools_used,
                        response_time_ms=response_time_ms,
                        success=False,
                        error="Timeout",
                        zip_code=zip_code
                    )
                    return {
                        "question": question,
                        "answer": (
                            "The query timed out. This might be due to network issues or the LLM service being slow. "
                            "Please try again with a simpler question or check your network connection."
                        ),
                        "sources": [],
                        "num_sources": 0
                    }
                
                self.logger.log_query(
                    question=question,
                    tools_used=tools_used,
                    response_time_ms=response_time_ms,
                    success=False,
                    error=error_msg,
                    zip_code=zip_code
                )
                return {
                    "question": question,
                    "answer": (
                        f"I encountered an error: {error_msg}. "
                        "Please try rephrasing your question."
                    ),
                    "sources": [],
                    "num_sources": 0
                }
        
        # Determine which nodes to use for sources
        # Try to get source nodes from the response first (SubQuestionQueryEngine provides these)
        final_nodes = []
        try:
            if hasattr(response, "source_nodes") and response.source_nodes:
                # Filter out constructed nodes that contain sub-question text
                # SubQuestionQueryEngine creates nodes with "Sub question:" prefix
                actual_source_nodes = []
                for node in response.source_nodes:
                    # Skip nodes that are sub-question/answer pairs (constructed nodes)
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
                    except Exception:
                        node_text = str(node) if node else ""
                    
                    # Check if this is a constructed sub-question node
                    # SubQuestionQueryEngine formats these as "Sub question: ...\nResponse: ..."
                    if node_text:
                        node_text_lower = node_text.lower()
                        if ("sub question:" in node_text_lower or 
                            "sub_question" in node_text_lower or
                            node_text.startswith("Sub question:")):
                            # This is a constructed node, skip it
                            continue
                    
                    # Also check metadata to see if it's a constructed node
                    if hasattr(node, "metadata"):
                        metadata = node.metadata or {}
                        if isinstance(metadata, dict):
                            # Constructed nodes might have specific metadata patterns
                            # Skip if it looks like a sub-question node
                            if any(key in str(metadata).lower() for key in ["sub_question", "subquestion"]):
                                continue
                    
                    # This appears to be an actual source node
                    actual_source_nodes.append(node)
                
                # Use filtered actual source nodes
                if actual_source_nodes:
                    final_nodes = actual_source_nodes[:top_k]
                # If all nodes were filtered out, final_nodes will remain empty
                # and we'll use the fallback to manually retrieved nodes below
        except (IndexError, AttributeError, TypeError) as e:
            print(f"Warning: Could not access response.source_nodes: {str(e)}")
        
        # Fallback to manually retrieved nodes if response doesn't have source_nodes
        if not final_nodes:
            # For charging station questions, prioritize transportation nodes
            if is_charging_station_question and trans_nodes:
                final_nodes = trans_nodes[:top_k]
            # For electricity cost questions, prioritize utility nodes
            elif is_electricity_cost_question and util_nodes:
                final_nodes = util_nodes[:top_k]
            elif len(trans_nodes) >= len(util_nodes) and trans_nodes:
                final_nodes = trans_nodes[:top_k]
            elif util_nodes:
                final_nodes = util_nodes[:top_k]
        
        # Extract answer text from LlamaIndex Response object
        # LlamaIndex Response objects typically have a .response property that contains the text
        answer_text = ""
        try:
            # Try the standard LlamaIndex Response API first
            if hasattr(response, "response"):
                try:
                    resp_value = response.response
                    # response.response can be a string, list, or another Response object
                    if isinstance(resp_value, str):
                        answer_text = resp_value
                    elif isinstance(resp_value, list):
                        # If it's a list, safely get the first element
                        if len(resp_value) > 0:
                            first_item = resp_value[0]
                            answer_text = first_item if isinstance(first_item, str) else str(first_item)
                    elif resp_value is not None:
                        if hasattr(resp_value, "response"):
                            # Nested response object - safely access
                            try:
                                nested_resp = resp_value.response
                                answer_text = nested_resp if isinstance(nested_resp, str) else str(nested_resp)
                            except (IndexError, AttributeError, TypeError) as e:
                                # If accessing nested response fails, try other methods
                                pass
                        if not answer_text and hasattr(resp_value, "text"):
                            answer_text = resp_value.text if resp_value.text is not None else ""
                        if not answer_text:
                            # Try string conversion, but catch any errors
                            try:
                                answer_text = str(resp_value) if resp_value is not None else ""
                            except (IndexError, AttributeError, TypeError):
                                answer_text = ""
                except (IndexError, AttributeError, TypeError) as e:
                    # If accessing response.response fails, continue to next method
                    print(f"Warning: Error accessing response.response: {str(e)}")
                    pass
            
            # Fallback to .text attribute
            if not answer_text and hasattr(response, "text"):
                text_value = response.text
                if isinstance(text_value, str):
                    answer_text = text_value
                elif text_value is not None:
                    try:
                        answer_text = str(text_value)
                    except Exception:
                        answer_text = ""
            
            # Fallback to get_response() method
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
                except Exception:
                    pass
            
            # Final fallback: string conversion
            if not answer_text:
                try:
                    answer_text = str(response) if response is not None else ""
                except Exception:
                    answer_text = ""
                    
        except Exception as e:
            # If all extraction methods fail, use empty string
            print(f"Warning: Failed to extract answer text from response: {str(e)}")
            answer_text = ""
        
        # Clean up the answer text - ensure it's a string and not None
        if answer_text:
            if isinstance(answer_text, str):
                answer_text = answer_text.strip()
            else:
                try:
                    answer_text = str(answer_text).strip()
                except Exception:
                    answer_text = ""
            
            # Remove redundant "Response:" prefixes (e.g., "Response 1:", "Response:", etc.)
            if isinstance(answer_text, str):
                # Remove patterns like "Response 1:", "Response 2:", "Response:", etc.
                answer_text = re.sub(r'^Response\s*\d*:\s*', '', answer_text, flags=re.IGNORECASE)
                answer_text = answer_text.strip()
        else:
            answer_text = ""
        
        # If answer is still empty but we have nodes, generate a basic answer from the nodes
        if not answer_text and final_nodes:
            answer_text = self._generate_basic_answer_from_nodes(
                question, final_nodes, trans_nodes, util_nodes, is_charging_station_question,
                is_electricity_cost_question, detected_location_info, utility_rates_info
            )
        
        # Build response with location detection info
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
        
        # Add location detection info if location was extracted from question
        if detected_location_info:
            response_data["detected_location"] = {
                "type": detected_location_info.get("location_type"),
                "zip_code": detected_location_info.get("zip_code"),
                "city": detected_location_info.get("city"),
                "state": detected_location_info.get("state")
            }
        
        # Add utility rates info if available
        if utility_rates_info:
            response_data["utility_rates"] = utility_rates_info
        
        # Log query completion
        response_time_ms = (time.time() - query_start_time) * 1000
        self.logger.log_query(
            question=question,
            tools_used=tools_used,
            response_time_ms=response_time_ms,
            success=True,
            num_sources=len(final_nodes),
            zip_code=zip_code or detected_location_info.get("zip_code") if detected_location_info else None
        )
        
        return response_data
    
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
            
            # Bulk insert documents for better performance
            indexed_count = 0
            failed_count = 0
            try:
                # Bulk insert all documents at once
                index.insert(documents)
                indexed_count = len(documents)
                print(f"Successfully bulk indexed {indexed_count} utility rate documents for location {location}")
            except Exception as e:
                # If bulk insert fails, fall back to individual inserts for error handling
                print(f"Warning: Bulk insert failed, falling back to individual inserts: {str(e)}")
                for doc in documents:
                    try:
                        index.insert(doc)
                        indexed_count += 1
                    except Exception as doc_error:
                        failed_count += 1
                        print(f"Warning: Failed to insert utility rate document {doc.id_}: {str(doc_error)}")
                        if failed_count <= 3:  # Print first few errors
                            import traceback
                            traceback.print_exc()
                
                if failed_count > 0:
                    print(f"Warning: {failed_count} out of {len(documents)} utility rate documents failed to index")
                else:
                    print(f"Successfully indexed {indexed_count} utility rate documents for location {location}")
        except Exception as e:
            # Don't fail silently - log the error
            print(f"Error indexing utility rates: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def _generate_basic_answer_from_nodes(
        self,
        question: str,
        final_nodes: List[Any],
        trans_nodes: List[Any],
        util_nodes: List[Any],
        is_charging_station_question: bool,
        is_electricity_cost_question: bool,
        detected_location_info: Optional[Dict[str, Any]],
        utility_rates_info: Optional[Dict[str, Any]]
    ) -> str:
        """
        Generate a basic answer from retrieved nodes when LLM response fails.
        
        Args:
            question: Original question
            final_nodes: Nodes to use for answer generation
            trans_nodes: Transportation nodes
            util_nodes: Utility nodes
            is_charging_station_question: Whether question is about charging stations
            is_electricity_cost_question: Whether question is about electricity costs
            detected_location_info: Detected location information
            utility_rates_info: Utility rates information if available
            
        Returns:
            Basic answer string
        """
        if is_charging_station_question:
            station_count = len(final_nodes)
            location_str = ""
            if detected_location_info:
                city = detected_location_info.get("city")
                state = detected_location_info.get("state")
                zip_code = detected_location_info.get("zip_code")
                if city and state:
                    location_str = f" in {city}, {state}"
                elif zip_code:
                    location_str = f" in zip code {zip_code}"
                elif state:
                    location_str = f" in {state}"
            
            if station_count > 0:
                return f"I found {station_count} charging station(s){location_str}. See the sources below for details."
            else:
                return f"No charging stations found{location_str}. Please try a different location."
        elif is_electricity_cost_question:
            if utility_rates_info:
                utility_name = utility_rates_info.get("utility_name", "the utility")
                location_str = utility_rates_info.get("location", "")
                return f"Electricity rates for {location_str} are provided by {utility_name}. See the sources below for detailed rate information."
            elif len(final_nodes) > 0:
                return f"I found utility rate information. See the sources below for details."
            else:
                return "No utility rate information found for this location."
        else:
            return f"I found {len(final_nodes)} relevant result(s). See the sources below for details."
    
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
            "electricity bill", "utility bill"
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
            
            # Bulk insert documents for better performance
            try:
                # Bulk insert entire batch at once
                index.insert(documents)
                indexed_count += len(documents)
            except Exception as e:
                # If bulk insert fails, fall back to individual inserts for error handling
                print(f"Warning: Bulk insert failed for batch, falling back to individual inserts: {str(e)}")
                for doc in documents:
                    try:
                        index.insert(doc)
                        indexed_count += 1
                    except Exception:
                        # Skip duplicates or errors
                        skipped_count += 1
        
        return {
            "state": state,
            "stations_fetched": total_stations,
            "stations_indexed": indexed_count,
            "skipped": skipped_count,
            "message": f"Successfully indexed {indexed_count} stations for {state}"
        }
    
    async def query_with_existing_data(
        self,
        question: str,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """
        Query using only existing indexed data (no new fetch).
        """
        return await self.query(question=question, zip_code=None, top_k=top_k)


