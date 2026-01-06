"""
Utility Bundle: Electricity rates, utility costs, and tariff information.

This bundle provides:
- Electricity rate queries
- Utility cost information
- Time-of-use rate schedules
- Utility provider information
"""

from typing import Optional, List
import re
from llama_index.core.tools import QueryEngineTool
from llama_index.core.query_engine import RetrieverQueryEngine, BaseQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.callbacks import CallbackManager
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.response_synthesizers.type import ResponseMode
from llama_index.core.prompts import PromptTemplate
from llama_index.core.base.response.schema import Response
from llama_index.core.schema import QueryBundle, TextNode, NodeWithScore
from app.services.vector_store_service import VectorStoreService
from app.services.urdb_service import URDBService
from app.services.nrel_client import NRELClient


def get_tool(
    llm,
    vector_store_service: VectorStoreService,
    callback_manager: Optional[CallbackManager] = None,
    top_k: int = 5,
    use_reranking: bool = False,
    rerank_top_n: int = 3,
    location_filters: Optional[List[MetadataFilter]] = None
) -> QueryEngineTool:
    """
    Get the utility tool as a QueryEngineTool.
    
    This tool provides electricity rate and utility cost queries
    using the vector store index.
    
    Args:
        llm: LLM instance for query processing
        vector_store_service: Vector store service for retrieving utility rates
        callback_manager: Optional callback manager for observability
        top_k: Number of top results to retrieve
        use_reranking: Whether to use LLM reranking
        rerank_top_n: Number of results to rerank if reranking is enabled
        location_filters: Optional location-based metadata filters
        
    Returns:
        QueryEngineTool configured for utility/electricity rate queries
    """
    # Get vector store index
    index = vector_store_service.get_index()
    
    # Build utility domain filter
    utility_filter_filters = [
        MetadataFilter(key="domain", value="utility", operator=FilterOperator.EQ)
    ]
    
    # Add location filters if provided
    # Note: Utility rates use "zip" metadata, not "queried_zip", "state", or "city"
    # Utility nodes only have "zip" metadata, so we ignore state/city filters
    skipped_filters = []
    if location_filters:
        for filter_obj in location_filters:
            # If filter uses queried_zip, convert to zip (utility rates use zip)
            if hasattr(filter_obj, 'key') and filter_obj.key == 'queried_zip':
                utility_filter_filters.append(
                    MetadataFilter(key="zip", value=filter_obj.value, operator=filter_obj.operator)
                )
            elif hasattr(filter_obj, 'key') and filter_obj.key == 'zip':
                # Keep zip filters as-is
                utility_filter_filters.append(filter_obj)
            elif hasattr(filter_obj, 'key') and filter_obj.key in ['state', 'city']:
                # Skip state and city filters - utility nodes don't have these metadata fields
                # They only have "zip" metadata, so filtering by state/city won't work
                skipped_filters.append(filter_obj.key)
    
    if skipped_filters:
        print(f"[UtilityTool] Skipping {', '.join(skipped_filters)} filter(s) - utility nodes only have 'zip' metadata")
    
    utility_filter = MetadataFilters(filters=utility_filter_filters)
    
    # Create retriever
    initial_top_k = top_k * 2 if use_reranking else top_k
    utility_retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=initial_top_k,
        filters=utility_filter
    )
    
    # Create node postprocessors (reranking if enabled)
    node_postprocessors = []
    if use_reranking:
        try:
            reranker = LLMRerank(
                llm=llm,
                top_n=rerank_top_n
            )
            node_postprocessors.append(reranker)
        except Exception as e:
            print(f"Warning: Failed to create reranker for utility tool: {str(e)}")
    
    # Create custom response synthesizer to prevent safety filter issues
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
            "IMPORTANT: Only respond with 'I do not have utility rate data available for this location. "
            "The data may not be available in the database, or the location may need to be indexed first.' "
            "if the context above is COMPLETELY EMPTY (no text, no data, just whitespace). "
            "If the context contains ANY utility rate data (even if it's for different locations than requested), "
            "you MUST provide that information. Always use the actual data from the context.\n"
            "For comparison questions (e.g., 'which state has the cheapest rate', 'compare rates across states'), "
            "you MUST analyze ALL the utility rate data provided in the context, extract rates from different locations, "
            "group them by state if possible, and identify which state/location has the cheapest/most expensive rate. "
            "If the data includes zip codes, you may need to infer states from zip codes or use the location information "
            "provided in the metadata. Provide a clear answer with the state/location name and the rate.\n"
            "For other questions, you can aggregate data from multiple locations or provide examples from the available data.\n"
            "Query: {query_str}\n"
            "Answer: "
        )
    )
    
    # Create query engine
    base_query_engine = RetrieverQueryEngine.from_args(
        retriever=utility_retriever,
        llm=llm,
        node_postprocessors=node_postprocessors,
        response_synthesizer=utility_response_synthesizer,
        callback_manager=callback_manager
    )
    
    # Initialize URDB service and NREL client for fallback fetching
    urdb_service = URDBService(llm_mode="local")
    nrel_client = NRELClient()
    
    # Wrap query engine to add debug logging and URDB fallback
    class UtilityQueryEngineWrapper(BaseQueryEngine):
        """Wrapper to add debug logging and URDB API fallback for utility query engine."""
        
        def __init__(self, base_engine, retriever, urdb_service, nrel_client, vector_store_service, callback_manager=None):
            super().__init__(callback_manager=callback_manager)
            self.base_engine = base_engine
            self.retriever = retriever
            self.urdb_service = urdb_service
            self.nrel_client = nrel_client
            self.vector_store_service = vector_store_service
        
        def _get_prompt_modules(self):
            """Get prompt sub-modules. Returns empty dict since we delegate to base engine."""
            return {}
        
        def _query(self, query_bundle: QueryBundle) -> Response:
            """Synchronous query - delegate to base engine with debugging."""
            query_str = query_bundle.query_str
            
            # Check retriever
            try:
                nodes = self.retriever.retrieve(query_str)
                node_count = len(nodes) if nodes else 0
                if node_count > 0:
                    print(f"[UtilityTool] query='{query_str[:60]}...' | nodes={node_count}")
            except Exception as e:
                print(f"[UtilityTool] ERROR retrieving nodes: {str(e)}")
            
            # Delegate to base engine
            response = self.base_engine._query(query_bundle)
            
            # Check if response is actually empty
            response_text = ""
            if hasattr(response, "response"):
                response_text = str(response.response) if response.response else ""
            elif hasattr(response, "text"):
                response_text = response.text if response.text else ""
            
            if not response_text or response_text.strip() == "" or response_text.strip() == "Empty Response":
                print(f"[UtilityTool] empty_response | query='{query_str[:60]}...'")
                helpful_response = Response(
                    response="I do not have utility rate data available for this location. The data may not be available in the database, or the location may need to be indexed first.",
                    source_nodes=response.source_nodes if hasattr(response, 'source_nodes') else [],
                    metadata=response.metadata if hasattr(response, 'metadata') else {}
                )
                return helpful_response
            
            return response
        
        def _extract_location_from_query(self, query_str: str) -> Optional[str]:
            """Extract location (zip code or city, state) from query string."""
            # Try to extract zip code (5 digits)
            zip_match = re.search(r'\b\d{5}\b', query_str)
            if zip_match:
                return zip_match.group(0)
            
            # Try to extract city, state pattern (e.g., "Atlanta, Georgia" or "Denver, CO")
            city_state_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z]{2}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', query_str)
            if city_state_match:
                return f"{city_state_match.group(1)}, {city_state_match.group(2)}"
            
            return None
        
        async def _check_location_match(self, queried_location: Optional[str], nodes: List) -> bool:
            """Check if any returned nodes match the queried location."""
            if not queried_location or not nodes:
                return False
            
            # Get zip code for queried location
            queried_zip = None
            if queried_location.isdigit() and len(queried_location) == 5:
                queried_zip = queried_location
            else:
                # Try to geocode city/state to zip code
                try:
                    if ", " in queried_location:
                        city, state = queried_location.split(", ", 1)
                        queried_zip = await self.nrel_client._get_zip_from_city_state(city, state)
                    else:
                        # Try full geocoding
                        lat, lon = await self.nrel_client._geocode_location(queried_location)
                        # For now, we can't reverse geocode lat/lon to zip easily
                        # So we'll be more lenient - if we can't geocode, assume match
                        # This prevents false negatives
                        return True  # Assume match if we can't verify
                except Exception:
                    # If geocoding fails, be lenient - assume match
                    # This prevents false negatives when geocoding is unavailable
                    return True
            
            if not queried_zip:
                return True  # Can't verify, assume match
            
            # Check if any node has matching zip
            for node in nodes:
                if hasattr(node, 'metadata'):
                    node_zip = node.metadata.get('zip', '')
                    if node_zip == queried_zip:
                        return True
            
            return False
        
        async def _fetch_rates_from_urdb(self, location: str) -> Optional[str]:
            """Fetch utility rates from URDB API for a given location."""
            try:
                from app.services.document_service import DocumentService
                document_service = DocumentService()
                
                # Extract zip code from location
                zip_code = None
                if location.isdigit() and len(location) == 5:
                    zip_code = location
                else:
                    # Try to geocode city/state to zip code
                    try:
                        if ", " in location:
                            city, state = location.split(", ", 1)
                            zip_code = await self.nrel_client._get_zip_from_city_state(city, state)
                        else:
                            # Try geocoding to lat/lon, then to zip
                            lat, lon = await self.nrel_client._geocode_location(location)
                            # For now, we need zip code - could enhance URDBService to accept lat/lon
                            # But for simplicity, let's try to reverse geocode to zip
                            # This is a limitation - we'd need to add reverse geocoding
                            pass
                    except Exception as e:
                        print(f"[UtilityTool] ERROR geocoding location: {str(e)}")
                        pass
                
                if not zip_code:
                    print(f"[UtilityTool] Could not determine zip code for location: {location}")
                    return None
                
                # Fetch rates for residential sector first (most common query)
                rates = await self.urdb_service.fetch_urdb_by_zip(zip_code, sector="residential", limit=5)
                if not rates or len(rates) == 0:
                    # Try commercial if residential fails
                    rates = await self.urdb_service.fetch_urdb_by_zip(zip_code, sector="commercial", limit=5)
                
                if not rates or len(rates) == 0:
                    return None
                
                # Use document_service to convert URDB data to documents (same format as vector store)
                # This ensures consistency in how rates are extracted and formatted
                documents = document_service.utility_rates_to_documents(rates[0], location=zip_code)
                
                if not documents or len(documents) == 0:
                    return None
                
                # Index the fetched documents to vector store for future queries
                try:
                    index = self.vector_store_service.get_index()
                    index.insert(documents)
                    print(f"[UtilityTool] indexed_urdb_data | zip={zip_code} | documents={len(documents)}")
                except Exception as index_error:
                    # Don't fail the query if indexing fails - just log it
                    print(f"[UtilityTool] WARNING indexing_failed | zip={zip_code} | error={str(index_error)[:100]}")
                
                # Extract formatted text and metadata from the document
                doc = documents[0]
                formatted_text = doc.text if hasattr(doc, 'text') else str(doc)
                metadata = doc.metadata if hasattr(doc, 'metadata') else {}
                
                # Build response similar to vector store format
                utility_name = metadata.get('utility_name', 'Unknown')
                residential_rate = metadata.get('residential_rate')
                commercial_rate = metadata.get('commercial_rate')
                industrial_rate = metadata.get('industrial_rate')
                
                info_parts = [f"Utility: {utility_name}", f"Location: {zip_code}"]
                if residential_rate is not None:
                    try:
                        rate_val = float(residential_rate)
                        info_parts.append(f"Residential Rate: ${rate_val:.4f}/kWh")
                    except (ValueError, TypeError):
                        info_parts.append(f"Residential Rate: ${residential_rate}/kWh")
                if commercial_rate is not None:
                    try:
                        rate_val = float(commercial_rate)
                        info_parts.append(f"Commercial Rate: ${rate_val:.4f}/kWh")
                    except (ValueError, TypeError):
                        info_parts.append(f"Commercial Rate: ${commercial_rate}/kWh")
                if industrial_rate is not None:
                    try:
                        rate_val = float(industrial_rate)
                        info_parts.append(f"Industrial Rate: ${rate_val:.4f}/kWh")
                    except (ValueError, TypeError):
                        info_parts.append(f"Industrial Rate: ${industrial_rate}/kWh")
                
                if len(info_parts) > 2:  # More than just utility and location
                    return "Current electricity rates:\n" + " | ".join(info_parts)
                
                # Fallback to formatted text from document
                return formatted_text
                
            except Exception as e:
                print(f"[UtilityTool] ERROR fetching from URDB: {str(e)}")
                import traceback
                traceback.print_exc()
                return None
        
        async def _aquery(self, query_bundle: QueryBundle) -> Response:
            """Async query with observability and URDB fallback."""
            query_str = query_bundle.query_str
            
            # Extract location from query
            queried_location = self._extract_location_from_query(query_str)
            
            # Check if this is a comparison question
            query_lower = query_str.lower()
            is_comparison_question = any(keyword in query_lower for keyword in [
                "which state", "which city", "cheapest", "cheaper", "most affordable", 
                "lowest", "highest", "compare", "comparison", "best rate", "worst rate"
            ])
            
            # Check what nodes the retriever finds
            nodes = None
            try:
                nodes = self.retriever.retrieve(query_str)
                node_count = len(nodes) if nodes else 0
                
                if node_count > 0:
                    # Show key metadata from first node
                    first_node = nodes[0]
                    metadata = first_node.metadata if hasattr(first_node, "metadata") else {}
                    zip_code = metadata.get('zip', 'N/A')
                    utility_name = metadata.get('utility_name', 'N/A')
                    print(f"[UtilityTool] query='{query_str[:50]}...' | nodes={node_count} | zip={zip_code} | utility={utility_name[:30]}")
                    
                    # Check if queried location matches returned nodes
                    if queried_location and not is_comparison_question:
                        location_matches = await self._check_location_match(queried_location, nodes)
                        if not location_matches:
                            print(f"[UtilityTool] location_mismatch | queried={queried_location} | found_zip={zip_code} | fetching_from_urdb")
                            # Try fetching from URDB API
                            urdb_response = await self._fetch_rates_from_urdb(queried_location)
                            if urdb_response:
                                node = TextNode(text=urdb_response)
                                node_with_score = NodeWithScore(node=node, score=1.0)
                                return Response(
                                    response=urdb_response,
                                    source_nodes=[node_with_score]
                                )
                else:
                    print(f"[UtilityTool] query='{query_str[:50]}...' | nodes=0 | checking_unfiltered")
                    # Try without filters to see if there are any utility rates at all
                    try:
                        unfiltered_retriever = VectorIndexRetriever(
                            index=self.retriever._index if hasattr(self.retriever, '_index') else None,
                            similarity_top_k=50 if is_comparison_question else 5,
                            filters=MetadataFilters(filters=[
                                MetadataFilter(key="domain", value="utility", operator=FilterOperator.EQ)
                            ])
                        )
                        all_nodes = unfiltered_retriever.retrieve("electricity rate")
                        unfiltered_count = len(all_nodes) if all_nodes else 0
                        
                        if unfiltered_count > 0:
                            print(f"[UtilityTool] unfiltered_nodes={unfiltered_count} | comparison={is_comparison_question}")
                            # If this is a comparison question, use unfiltered retriever
                            if is_comparison_question:
                                self.retriever = unfiltered_retriever
                                if hasattr(self.base_engine, 'retriever'):
                                    self.base_engine.retriever = unfiltered_retriever
                                nodes = all_nodes
                    except Exception as e2:
                        print(f"[UtilityTool] ERROR checking unfiltered: {str(e2)}")
            except Exception as e:
                print(f"[UtilityTool] ERROR retrieving nodes: {str(e)}")
                import traceback
                traceback.print_exc()
            
            # For comparison questions, try unfiltered retriever if no nodes found
            if (not nodes or len(nodes) == 0) and is_comparison_question:
                try:
                    unfiltered_retriever = VectorIndexRetriever(
                        index=self.retriever._index if hasattr(self.retriever, '_index') else None,
                        similarity_top_k=50,
                        filters=MetadataFilters(filters=[
                            MetadataFilter(key="domain", value="utility", operator=FilterOperator.EQ)
                        ])
                    )
                    nodes = unfiltered_retriever.retrieve(query_str)
                    if nodes and len(nodes) > 0:
                        print(f"[UtilityTool] comparison_fallback | nodes={len(nodes)}")
                        self.retriever = unfiltered_retriever
                        if hasattr(self.base_engine, 'retriever'):
                            self.base_engine.retriever = unfiltered_retriever
                except Exception as e2:
                    print(f"[UtilityTool] ERROR unfiltered_retriever: {str(e2)}")
            
            # Execute query
            try:
                response = await self.base_engine._aquery(query_bundle)
                
                # Check if we have nodes but LLM returned empty/unhelpful response
                has_source_nodes = hasattr(response, 'source_nodes') and response.source_nodes and len(response.source_nodes) > 0
                response_text = ""
                if hasattr(response, "response"):
                    response_text = str(response.response) if response.response else ""
                elif hasattr(response, "text"):
                    response_text = response.text if response.text else ""
                
                # If we have source nodes but response says "I do not have", extract data from nodes instead
                if has_source_nodes and response_text and "I do not have utility rate data" in response_text:
                    print(f"[UtilityTool] llm_fallback | source_nodes={len(response.source_nodes)} | extracting_from_metadata")
                    # Extract utility rate data from source nodes
                    utility_info = []
                    for node in response.source_nodes:
                        if hasattr(node, 'metadata'):
                            meta = node.metadata
                            utility_name = meta.get('utility_name', 'Unknown')
                            zip_code = meta.get('zip', meta.get('location', 'Unknown'))
                            residential_rate = meta.get('residential_rate', None)
                            commercial_rate = meta.get('commercial_rate', None)
                            industrial_rate = meta.get('industrial_rate', None)
                            
                            info_parts = [f"Utility: {utility_name}", f"Location: {zip_code}"]
                            if residential_rate is not None:
                                info_parts.append(f"Residential Rate: ${residential_rate:.4f}/kWh")
                            if commercial_rate is not None:
                                info_parts.append(f"Commercial Rate: ${commercial_rate:.4f}/kWh")
                            if industrial_rate is not None:
                                info_parts.append(f"Industrial Rate: ${industrial_rate:.4f}/kWh")
                            
                            utility_info.append(" | ".join(info_parts))
                    
                    if utility_info:
                        extracted_response = "Current electricity rates:\n" + "\n".join(utility_info)
                        return Response(
                            response=extracted_response,
                            source_nodes=response.source_nodes,
                            metadata=response.metadata if hasattr(response, 'metadata') else {}
                        )
                
                # Check if response is actually empty
                if not response_text or response_text.strip() == "" or response_text.strip() == "Empty Response":
                    if not has_source_nodes:
                        print(f"[UtilityTool] empty_response | no_source_nodes")
                        # Try fetching from URDB API as fallback
                        if queried_location and not is_comparison_question:
                            print(f"[UtilityTool] attempting_urdb_fallback | location={queried_location}")
                            urdb_response = await self._fetch_rates_from_urdb(queried_location)
                            if urdb_response:
                                node = TextNode(text=urdb_response)
                                node_with_score = NodeWithScore(node=node, score=1.0)
                                return Response(
                                    response=urdb_response,
                                    source_nodes=[node_with_score]
                                )
                        
                        helpful_response = Response(
                            response="I do not have utility rate data available for this location. The data may not be available in the database, or the location may need to be indexed first.",
                            source_nodes=[],
                            metadata=response.metadata if hasattr(response, 'metadata') else {}
                        )
                        return helpful_response
                
                return response
                
            except Exception as e:
                print(f"[UtilityTool] ERROR query: {str(e)}")
                import traceback
                traceback.print_exc()
                raise e
    
    # Wrap the query engine
    wrapped_engine = UtilityQueryEngineWrapper(
        base_query_engine,
        utility_retriever,
        urdb_service,
        nrel_client,
        vector_store_service,
        callback_manager=callback_manager
    )
    
    # Create tool with high-quality metadata
    tool = QueryEngineTool.from_defaults(
        query_engine=wrapped_engine,
        name="utility_tool",
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
    
    return tool

