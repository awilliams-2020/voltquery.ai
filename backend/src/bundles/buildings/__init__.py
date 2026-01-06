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
    Get the buildings tool as a QueryEngineTool.
    
    This tool provides building energy code, efficiency standards, and compliance queries
    using the vector store index.
    
    Args:
        llm: LLM instance for query processing
        vector_store_service: Vector store service for retrieving building data
        callback_manager: Optional callback manager for observability
        top_k: Number of top results to retrieve
        use_reranking: Whether to use LLM reranking
        rerank_top_n: Number of results to rerank if reranking is enabled
        location_filters: Optional location-based metadata filters
        
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
    
    # Wrap query engine to investigate empty responses
    class BuildingsQueryEngineWrapper(BaseQueryEngine):
        """Wrapper to investigate empty responses from buildings query engine."""
        
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
                    state = metadata.get('state', 'N/A')
                    print(f"[BuildingsTool] query='{query_str[:50]}...' | nodes={node_count} | state={state}")
                else:
                    print(f"[BuildingsTool] query='{query_str[:50]}...' | nodes=0")
            except Exception as e:
                print(f"[BuildingsTool] ERROR retrieving nodes: {str(e)}")
            
            # Check if we have nodes before querying
            nodes = self.retriever.retrieve(query_str)
            if not nodes or len(nodes) == 0:
                print(f"[BuildingsTool] no_nodes | returning_empty_response")
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
            
            # Check if we have nodes before querying
            if not nodes or len(nodes) == 0:
                print(f"[BuildingsTool] no_nodes | returning_empty_response")
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

