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
            """Synchronous query - delegate to base engine with debugging."""
            query_str = query_bundle.query_str
            print(f"\n[TransportationTool] ===== DEBUG START (SYNC) =====")
            print(f"[TransportationTool] Query: {query_str}")
            
            # Check retriever
            try:
                nodes = self.retriever.retrieve(query_str)
                print(f"[TransportationTool] Retriever found {len(nodes) if nodes else 0} nodes")
            except Exception as e:
                print(f"[TransportationTool] ERROR retrieving nodes: {str(e)}")
            
            # Delegate to base engine
            response = self.base_engine.query(query_bundle)
            self._debug_response(response, query_str)
            print(f"[TransportationTool] ===== DEBUG END (SYNC) =====\n")
            return response
        
        async def _aquery(self, query_bundle: QueryBundle) -> Response:
            """Async query with detailed debugging for empty responses."""
            query_str = query_bundle.query_str
            print(f"\n[TransportationTool] ===== DEBUG START =====")
            print(f"[TransportationTool] Query: {query_str}")
            
            # First, check what nodes the retriever finds
            try:
                print(f"[TransportationTool] Checking retriever directly...")
                print(f"[TransportationTool] Retriever filters: {self.retriever._filters if hasattr(self.retriever, '_filters') else 'N/A'}")
                nodes = self.retriever.retrieve(query_str)
                print(f"[TransportationTool] Retriever found {len(nodes) if nodes else 0} nodes")
                
                if nodes:
                    for i, node in enumerate(nodes[:3]):  # Show first 3 nodes
                        metadata = node.metadata if hasattr(node, "metadata") else {}
                        node_text = node.text[:100] if hasattr(node, "text") and node.text else "No text"
                        print(f"[TransportationTool] Node {i+1}:")
                        print(f"  - Text preview: {node_text}")
                        print(f"  - Metadata: {metadata}")
                else:
                    print(f"[TransportationTool] WARNING: Retriever returned no nodes!")
                    # Try without filters to see if there are any stations at all
                    print(f"[TransportationTool] Checking if ANY transportation nodes exist (no filters)...")
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
                        print(f"[TransportationTool] Found {len(all_nodes) if all_nodes else 0} transportation nodes total (no zip filter)")
                        if all_nodes:
                            for i, node in enumerate(all_nodes[:3]):
                                metadata = node.metadata if hasattr(node, "metadata") else {}
                                print(f"[TransportationTool] Sample node {i+1} zip: {metadata.get('zip', 'N/A')}, queried_zip: {metadata.get('queried_zip', 'N/A')}")
                    except Exception as e2:
                        print(f"[TransportationTool] Could not check unfiltered nodes: {str(e2)}")
            except Exception as e:
                print(f"[TransportationTool] ERROR retrieving nodes: {str(e)}")
                import traceback
                traceback.print_exc()
            
            # Check response synthesizer
            if hasattr(self.base_engine, "response_synthesizer"):
                print(f"[TransportationTool] Query engine has response_synthesizer: {type(self.base_engine.response_synthesizer)}")
            else:
                print(f"[TransportationTool] WARNING: Query engine has no response_synthesizer attribute")
            
            # Now try the actual query
            try:
                print(f"[TransportationTool] Calling base query engine...")
                response = await self.base_engine._aquery(query_bundle)
                print(f"[TransportationTool] Base query engine returned response")
                
                self._debug_response(response, query_str)
                
                print(f"[TransportationTool] ===== DEBUG END =====\n")
                return response
                
            except Exception as e:
                print(f"[TransportationTool] ERROR in query: {str(e)}")
                import traceback
                traceback.print_exc()
                print(f"[TransportationTool] ===== DEBUG END (ERROR) =====\n")
                raise e
        
        def _debug_response(self, response: Response, query_str: str):
            """Debug helper to inspect response object."""
            # Check response structure
            print(f"[TransportationTool] Response type: {type(response)}")
            print(f"[TransportationTool] Response attributes: {[a for a in dir(response) if not a.startswith('__')]}")
            
            # Check if response has source_nodes
            if hasattr(response, "source_nodes"):
                print(f"[TransportationTool] Response has {len(response.source_nodes) if response.source_nodes else 0} source_nodes")
            
            # Extract response text
            response_text = ""
            if hasattr(response, "response"):
                response_text = str(response.response) if response.response else ""
                print(f"[TransportationTool] response.response: {response_text[:200] if response_text else 'EMPTY'}")
            elif hasattr(response, "text"):
                response_text = response.text if response.text else ""
                print(f"[TransportationTool] response.text: {response_text[:200] if response_text else 'EMPTY'}")
            else:
                response_text = str(response) if response else ""
                print(f"[TransportationTool] str(response): {response_text[:200] if response_text else 'EMPTY'}")
            
            print(f"[TransportationTool] Response text length: {len(response_text)}")
            print(f"[TransportationTool] Response text is empty: {not response_text or response_text.strip() == ''}")
            
            if not response_text or response_text.strip() == "":
                print(f"[TransportationTool] ERROR: Empty response detected!")
                print(f"[TransportationTool] Full response object: {response}")
                
                # Check if response has any other attributes that might contain data
                for attr in dir(response):
                    if not attr.startswith("_"):
                        try:
                            attr_value = getattr(response, attr)
                            if attr_value and attr not in ["response", "text"]:
                                print(f"[TransportationTool] response.{attr}: {str(attr_value)[:100]}")
                        except Exception:
                            pass
    
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

