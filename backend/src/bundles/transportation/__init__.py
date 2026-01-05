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
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.callbacks import CallbackManager
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
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
    
    # Create query engine
    transportation_query_engine = RetrieverQueryEngine.from_args(
        retriever=transportation_retriever,
        llm=llm,
        node_postprocessors=node_postprocessors,
        callback_manager=callback_manager
    )
    
    # Create tool with high-quality metadata
    tool = QueryEngineTool.from_defaults(
        query_engine=transportation_query_engine,
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

