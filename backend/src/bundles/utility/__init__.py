"""
Utility Bundle: Electricity rates, utility costs, and tariff information.

This bundle provides:
- Electricity rate queries
- Utility cost information
- Time-of-use rate schedules
- Utility provider information
"""

from typing import Optional, List
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
from llama_index.core.schema import QueryBundle
from app.services.vector_store_service import VectorStoreService


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
            "If the context above is empty or contains no utility rate data, respond with: "
            "'I do not have utility rate data available for this location. The data may not be available in the database, or the location may need to be indexed first.' "
            "Otherwise, provide the utility rate information clearly and accurately.\n"
            "Query: {query_str}\n"
            "Answer: "
        )
    )
    
    # Create query engine (same pattern as transportation tool)
    base_utility_query_engine = RetrieverQueryEngine.from_args(
        retriever=utility_retriever,
        llm=llm,
        node_postprocessors=node_postprocessors,
        response_synthesizer=utility_response_synthesizer,
        callback_manager=callback_manager
    )
    
    # Wrap query engine to add debug logging
    class UtilityQueryEngineWrapper(BaseQueryEngine):
        """Wrapper to add debug logging for utility query engine."""
        
        def __init__(self, base_engine, retriever, callback_manager=None):
            super().__init__(callback_manager=callback_manager)
            self.base_engine = base_engine
            self.retriever = retriever
        
        def _get_prompt_modules(self):
            """Get prompt sub-modules. Returns empty dict since we delegate to base engine."""
            return {}
        
        def _query(self, query_bundle: QueryBundle) -> Response:
            """Synchronous query - delegate to base engine with debugging."""
            query_str = query_bundle.query_str
            print(f"\n[UtilityTool] ===== DEBUG START (SYNC) =====")
            print(f"[UtilityTool] Query: {query_str}")
            
            # Check retriever
            try:
                nodes = self.retriever.retrieve(query_str)
                print(f"[UtilityTool] Retriever found {len(nodes) if nodes else 0} nodes")
                
                # If no nodes, return helpful message
                if not nodes or len(nodes) == 0:
                    print(f"[UtilityTool] WARNING: No nodes found, returning helpful empty response")
                    empty_response = Response(
                        response="I do not have utility rate data available for this location. The data may not be available in the database, or the location may need to be indexed first.",
                        source_nodes=[],
                        metadata={}
                    )
                    print(f"[UtilityTool] ===== DEBUG END (NO DATA) =====\n")
                    return empty_response
            except Exception as e:
                print(f"[UtilityTool] ERROR retrieving nodes: {str(e)}")
            
            # Delegate to base engine
            response = self.base_engine._query(query_bundle)
            self._debug_response(response, query_str)
            
            # Check if response is actually empty
            response_text = ""
            if hasattr(response, "response"):
                response_text = str(response.response) if response.response else ""
            elif hasattr(response, "text"):
                response_text = response.text if response.text else ""
            
            if not response_text or response_text.strip() == "" or response_text.strip() == "Empty Response":
                print(f"[UtilityTool] Response is empty, creating helpful message")
                helpful_response = Response(
                    response="I do not have utility rate data available for this location. The data may not be available in the database, or the location may need to be indexed first.",
                    source_nodes=response.source_nodes if hasattr(response, 'source_nodes') else [],
                    metadata=response.metadata if hasattr(response, 'metadata') else {}
                )
                print(f"[UtilityTool] ===== DEBUG END (SYNC) =====\n")
                return helpful_response
            
            print(f"[UtilityTool] ===== DEBUG END (SYNC) =====\n")
            return response
        
        async def _aquery(self, query_bundle: QueryBundle) -> Response:
            """Async query with detailed debugging."""
            query_str = query_bundle.query_str
            print(f"\n[UtilityTool] ===== DEBUG START =====")
            print(f"[UtilityTool] Query: {query_str}")
            
            # First, check what nodes the retriever finds
            try:
                print(f"[UtilityTool] Checking retriever directly...")
                print(f"[UtilityTool] Retriever filters: {self.retriever._filters if hasattr(self.retriever, '_filters') else 'N/A'}")
                nodes = self.retriever.retrieve(query_str)
                print(f"[UtilityTool] Retriever found {len(nodes) if nodes else 0} nodes")
                
                if nodes:
                    for i, node in enumerate(nodes[:3]):  # Show first 3 nodes
                        metadata = node.metadata if hasattr(node, "metadata") else {}
                        node_text = node.text[:100] if hasattr(node, "text") and node.text else "No text"
                        print(f"[UtilityTool] Node {i+1}:")
                        print(f"  - Text preview: {node_text}")
                        print(f"  - Metadata: {metadata}")
                else:
                    print(f"[UtilityTool] WARNING: Retriever returned no nodes!")
                    # Try without filters to see if there are any utility rates at all
                    print(f"[UtilityTool] Checking if ANY utility nodes exist (no filters)...")
                    try:
                        unfiltered_retriever = VectorIndexRetriever(
                            index=self.retriever._index if hasattr(self.retriever, '_index') else None,
                            similarity_top_k=5,
                            filters=MetadataFilters(filters=[
                                MetadataFilter(key="domain", value="utility", operator=FilterOperator.EQ)
                            ])
                        )
                        all_nodes = unfiltered_retriever.retrieve("electricity rate")
                        print(f"[UtilityTool] Found {len(all_nodes) if all_nodes else 0} utility nodes total (no zip filter)")
                        if all_nodes:
                            for i, node in enumerate(all_nodes[:3]):
                                metadata = node.metadata if hasattr(node, "metadata") else {}
                                print(f"[UtilityTool] Sample node {i+1} zip: {metadata.get('zip', 'N/A')}")
                    except Exception as e2:
                        print(f"[UtilityTool] Could not check unfiltered nodes: {str(e2)}")
            except Exception as e:
                print(f"[UtilityTool] ERROR retrieving nodes: {str(e)}")
                import traceback
                traceback.print_exc()
            
            # Check response synthesizer
            if hasattr(self.base_engine, "response_synthesizer"):
                print(f"[UtilityTool] Query engine has response_synthesizer: {type(self.base_engine.response_synthesizer)}")
            else:
                print(f"[UtilityTool] WARNING: Query engine has no response_synthesizer attribute")
            
            # Check if we have nodes before querying
            nodes = self.retriever.retrieve(query_str)
            if not nodes or len(nodes) == 0:
                print(f"[UtilityTool] WARNING: No nodes found, returning helpful empty response")
                # Create a response indicating no data available
                empty_response = Response(
                    response="I do not have utility rate data available for this location. The data may not be available in the database, or the location may need to be indexed first.",
                    source_nodes=[],
                    metadata={}
                )
                print(f"[UtilityTool] ===== DEBUG END (NO DATA) =====\n")
                return empty_response
            
            # Now try the actual query
            try:
                print(f"[UtilityTool] Calling base query engine...")
                response = await self.base_engine._aquery(query_bundle)
                print(f"[UtilityTool] Base query engine returned response")
                
                self._debug_response(response, query_str)
                
                # Check if response is actually empty or just says "Empty Response"
                response_text = ""
                if hasattr(response, "response"):
                    response_text = str(response.response) if response.response else ""
                elif hasattr(response, "text"):
                    response_text = response.text if response.text else ""
                
                if not response_text or response_text.strip() == "" or response_text.strip() == "Empty Response":
                    print(f"[UtilityTool] Response is empty, creating helpful message")
                    helpful_response = Response(
                        response="I do not have utility rate data available for this location. The data may not be available in the database, or the location may need to be indexed first.",
                        source_nodes=response.source_nodes if hasattr(response, 'source_nodes') else [],
                        metadata=response.metadata if hasattr(response, 'metadata') else {}
                    )
                    print(f"[UtilityTool] ===== DEBUG END =====\n")
                    return helpful_response
                
                print(f"[UtilityTool] ===== DEBUG END =====\n")
                return response
                
            except Exception as e:
                print(f"[UtilityTool] ERROR in query: {str(e)}")
                import traceback
                traceback.print_exc()
                print(f"[UtilityTool] ===== DEBUG END (ERROR) =====\n")
                raise e
        
        def _debug_response(self, response: Response, query_str: str):
            """Debug helper to inspect response object."""
            # Check response structure
            print(f"[UtilityTool] Response type: {type(response)}")
            print(f"[UtilityTool] Response attributes: {[a for a in dir(response) if not a.startswith('__')]}")
            
            # Check if response has source_nodes
            if hasattr(response, "source_nodes"):
                print(f"[UtilityTool] Response has {len(response.source_nodes) if response.source_nodes else 0} source_nodes")
            
            # Extract response text
            response_text = ""
            if hasattr(response, "response"):
                response_text = str(response.response) if response.response else ""
                print(f"[UtilityTool] response.response: {response_text[:200] if response_text else 'EMPTY'}")
            elif hasattr(response, "text"):
                response_text = response.text if response.text else ""
                print(f"[UtilityTool] response.text: {response_text[:200] if response_text else 'EMPTY'}")
            else:
                response_text = str(response) if response else ""
                print(f"[UtilityTool] str(response): {response_text[:200] if response_text else 'EMPTY'}")
            
            print(f"[UtilityTool] Response text length: {len(response_text)}")
            print(f"[UtilityTool] Response text is empty: {not response_text or response_text.strip() == ''}")
            
            if not response_text or response_text.strip() == "":
                print(f"[UtilityTool] ERROR: Empty response detected!")
                print(f"[UtilityTool] Full response object: {response}")
                
                # Check if response has any other attributes that might contain data
                for attr in dir(response):
                    if not attr.startswith("_"):
                        try:
                            attr_value = getattr(response, attr)
                            if attr_value and attr not in ["response", "text"]:
                                print(f"[UtilityTool] response.{attr}: {str(attr_value)[:100]}")
                        except Exception:
                            pass
    
    # Wrap the query engine
    wrapped_engine = UtilityQueryEngineWrapper(
        base_utility_query_engine,
        utility_retriever,
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

