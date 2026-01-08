"""
Buildings Bundle: Building energy efficiency, codes, and standards.

This bundle provides:
- Building energy code queries
- Energy efficiency standards and requirements
- Building performance data
- Code compliance information
- Building energy modeling information

Data Sources:
- NREL Building Component Library (BCL): https://bcl.nrel.gov/
  - OpenStudio Measures (schema: https://bcl.nrel.gov/static/assets/json/measure_schema.json)
  - Building Components (schema: https://bcl.nrel.gov/static/assets/json/component_schema.json)
  
The Buildings bundle queries vector store documents indexed with domain="buildings" metadata.
These documents typically contain BCL measures and components related to building codes,
energy efficiency standards, and compliance requirements.
"""

from typing import Optional, List
import re
from llama_index.core.tools import QueryEngineTool
from llama_index.core.query_engine import RetrieverQueryEngine, BaseQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.callbacks import CallbackManager
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
from llama_index.core.base.response.schema import Response
from llama_index.core.schema import QueryBundle, TextNode, NodeWithScore
from app.services.vector_store_service import VectorStoreService
from app.services.bcl_client import BCLClient
from app.services.freshness_checker import FreshnessChecker


def get_tool(
    llm,
    vector_store_service: VectorStoreService,
    callback_manager: Optional[CallbackManager] = None,
    top_k: int = 5,
    use_reranking: bool = False,
    rerank_top_n: int = 3,
    location_filters: Optional[List[MetadataFilter]] = None,
    bcl_client: Optional[BCLClient] = None
) -> QueryEngineTool:
    """
    Get the buildings tool as a QueryEngineTool.
    
    This tool provides building energy code, efficiency standards, and compliance queries
    using the vector store index with BCL API fallback.
    
    Args:
        llm: LLM instance for query processing
        vector_store_service: Vector store service for retrieving building data
        callback_manager: Optional callback manager for observability
        top_k: Number of top results to retrieve
        use_reranking: Whether to use LLM reranking
        rerank_top_n: Number of results to rerank if reranking is enabled
        location_filters: Optional location-based metadata filters
        bcl_client: Optional BCL client for API fallback (creates new if not provided)
        
    Returns:
        QueryEngineTool configured for buildings/energy code queries
    """
    # Get vector store index
    index = vector_store_service.get_index()
    
    # Build buildings domain filter
    buildings_filter_filters = [
        MetadataFilter(key="domain", value="buildings", operator=FilterOperator.EQ)
    ]
    
    # Add location filters if provided
    # Note: Buildings nodes only have 'state' metadata, NOT 'zip' or 'city'
    # Building codes are state-level, not zip/city-level
    skipped_filters = []
    if location_filters:
        for filter_obj in location_filters:
            if hasattr(filter_obj, 'key') and filter_obj.key == 'state':
                # State filters are supported (building codes vary by state)
                buildings_filter_filters.append(filter_obj)
            elif hasattr(filter_obj, 'key') and filter_obj.key in ['zip', 'queried_zip', 'city']:
                # Skip zip and city filters - buildings nodes don't have these metadata fields
                skipped_filters.append(filter_obj.key)
    
    if skipped_filters:
        print(f"[BuildingsTool] Skipping {', '.join(skipped_filters)} filter(s) - buildings nodes only have 'state' metadata")
    
    buildings_filter = MetadataFilters(filters=buildings_filter_filters)
    
    # Create retriever
    initial_top_k = top_k * 2 if use_reranking else top_k
    buildings_retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=initial_top_k,
        filters=buildings_filter
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
            print(f"Warning: Failed to create reranker for buildings tool: {str(e)}")
    
    # Create query engine with custom response synthesizer
    from llama_index.core.response_synthesizers import get_response_synthesizer
    from llama_index.core.response_synthesizers.type import ResponseMode
    from llama_index.core.prompts import PromptTemplate
    
    # Create custom response synthesizer with explicit prompt
    buildings_response_synthesizer = get_response_synthesizer(
        llm=llm,
        response_mode=ResponseMode.COMPACT,
        text_qa_template=PromptTemplate(
            "Context information about building energy codes and standards is below.\n"
            "---------------------\n"
            "{context_str}\n"
            "---------------------\n"
            "You are a helpful assistant providing information about building energy codes, "
            "energy efficiency standards, building performance requirements, code compliance, "
            "and building energy modeling. "
            "Use the context information to answer the user's question about building codes, "
            "standards, efficiency requirements, and compliance information.\n"
            "Query: {query_str}\n"
            "Answer: "
        )
    )
    
    # Create query engine
    base_query_engine = RetrieverQueryEngine.from_args(
        retriever=buildings_retriever,
        llm=llm,
        node_postprocessors=node_postprocessors,
        callback_manager=callback_manager,
        response_synthesizer=buildings_response_synthesizer
    )
    
    # Initialize BCL client for fallback fetching
    if bcl_client is None:
        bcl_client = BCLClient()
    
    # Initialize freshness checker
    from app.services.rag_settings import RAGSettings
    settings = RAGSettings()
    freshness_checker = FreshnessChecker(vector_store_service, settings)
    
    # Wrap query engine to add BCL API fallback with freshness checking
    class BuildingsQueryEngineWrapper(BaseQueryEngine):
        """Wrapper to add BCL API fallback with freshness checking for buildings query engine."""
        
        def __init__(self, base_engine, retriever, bcl_client, vector_store_service, freshness_checker, callback_manager=None):
            super().__init__(callback_manager=callback_manager)
            self.base_engine = base_engine
            self.retriever = retriever
            self.bcl_client = bcl_client
            self.vector_store_service = vector_store_service
            self.freshness_checker = freshness_checker
        
        def _get_prompt_modules(self):
            """Get prompt sub-modules. Returns empty dict since we delegate to base engine."""
            return {}
        
        def _extract_state_from_query(self, query_str: str) -> Optional[str]:
            """Extract state code from query string."""
            # Try to extract state code (2 uppercase letters)
            state_match = re.search(r'\b([A-Z]{2})\b', query_str)
            if state_match:
                return state_match.group(1)
            
            # Try to extract state name and convert to code
            # Common state name patterns
            state_names = {
                "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
                "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
                "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
                "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
                "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
                "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
                "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
                "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
                "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
                "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
                "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
                "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
                "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC"
            }
            
            query_lower = query_str.lower()
            for state_name, state_code in state_names.items():
                if state_name in query_lower:
                    return state_code
            
            return None
        
        async def _fetch_from_bcl_api(self, query_str: str, state: Optional[str] = None) -> Optional[str]:
            """Fetch building codes and efficiency measures from BCL API."""
            try:
                from app.services.document_service import DocumentService
                document_service = DocumentService()
                
                # Extract key terms from query for better search
                search_query = None
                query_lower = query_str.lower()
                keywords = []
                if any(term in query_lower for term in ["code", "standard", "compliance", "iecc", "ashrae"]):
                    keywords.append("energy code")
                if any(term in query_lower for term in ["efficiency", "retrofit", "improve", "reduce", "lower"]):
                    keywords.append("energy efficiency")
                if any(term in query_lower for term in ["building", "residential", "home"]):
                    keywords.append("residential")
                
                # Use first keyword or original query
                search_query = keywords[0] if keywords else query_str[:50]  # Limit query length
                
                # Search for building code measures
                print(f"[BuildingsTool] bcl_api_call | type=building_codes | query='{search_query[:50] if search_query else 'N/A'}' | state={state}")
                building_codes = await self.bcl_client.search_building_codes(
                    query=search_query,
                    limit=10
                )
                
                # Search for energy efficiency measures
                print(f"[BuildingsTool] bcl_api_call | type=efficiency_measures | query='{search_query[:50] if search_query else 'N/A'}' | state={state}")
                efficiency_measures = await self.bcl_client.search_energy_efficiency_measures(
                    query=search_query,
                    limit=10
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
                    return None
                
                # Convert to documents
                documents = document_service.bcl_measures_to_documents(
                    measures=unique_measures,
                    state=state
                )
                
                if not documents or len(documents) == 0:
                    return None
                
                # Index the fetched documents to vector store for future queries
                try:
                    index = self.vector_store_service.get_index()
                    # Use bulk insert if available
                    if hasattr(index, 'insert_nodes'):
                        from llama_index.core.node_parser import SimpleNodeParser
                        node_parser = SimpleNodeParser.from_defaults()
                        nodes = node_parser.get_nodes_from_documents(documents)
                        if nodes:
                            index.insert_nodes(nodes)
                    else:
                        # Fallback to individual inserts
                        for doc in documents:
                            try:
                                index.insert(doc)
                            except Exception:
                                pass
                    print(f"[BuildingsTool] indexed_bcl_data | state={state} | documents={len(documents)}")
                except Exception as index_error:
                    # Don't fail the query if indexing fails - just log it
                    print(f"[BuildingsTool] WARNING indexing_failed | state={state} | error={str(index_error)[:100]}")
                
                # Extract formatted text from documents
                formatted_texts = []
                for doc in documents[:5]:  # Limit to top 5 measures
                    doc_text = doc.text if hasattr(doc, 'text') else str(doc)
                    metadata = doc.metadata if hasattr(doc, 'metadata') else {}
                    measure_name = metadata.get('name', 'Unknown Measure')
                    
                    # Build summary
                    summary = f"{measure_name}: {doc_text[:200]}..."
                    formatted_texts.append(summary)
                
                if formatted_texts:
                    return "Building energy codes and efficiency measures:\n" + "\n\n".join(formatted_texts)
                
                return None
                
            except Exception as e:
                print(f"[BuildingsTool] ERROR fetching from BCL: {str(e)}")
                import traceback
                traceback.print_exc()
                return None
        
        def _query(self, query_bundle: QueryBundle) -> Response:
            """Synchronous query - delegate to base engine."""
            query_str = query_bundle.query_str
            
            # Check retriever
            try:
                nodes = self.retriever.retrieve(query_str)
                node_count = len(nodes) if nodes else 0
                if node_count > 0:
                    first_node = nodes[0]
                    metadata = first_node.metadata if hasattr(first_node, "metadata") else {}
                    state = metadata.get('state', 'N/A')
                    print(f"[BuildingsTool] query='{query_str[:50]}...' | nodes={node_count} | state={state}")
                else:
                    print(f"[BuildingsTool] query='{query_str[:50]}...' | nodes=0")
            except Exception as e:
                print(f"[BuildingsTool] ERROR retrieving nodes: {str(e)}")
            
            # Check if we have nodes before querying
            nodes = self.retriever.retrieve(query_str)
            if not nodes or len(nodes) == 0:
                print(f"[BuildingsTool] no_nodes | sync_query | cannot_fetch_async")
                empty_response = Response(
                    response="I do not have building energy code or efficiency standard data available. The data may not be available in the database, or building codes may need to be indexed first.",
                    source_nodes=[],
                    metadata={}
                )
                return empty_response
            
            # Delegate to base engine
            response = self.base_engine.query(query_bundle)
            
            # Check if response is empty
            response_text = ""
            if hasattr(response, "response"):
                response_text = str(response.response) if response.response else ""
            elif hasattr(response, "text"):
                response_text = response.text if response.text else ""
            
            if not response_text or response_text.strip() == "" or response_text.strip() == "Empty Response":
                print(f"[BuildingsTool] empty_response | creating_helpful_message")
                helpful_response = Response(
                    response="I do not have building energy code or efficiency standard data available. The data may not be available in the database, or building codes may need to be indexed first.",
                    source_nodes=response.source_nodes if hasattr(response, 'source_nodes') else [],
                    metadata=response.metadata if hasattr(response, 'metadata') else {}
                )
                return helpful_response
            
            return response
        
        async def _aquery(self, query_bundle: QueryBundle) -> Response:
            """Async query with observability."""
            query_str = query_bundle.query_str
            
            # Check what nodes the retriever finds
            nodes = None
            try:
                nodes = self.retriever.retrieve(query_str)
                node_count = len(nodes) if nodes else 0
                
                if node_count > 0:
                    first_node = nodes[0]
                    metadata = first_node.metadata if hasattr(first_node, "metadata") else {}
                    state = metadata.get('state', 'N/A')
                    measure_name = metadata.get('name', 'N/A')[:30]
                    print(f"[BuildingsTool] query='{query_str[:50]}...' | nodes={node_count} | state={state} | measure={measure_name}")
                else:
                    print(f"[BuildingsTool] query='{query_str[:50]}...' | nodes=0 | checking_unfiltered")
                    # Try without filters to see if there are any building documents at all
                    try:
                        from llama_index.core.retrievers import VectorIndexRetriever
                        from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
                        unfiltered_retriever = VectorIndexRetriever(
                            index=self.retriever._index if hasattr(self.retriever, '_index') else None,
                            similarity_top_k=5,
                            filters=MetadataFilters(filters=[
                                MetadataFilter(key="domain", value="buildings", operator=FilterOperator.EQ)
                            ])
                        )
                        all_nodes = unfiltered_retriever.retrieve("building code")
                        unfiltered_count = len(all_nodes) if all_nodes else 0
                        if unfiltered_count > 0:
                            print(f"[BuildingsTool] unfiltered_nodes={unfiltered_count}")
                    except Exception as e2:
                        print(f"[BuildingsTool] ERROR checking unfiltered: {str(e2)}")
            except Exception as e:
                print(f"[BuildingsTool] ERROR retrieving nodes: {str(e)}")
                import traceback
                traceback.print_exc()
            
            # Extract state from query for BCL API fallback
            queried_state = self._extract_state_from_query(query_str)
            
            # Check if we have nodes before querying
            if not nodes or len(nodes) == 0:
                print(f"[BuildingsTool] no_nodes | checking_freshness | state={queried_state}")
                
                # Check freshness before fetching from API
                should_fetch = False
                if queried_state:
                    # First check if we have ANY building data (to detect state mismatches)
                    has_any_building_data = False
                    try:
                        from llama_index.core.retrievers import VectorIndexRetriever
                        from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
                        any_state_retriever = VectorIndexRetriever(
                            index=self.retriever._index if hasattr(self.retriever, '_index') else None,
                            similarity_top_k=1,
                            filters=MetadataFilters(filters=[
                                MetadataFilter(key="domain", value="buildings", operator=FilterOperator.EQ)
                            ])
                        )
                        any_nodes = any_state_retriever.retrieve("building code")
                        has_any_building_data = any_nodes and len(any_nodes) > 0
                        if has_any_building_data:
                            # Check what state(s) we have data for
                            existing_states = set()
                            for node in any_nodes[:5]:  # Check first 5 nodes
                                if hasattr(node, 'metadata'):
                                    node_state = node.metadata.get('state')
                                    if node_state:
                                        existing_states.add(node_state)
                            if existing_states and queried_state not in existing_states:
                                print(f"[BuildingsTool] state_mismatch | queried={queried_state} | existing={','.join(existing_states)} | fetching_for_queried_state")
                    except Exception as e:
                        print(f"[BuildingsTool] ERROR checking any building data: {str(e)}")
                    
                    # Check freshness for this specific state
                    is_fresh, indexed_at = await self.freshness_checker.check_bcl_measures_freshness(queried_state)
                    if not is_fresh:
                        if indexed_at:
                            print(f"[BuildingsTool] freshness_check | state={queried_state} | source=vector_store | stale=true")
                        else:
                            if has_any_building_data:
                                print(f"[BuildingsTool] freshness_check | state={queried_state} | source=vector_store | found=false | state_mismatch")
                            else:
                                print(f"[BuildingsTool] freshness_check | state={queried_state} | source=vector_store | found=false | no_building_data")
                        should_fetch = True
                    else:
                        print(f"[BuildingsTool] freshness_check | state={queried_state} | source=vector_store | fresh=true")
                else:
                    # No state specified - fetch anyway (can't check freshness without state)
                    should_fetch = True
                
                # Try fetching from BCL API as fallback if data is stale or doesn't exist
                if should_fetch:
                    print(f"[BuildingsTool] attempting_bcl_fallback | state={queried_state}")
                    if queried_state:
                        bcl_response = await self._fetch_from_bcl_api(query_str, state=queried_state)
                        if bcl_response:
                            node = TextNode(text=bcl_response)
                            node_with_score = NodeWithScore(node=node, score=1.0)
                            return Response(
                                response=bcl_response,
                                source_nodes=[node_with_score]
                            )
                    else:
                        # Try without state filter
                        bcl_response = await self._fetch_from_bcl_api(query_str, state=None)
                        if bcl_response:
                            node = TextNode(text=bcl_response)
                            node_with_score = NodeWithScore(node=node, score=1.0)
                            return Response(
                                response=bcl_response,
                                source_nodes=[node_with_score]
                            )
                
                print(f"[BuildingsTool] no_nodes | bcl_fallback_failed | returning_empty_response")
                empty_response = Response(
                    response="I do not have building energy code or efficiency standard data available. The data may not be available in the database, or building codes may need to be indexed first.",
                    source_nodes=[],
                    metadata={}
                )
                return empty_response
            
            # Execute query
            try:
                response = await self.base_engine._aquery(query_bundle)
                
                # Check if response is actually empty
                response_text = ""
                if hasattr(response, "response"):
                    response_text = str(response.response) if response.response else ""
                elif hasattr(response, "text"):
                    response_text = response.text if response.text else ""
                
                if not response_text or response_text.strip() == "" or response_text.strip() == "Empty Response":
                    if not (hasattr(response, 'source_nodes') and response.source_nodes and len(response.source_nodes) > 0):
                        print(f"[BuildingsTool] empty_response | no_source_nodes | checking_freshness")
                        
                        # Check freshness before fetching from API
                        should_fetch = False
                        if queried_state:
                            # First check if we have ANY building data (to detect state mismatches)
                            has_any_building_data = False
                            try:
                                from llama_index.core.retrievers import VectorIndexRetriever
                                from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
                                any_state_retriever = VectorIndexRetriever(
                                    index=self.retriever._index if hasattr(self.retriever, '_index') else None,
                                    similarity_top_k=1,
                                    filters=MetadataFilters(filters=[
                                        MetadataFilter(key="domain", value="buildings", operator=FilterOperator.EQ)
                                    ])
                                )
                                any_nodes = any_state_retriever.retrieve("building code")
                                has_any_building_data = any_nodes and len(any_nodes) > 0
                                if has_any_building_data:
                                    # Check what state(s) we have data for
                                    existing_states = set()
                                    for node in any_nodes[:5]:  # Check first 5 nodes
                                        if hasattr(node, 'metadata'):
                                            node_state = node.metadata.get('state')
                                            if node_state:
                                                existing_states.add(node_state)
                                    if existing_states and queried_state not in existing_states:
                                        print(f"[BuildingsTool] state_mismatch | queried={queried_state} | existing={','.join(existing_states)} | fetching_for_queried_state")
                            except Exception as e:
                                print(f"[BuildingsTool] ERROR checking any building data: {str(e)}")
                            
                            is_fresh, indexed_at = await self.freshness_checker.check_bcl_measures_freshness(queried_state)
                            if not is_fresh:
                                if indexed_at:
                                    print(f"[BuildingsTool] freshness_check | state={queried_state} | source=vector_store | stale=true")
                                else:
                                    if has_any_building_data:
                                        print(f"[BuildingsTool] freshness_check | state={queried_state} | source=vector_store | found=false | state_mismatch")
                                    else:
                                        print(f"[BuildingsTool] freshness_check | state={queried_state} | source=vector_store | found=false | no_building_data")
                                should_fetch = True
                            else:
                                print(f"[BuildingsTool] freshness_check | state={queried_state} | source=vector_store | fresh=true")
                        else:
                            # No state specified - fetch anyway
                            should_fetch = True
                        
                        # Try fetching from BCL API as fallback if data is stale or doesn't exist
                        if should_fetch:
                            print(f"[BuildingsTool] attempting_bcl_fallback | state={queried_state}")
                            if queried_state:
                                bcl_response = await self._fetch_from_bcl_api(query_str, state=queried_state)
                                if bcl_response:
                                    node = TextNode(text=bcl_response)
                                    node_with_score = NodeWithScore(node=node, score=1.0)
                                    return Response(
                                        response=bcl_response,
                                        source_nodes=[node_with_score]
                                    )
                            else:
                                # Try without state filter
                                bcl_response = await self._fetch_from_bcl_api(query_str, state=None)
                                if bcl_response:
                                    node = TextNode(text=bcl_response)
                                    node_with_score = NodeWithScore(node=node, score=1.0)
                                    return Response(
                                        response=bcl_response,
                                        source_nodes=[node_with_score]
                                    )
                    
                    print(f"[BuildingsTool] empty_response | creating_helpful_message")
                    helpful_response = Response(
                        response="I do not have building energy code or efficiency standard data available. The data may not be available in the database, or building codes may need to be indexed first.",
                        source_nodes=response.source_nodes if hasattr(response, 'source_nodes') else [],
                        metadata=response.metadata if hasattr(response, 'metadata') else {}
                    )
                    return helpful_response
                
                return response
                
            except Exception as e:
                print(f"[BuildingsTool] ERROR query: {str(e)}")
                import traceback
                traceback.print_exc()
                raise e
    
    # Wrap the query engine
    wrapped_engine = BuildingsQueryEngineWrapper(
        base_query_engine, 
        buildings_retriever,
        bcl_client,
        vector_store_service,
        freshness_checker,
        callback_manager=callback_manager
    )
    
    # Create tool with high-quality metadata
    tool = QueryEngineTool.from_defaults(
        query_engine=wrapped_engine,
        name="buildings_tool",
        description=(
            "BUILDINGS DOMAIN: Use this for questions about building energy codes, "
            "energy efficiency standards, building performance requirements, code compliance, "
            "building energy modeling, energy codes (IECC, ASHRAE), building standards, "
            "energy efficiency requirements, building codes, building performance data, "
            "and ways to reduce electricity bills through building efficiency improvements. "
            "Use this when the question asks about building codes, energy codes, efficiency standards, "
            "code compliance, building performance, energy requirements for buildings, "
            "how to lower electricity bills through efficiency, energy retrofits, or improving building efficiency. "
            "Use this when the question contains words like 'building code', 'energy code', "
            "'IECC', 'ASHRAE', 'building standard', 'efficiency requirement', 'code compliance', "
            "'building performance', 'energy efficiency standard', 'building energy code', "
            "'lower bill', 'reduce electricity', 'energy efficiency measure', 'energy retrofit', "
            "'improve efficiency', or 'reduce consumption'. "
            "DO NOT use this for questions about solar production estimates, utility rates, charging stations, "
            "or optimization analysis. Use the appropriate domain-specific tool for those questions."
        )
    )
    
    return tool

