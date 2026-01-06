"""
Transportation Bundle: EV charging stations and infrastructure.

This bundle provides:
- EV charging station location queries
- Charger type information (J1772, CCS, CHAdeMO, NEMA)
- Station network information
- DC fast charging and Level 2 charging data
"""

from typing import Optional, List
from llama_index.core.tools import QueryEngineTool
from llama_index.core.query_engine import RetrieverQueryEngine, BaseQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.callbacks import CallbackManager
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
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
    Get the transportation tool as a QueryEngineTool.
    
    This tool provides EV charging station location and information queries
    using the vector store index.
    
    Args:
        llm: LLM instance for query processing
        vector_store_service: Vector store service for retrieving stations
        callback_manager: Optional callback manager for observability
        top_k: Number of top results to retrieve
        use_reranking: Whether to use LLM reranking
        rerank_top_n: Number of results to rerank if reranking is enabled
        location_filters: Optional location-based metadata filters
        
    Returns:
        QueryEngineTool configured for transportation/EV charging queries
    """
    # Get vector store index
    index = vector_store_service.get_index()
    
    # Build transportation domain filter
    transportation_filter_filters = [
        MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ)
    ]
    
    # Add location filters if provided
    if location_filters:
        transportation_filter_filters.extend(location_filters)
    
    transportation_filter = MetadataFilters(filters=transportation_filter_filters)
    
    # Create retriever
    initial_top_k = top_k * 2 if use_reranking else top_k
    transportation_retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=initial_top_k,
        filters=transportation_filter
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
            print(f"Warning: Failed to create reranker for transportation tool: {str(e)}")
    
    # Create query engine with custom response synthesizer for better debugging
    from llama_index.core.response_synthesizers import get_response_synthesizer
    from llama_index.core.response_synthesizers.type import ResponseMode
    from llama_index.core.prompts import PromptTemplate
    
    # Create custom response synthesizer with explicit prompt
    transportation_response_synthesizer = get_response_synthesizer(
        llm=llm,
        response_mode=ResponseMode.COMPACT,
        text_qa_template=PromptTemplate(
            "Context information about EV charging stations is below.\n"
            "---------------------\n"
            "{context_str}\n"
            "---------------------\n"
            "You are a helpful assistant providing information about EV charging stations. "
            "Use the context information to answer the user's question about charging station locations, "
            "charger types, networks, and availability.\n"
            "Query: {query_str}\n"
            "Answer: "
        )
    )
    
    # Create query engine
    base_query_engine = RetrieverQueryEngine.from_args(
        retriever=transportation_retriever,
        llm=llm,
        node_postprocessors=node_postprocessors,
        callback_manager=callback_manager,
        response_synthesizer=transportation_response_synthesizer
    )
    
    # Wrap query engine to investigate empty responses
    class TransportationQueryEngineWrapper(BaseQueryEngine):
        """Wrapper to investigate empty responses from transportation query engine."""
        
        def __init__(self, base_engine, retriever, callback_manager=None):
            super().__init__(callback_manager=callback_manager)
            self.base_engine = base_engine
            self.retriever = retriever
        
        def _get_prompt_modules(self):
            """Get prompt sub-modules. Returns empty dict since we delegate to base engine."""
            return {}
        
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
                    city = metadata.get('city', 'N/A')
                    state = metadata.get('state', 'N/A')
                    zip_code = metadata.get('zip', 'N/A')
                    print(f"[TransportationTool] query='{query_str[:50]}...' | nodes={node_count} | city={city} state={state} zip={zip_code}")
                else:
                    print(f"[TransportationTool] query='{query_str[:50]}...' | nodes=0")
            except Exception as e:
                print(f"[TransportationTool] ERROR retrieving_nodes | error={str(e)[:100]}")
            
            # Delegate to base engine
            response = self.base_engine.query(query_bundle)
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
                    city = metadata.get('city', 'N/A')
                    state = metadata.get('state', 'N/A')
                    zip_code = metadata.get('zip', 'N/A')
                    print(f"[TransportationTool] query='{query_str[:50]}...' | nodes={node_count} | city={city} state={state} zip={zip_code}")
                else:
                    print(f"[TransportationTool] query='{query_str[:50]}...' | nodes=0 | checking_unfiltered")
                    # Try without filters to see if there are any stations at all
                    try:
                        from llama_index.core.retrievers import VectorIndexRetriever
                        from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
                        unfiltered_retriever = VectorIndexRetriever(
                            index=self.retriever._index if hasattr(self.retriever, '_index') else None,
                            similarity_top_k=5,
                            filters=MetadataFilters(filters=[
                                MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ)
                            ])
                        )
                        all_nodes = unfiltered_retriever.retrieve("charging station")
                        unfiltered_count = len(all_nodes) if all_nodes else 0
                        if unfiltered_count > 0:
                            print(f"[TransportationTool] unfiltered_nodes={unfiltered_count}")
                    except Exception as e2:
                        print(f"[TransportationTool] ERROR checking_unfiltered | error={str(e2)[:100]}")
            except Exception as e:
                print(f"[TransportationTool] ERROR retrieving_nodes | error={str(e)[:100]}")
            
            # Check if we have nodes before querying
            if not nodes or len(nodes) == 0:
                print(f"[TransportationTool] no_nodes | returning_empty_response")
                empty_response = Response(
                    response="I do not have EV charging station data available for this location. The data may not be available in the database, or charging stations may need to be indexed first.",
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
                    print(f"[TransportationTool] empty_response | creating_helpful_message")
                    helpful_response = Response(
                        response="I do not have EV charging station data available for this location. The data may not be available in the database, or charging stations may need to be indexed first.",
                        source_nodes=response.source_nodes if hasattr(response, 'source_nodes') else [],
                        metadata=response.metadata if hasattr(response, 'metadata') else {}
                    )
                    return helpful_response
                
                return response
                
            except Exception as e:
                print(f"[TransportationTool] ERROR query | error={str(e)[:100]}")
                raise e
        
    
    # Wrap the query engine
    wrapped_engine = TransportationQueryEngineWrapper(
        base_query_engine, 
        transportation_retriever,
        callback_manager=callback_manager
    )
    
    # Create tool with high-quality metadata
    tool = QueryEngineTool.from_defaults(
        query_engine=wrapped_engine,
        name="transportation_tool",
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
    
    return tool

