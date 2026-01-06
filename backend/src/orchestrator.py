"""
Orchestrator: Initializes SubQuestionQueryEngine with dynamically loaded bundles.

The orchestrator pattern centralizes the initialization of the SubQuestionQueryEngine
and dynamically registers tools from the bundles/ directory.
"""

from typing import List, Optional, Any
from llama_index.core.query_engine import SubQuestionQueryEngine
from llama_index.core.tools import QueryEngineTool
from llama_index.core.callbacks import CallbackManager
from llama_index.core.question_gen.llm_generators import LLMQuestionGenerator
from llama_index.core.output_parsers.base import BaseOutputParser, StructuredOutput
from llama_index.core.question_gen.types import SubQuestion
import json
from src.debug_utils import setup_global_observability
from src.bundles.solar import get_tool as get_solar_tool
from src.bundles.transportation import get_tool as get_transportation_tool
from src.bundles.utility import get_tool as get_utility_tool
from src.bundles.buildings import get_tool as get_buildings_tool


class RobustSubQuestionOutputParser(BaseOutputParser):
    """
    Custom output parser that handles cases where LLM returns multiple JSON objects.
    Extracts the last valid JSON object from the output.
    """
    
    def parse(self, output: str) -> Any:
        """Parse output, handling multiple JSON objects by using the last valid one."""
        # Try to find all JSON objects in the output
        json_objects = []
        
        # First, try to parse as-is (single JSON)
        try:
            json_dict = json.loads(output.strip())
            if isinstance(json_dict, dict):
                json_objects.append(json_dict)
        except json.JSONDecodeError:
            pass
        
        # If that fails, try to extract JSON objects by finding balanced braces
        if not json_objects:
            i = len(output) - 1
            while i >= 0:
                if output[i] == '}':
                    brace_count = 0
                    start_pos = i
                    end_pos = i + 1
                    
                    for j in range(i, -1, -1):
                        if output[j] == '}':
                            brace_count += 1
                        elif output[j] == '{':
                            brace_count -= 1
                            if brace_count == 0:
                                start_pos = j
                                break
                    
                    if brace_count == 0:
                        json_str = output[start_pos:end_pos]
                        try:
                            json_dict = json.loads(json_str)
                            if isinstance(json_dict, dict):
                                if "items" in json_dict or (isinstance(json_dict, dict) and len(json_dict) > 0):
                                    json_objects.append(json_dict)
                                    i = start_pos - 1
                                    continue
                        except json.JSONDecodeError:
                            pass
                i -= 1
        
        if not json_objects:
            try:
                from llama_index.core.output_parsers.utils import parse_json_markdown
                json_dict = parse_json_markdown(output)
                if json_dict:
                    json_objects.append(json_dict)
            except Exception:
                pass
        
        if not json_objects:
            raise ValueError(f"No valid JSON found in output: {output[:500]}")
        
        # Filter and prioritize sub-question structures
        valid_json_objects = []
        prioritized_objects = []
        
        for obj in json_objects:
            if isinstance(obj, dict):
                if "items" in obj:
                    prioritized_objects.append(obj)
                elif "sub_question" in obj and "tool_name" in obj:
                    valid_json_objects.append(obj)
                else:
                    all_strings = all(isinstance(v, str) for v in obj.values())
                    if not all_strings:
                        valid_json_objects.append(obj)
        
        if prioritized_objects:
            json_dict = prioritized_objects[-1]
        elif valid_json_objects:
            json_dict = valid_json_objects[-1]
        else:
            if json_objects:
                tool_desc_dict = json_objects[-1]
                if isinstance(tool_desc_dict, dict):
                    all_strings = all(isinstance(v, str) for v in tool_desc_dict.values())
                    if all_strings:
                        raise ValueError(
                            f"LLM returned tool descriptions instead of sub-questions. "
                            f"Expected format: {{'items': [{{'sub_question': '...', 'tool_name': '...'}}]}}. "
                            f"Got: {json.dumps(tool_desc_dict, indent=2)[:500]}"
                        )
            json_dict = json_objects[-1] if json_objects else {}
        
        # Handle 'items' key
        if "items" in json_dict:
            items = json_dict["items"]
            if not isinstance(items, list):
                raise ValueError(f"'items' key should contain a list, got: {type(items)}")
            
            sub_questions = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if "sub_question" not in item or "tool_name" not in item:
                    continue
                sub_questions.append(item)
            
            if not sub_questions:
                raise ValueError(f"No valid sub-questions found in items: {items}")
            
            # Convert to SubQuestion objects
            parsed_sub_questions = []
            for q in sub_questions:
                try:
                    parsed_sub_questions.append(SubQuestion.parse_obj(q))
                except Exception as e:
                    print(f"Warning: Failed to parse sub-question: {q}, error: {str(e)}")
                    continue
            
            if not parsed_sub_questions:
                raise ValueError(f"No valid sub-questions found in items: {items}")
            
            return StructuredOutput(raw_output=output, parsed_output=parsed_sub_questions)
        
        # Single sub-question format
        if "sub_question" in json_dict and "tool_name" in json_dict:
            try:
                sub_question = SubQuestion.parse_obj(json_dict)
                return StructuredOutput(raw_output=output, parsed_output=[sub_question])
            except Exception as e:
                raise ValueError(f"Failed to parse single sub-question: {json_dict}, error: {str(e)}")
        
        raise ValueError(f"Invalid JSON structure: {json_dict}")
    
    def format(self, prompt_template: str) -> str:
        """Format prompt template."""
        return prompt_template


class ToolNameMappingParser(BaseOutputParser):
    """
    Wrapper parser that maps incorrect tool names to correct ones.
    
    LLM sometimes uses example tool names from the prompt instead of actual tool names.
    This parser fixes those mappings.
    """
    
    def __init__(self, base_parser: BaseOutputParser, tool_names: List[str]):
        self.base_parser = base_parser
        self.tool_names = tool_names
    
    def parse(self, output: str) -> Any:
        """Parse output and map incorrect tool names to correct ones."""
        result = self.base_parser.parse(output)
        # Map any incorrect tool names to valid ones
        if hasattr(result, "parsed_output"):
            for sub_q in result.parsed_output:
                if sub_q.tool_name not in self.tool_names:
                    # Map based on question content
                    sub_q_text_lower = sub_q.sub_question.lower()
                    # Distinguish between charging station questions vs charging cost questions
                    # Priority: Check for cost/savings/rate keywords FIRST (these are utility questions)
                    if any(keyword in sub_q_text_lower for keyword in [
                        "electricity", "utility", "rate", "cost", "kwh", "price", "bill",
                        "time-of-use", "off-peak", "peak rate", "charging cost", "charging at",
                        "savings", "compare", "monthly", "annual"
                    ]):
                        sub_q.tool_name = "utility_tool"
                    # Then check for location keywords (these are transportation questions)
                    elif any(keyword in sub_q_text_lower for keyword in [
                        "charging station", "charging stations", "where to charge", "where can i charge",
                        "charger location", "charging location", "nearest charging", "find charging",
                        "dc fast", "level 2", "station near"
                    ]):
                        sub_q.tool_name = "transportation_tool"
                    # Generic "charging" keyword - check context
                    elif "charging" in sub_q_text_lower:
                        # If it mentions cost/savings/rate/price/bill/time, it's utility
                        if any(cost_word in sub_q_text_lower for cost_word in [
                            "cost", "savings", "rate", "price", "bill", "at 11", "at 12", "time"
                        ]):
                            sub_q.tool_name = "utility_tool"
                        # Otherwise default to transportation (finding stations)
                        else:
                            sub_q.tool_name = "transportation_tool"
                    elif any(keyword in sub_q_text_lower for keyword in [
                        "investment", "sizing", "roi", "optimal size", "optimal system", "npv",
                        "net present value", "financial analysis", "economic analysis", "optimal design",
                        "cost-benefit", "payback", "optimize", "optimization", "optimal solar",
                        "optimal storage", "optimal energy system"
                    ]):
                        sub_q.tool_name = "optimization_tool"
                    elif any(keyword in sub_q_text_lower for keyword in [
                        "solar", "solar panel", "solar energy", "solar production", "solar generation",
                        "solar savings", "solar offset", "solar payback", "photovoltaic", "pv system"
                    ]):
                        sub_q.tool_name = "solar_production_tool"
                    elif any(keyword in sub_q_text_lower for keyword in [
                        "building code", "energy code", "iecc", "ashrae", "building standard",
                        "efficiency requirement", "code compliance", "building performance",
                        "energy efficiency standard", "building energy code", "building codes",
                        "energy standards", "building efficiency", "lower bill", "reduce bill",
                        "lower electricity", "reduce electricity", "energy efficiency measure",
                        "energy retrofit", "improve efficiency", "reduce consumption"
                    ]):
                        sub_q.tool_name = "buildings_tool"
                    else:
                        # Default to transportation_tool
                        sub_q.tool_name = "transportation_tool"
        return result
    
    def format(self, prompt_template: str) -> str:
        """Format prompt template."""
        return self.base_parser.format(prompt_template)


class RAGOrchestrator:
    """
    Orchestrator for managing SubQuestionQueryEngine with modular bundles.
    
    Dynamically loads tools from bundles and initializes the SubQuestionQueryEngine
    with proper routing and observability.
    """
    
    def __init__(
        self,
        llm,
        vector_store_service,
        callback_manager: Optional[CallbackManager] = None,
        enable_observability: bool = True,
        observability_handler_type: str = "simple"
    ):
        """
        Initialize the orchestrator.
        
        Args:
            llm: LLM instance for query processing
            vector_store_service: Vector store service for retrievers
            callback_manager: Optional callback manager
            enable_observability: Whether to enable observability (creates callback manager)
            observability_handler_type: Ignored (kept for backward compatibility)
        """
        self.llm = llm
        self.vector_store_service = vector_store_service
        
        # Set up callback manager if enabled
        if enable_observability:
            self.callback_manager = setup_global_observability(
                handler_type=observability_handler_type,
                callback_manager=callback_manager
            )
        else:
            self.callback_manager = callback_manager
        
        # Set Settings.llm to ensure SubQuestionQueryEngine uses the configured LLM
        from llama_index.core.settings import Settings
        Settings.llm = llm
    
    def get_custom_prompt_template(self) -> str:
        """
        Get the custom prompt template for sub-question generation.
        
        Returns:
            Prompt template string
        """
        return """\
Given a user question and tools, output relevant sub-questions in JSON format.

RULES:
1. Create NEW sub-questions based on the user's question
2. Do NOT copy tool descriptions
3. Output format: {{"items": [{{"sub_question": "...", "tool_name": "..."}}]}}
4. IMPORTANT: If the year is 2026 and the question involves residential solar financing, 
   explicitly compare the 0% purchase credit vs the 30% lease credit for homeowners.

TOOL USAGE:
- transportation_tool: Finding EV charging stations, locations, charger types
- utility_tool: Electricity rates, costs, time-of-use rates, utility info
- solar_production_tool: Solar energy production estimates (kWh) for location/system size
- buildings_tool: Building energy codes, efficiency standards, code compliance, building performance, energy efficiency measures to reduce bills
- optimization_tool: Investment analysis, ROI, optimal sizing, NPV. MUST include location (zip/city/state/coordinates) in sub-question.

TAX CREDIT CONTEXT (2026 OBBBA):
- Residential Purchase: 0% federal tax credit (expired in 2025)
- Residential Lease: 30% federal tax credit (still eligible)
- Commercial: 30% if construction starts before July 4, 2026

EXAMPLES:

Q: "What are the nearest DC fast charging stations and electricity cost?"
A: {{"items": [{{"sub_question": "Where are the nearest DC fast charging stations?", "tool_name": "transportation_tool"}}, {{"sub_question": "What is the electricity cost per kWh?", "tool_name": "utility_tool"}}]}}

Q: "Compare savings: charging at 11 PM vs 4kW solar in zip 45424"
A: {{"items": [{{"sub_question": "What are electricity rates including time-of-use for zip 45424?", "tool_name": "utility_tool"}}, {{"sub_question": "What is solar production for 4kW system in zip 45424?", "tool_name": "solar_production_tool"}}]}}

Q: "Optimal solar and storage size for zip 80202? ROI?"
A: {{"items": [{{"sub_question": "What is optimal solar/storage size and NPV for zip 80202?", "tool_name": "optimization_tool"}}]}}

Q: "What's the ROI for solar in zip 80202 in 2026?"
A: {{"items": [
    {{"sub_question": "What is optimal solar/storage size and NPV for zip 80202 with purchase financing (0% ITC)?", "tool_name": "optimization_tool"}},
    {{"sub_question": "What is optimal solar/storage size and NPV for zip 80202 with lease financing (30% ITC)?", "tool_name": "optimization_tool"}}
]}}

Q: "Should I buy or lease solar panels for my home in 2026?"
A: {{"items": [
    {{"sub_question": "What is optimal solar/storage size and NPV for residential solar purchase in 2026 (0% ITC)?", "tool_name": "optimization_tool"}},
    {{"sub_question": "What is optimal solar/storage size and NPV for residential solar lease in 2026 (30% ITC)?", "tool_name": "optimization_tool"}}
]}}

Q: "Where is the cheapest place in Florida to charge my EV?"
A: {{"items": [
    {{"sub_question": "Where are EV charging stations in Florida?", "tool_name": "transportation_tool"}},
    {{"sub_question": "What are the electricity rates and costs for charging in Florida?", "tool_name": "utility_tool"}}
]}}

Q: "What's the most affordable place to charge near me?"
A: {{"items": [
    {{"sub_question": "Where are EV charging stations near me?", "tool_name": "transportation_tool"}},
    {{"sub_question": "What are the electricity rates and costs for charging?", "tool_name": "utility_tool"}}
]}}

Q: "How do I lower my electricity bill?"
A: {{"items": [
    {{"sub_question": "What are current electricity rates?", "tool_name": "utility_tool"}},
    {{"sub_question": "What are building energy efficiency standards and measures to reduce energy consumption?", "tool_name": "buildings_tool"}},
    {{"sub_question": "What is solar production potential to offset electricity costs?", "tool_name": "solar_production_tool"}}
]}}

CRITICAL RULE FOR COST + LOCATION QUESTIONS:
- If a question asks about "cheapest", "cheaper", "most affordable", "best price", "lowest cost", 
  or compares costs across locations, you MUST generate TWO sub-questions:
  1. One for finding locations/stations (transportation_tool)
  2. One for getting cost/rate information (utility_tool)
- This allows comparing costs across different locations to determine the cheapest option.

CRITICAL RULE FOR 2026 SOLAR ROI QUESTIONS:
- If the question mentions "ROI", "return on investment", "financial analysis", "NPV", "payback", or asks about buying/leasing solar in 2026, you MUST generate TWO separate sub-questions:
  1. One for purchase (0% ITC) - explicitly mention "purchase" and "0% ITC" in the sub-question
  2. One for lease (30% ITC) - explicitly mention "lease" and "30% ITC" in the sub-question
- Both sub-questions must call optimization_tool
- The final answer will compare both scenarios: "Under 2026 rules, buying with cash is non-viable (NPV=$0), but a lease is viable (NPV=$X) because the developer keeps the 30% credit."

YOUR TASK:
<Tools>
{tools_str}
</Tools>

<User Question>
{query_str}

<Output>
```json
{{
    "items": [
        {{
            "sub_question": "...",
            "tool_name": "..."
        }}
    ]
}}
```
"""
    
    def create_tools(
        self,
        top_k: int = 5,
        use_reranking: bool = False,
        rerank_top_n: int = 3,
        location_filters: Optional[List] = None,
        nrel_client=None,
        bcl_client=None,
        location_service=None,
        reopt_service=None
    ) -> List[QueryEngineTool]:
        """
        Create and return all tools from bundles.
        
        Args:
            top_k: Number of top results to retrieve
            use_reranking: Whether to use LLM reranking
            rerank_top_n: Number of results to rerank if reranking is enabled
            location_filters: Optional location-based metadata filters
            nrel_client: Optional NREL client (creates new if not provided)
            bcl_client: Optional BCL client (creates new if not provided)
            location_service: Optional location service (creates new if not provided)
            reopt_service: Optional REopt service (creates new if not provided)
            
        Returns:
            List of QueryEngineTool instances
        """
        tools = []
        
        # Create solar tool
        solar_tool = get_solar_tool(
            llm=self.llm,
            callback_manager=self.callback_manager,
            nrel_client=nrel_client,
            location_service=location_service
        )
        tools.append(solar_tool)
        
        # Create transportation tool
        transportation_tool = get_transportation_tool(
            llm=self.llm,
            vector_store_service=self.vector_store_service,
            callback_manager=self.callback_manager,
            top_k=top_k,
            use_reranking=use_reranking,
            rerank_top_n=rerank_top_n,
            location_filters=location_filters
        )
        tools.append(transportation_tool)
        
        # Create utility tool
        utility_tool = get_utility_tool(
            llm=self.llm,
            vector_store_service=self.vector_store_service,
            callback_manager=self.callback_manager,
            top_k=top_k,
            use_reranking=use_reranking,
            rerank_top_n=rerank_top_n,
            location_filters=location_filters
        )
        tools.append(utility_tool)
        
        # Create buildings tool
        buildings_tool = get_buildings_tool(
            llm=self.llm,
            vector_store_service=self.vector_store_service,
            callback_manager=self.callback_manager,
            top_k=top_k,
            use_reranking=use_reranking,
            rerank_top_n=rerank_top_n,
            location_filters=location_filters
        )
        tools.append(buildings_tool)
        
        # Create optimization tool if REopt service is provided
        if reopt_service:
            from src.bundles.optimization import get_tool as get_optimization_tool
            optimization_tool = get_optimization_tool(
                llm=self.llm,
                reopt_service=reopt_service,
                nrel_client=nrel_client,
                callback_manager=self.callback_manager
            )
            tools.append(optimization_tool)
        
        return tools
    
    def create_sub_question_query_engine(
        self,
        tools: List[QueryEngineTool],
        use_robust_parser: bool = True
    ) -> SubQuestionQueryEngine:
        """
        Create and configure SubQuestionQueryEngine with tools.
        
        Args:
            tools: List of QueryEngineTool instances
            use_robust_parser: Whether to use robust parser with tool name mapping
            
        Returns:
            Configured SubQuestionQueryEngine instance
        """
        # Create question generator with custom prompt template string
        if use_robust_parser:
            # Use robust parser with tool name mapping
            robust_parser = RobustSubQuestionOutputParser()
            tool_names = [tool.metadata.name for tool in tools]
            parser = ToolNameMappingParser(base_parser=robust_parser, tool_names=tool_names)
            
            question_generator = LLMQuestionGenerator.from_defaults(
                llm=self.llm,
                prompt_template_str=self.get_custom_prompt_template(),
                output_parser=parser
            )
        else:
            question_generator = LLMQuestionGenerator.from_defaults(
                llm=self.llm,
                prompt_template_str=self.get_custom_prompt_template()
            )
        
        # Create response synthesizer with custom prompt for comparing scenarios
        from llama_index.core.response_synthesizers import get_response_synthesizer
        from llama_index.core.response_synthesizers.type import ResponseMode
        from llama_index.core.prompts import PromptTemplate as ResponsePromptTemplate
        
        # Custom response synthesis prompt that emphasizes comparison for dual optimization calls
        response_prompt = """\
Context information is below.
---------------------
{context_str}
---------------------
Given the context information and not prior knowledge, answer the query.
If multiple optimization results are provided (purchase vs lease scenarios), 
you MUST compare them explicitly:

1. State the NPV for purchase scenario (0% ITC)
2. State the NPV for lease scenario (30% ITC)
3. Explain: "Under 2026 OBBBA rules, buying with cash is non-viable (NPV=$X), 
   but a lease is viable (NPV=$Y) because the developer keeps the 30% credit."
4. Highlight the key difference: homeowners lose the purchase tax credit in 2026, 
   but lease/PPA providers can still claim 30% and pass savings through lower rates.

Query: {query_str}
Answer: """
        
        response_synthesizer = get_response_synthesizer(
            llm=self.llm,
            response_mode=ResponseMode.COMPACT_ACCUMULATE,
            text_qa_template=ResponsePromptTemplate(response_prompt),
            callback_manager=self.callback_manager
        )
        
        # Create SubQuestionQueryEngine with custom response synthesizer
        # Note: callback_manager is inherited from tools, not passed directly
        router_query_engine = SubQuestionQueryEngine.from_defaults(
            question_gen=question_generator,
            query_engine_tools=tools,
            response_synthesizer=response_synthesizer
        )
        
        return router_query_engine

