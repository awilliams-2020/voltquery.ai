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
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.callbacks import CallbackManager
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.response_synthesizers.type import ResponseMode
from llama_index.core.prompts import PromptTemplate
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
    if location_filters:
        utility_filter_filters.extend(location_filters)
    
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
            "Provide the utility rate information clearly and accurately.\n"
            "Query: {query_str}\n"
            "Answer: "
        )
    )
    
    # Create query engine
    utility_query_engine = RetrieverQueryEngine.from_args(
        retriever=utility_retriever,
        llm=llm,
        node_postprocessors=node_postprocessors,
        response_synthesizer=utility_response_synthesizer,
        callback_manager=callback_manager
    )
    
    # Create tool with high-quality metadata
    tool = QueryEngineTool.from_defaults(
        query_engine=utility_query_engine,
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

