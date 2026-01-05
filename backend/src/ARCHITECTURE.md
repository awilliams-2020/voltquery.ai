# Modular Tool-Bundle Architecture

This document describes the refactored modular tool-bundle architecture for the RAG system.

## Overview

The RAG system has been refactored into a modular architecture that supports vertical scalability by encapsulating domain logic into separate bundles. Each bundle exports a standardized `get_tool()` function that returns a `QueryEngineTool` with high-quality metadata.

## Directory Structure

```
backend/src/
├── __init__.py                 # Package exports
├── global_settings.py          # Centralized financial constants
├── debug_utils.py              # Observability utilities
├── orchestrator.py             # SubQuestionQueryEngine initialization
└── bundles/
    ├── __init__.py
    ├── solar/
    │   ├── __init__.py         # get_tool() function
    │   └── query_engine.py     # SolarQueryEngine implementation
    ├── transportation/
    │   └── __init__.py         # get_tool() function
    ├── utility/
    │   └── __init__.py         # get_tool() function
    └── optimization/
        └── __init__.py         # get_tool() function + OptimizationQueryEngine
```

## Components

### 1. GlobalSettings (`src/global_settings.py`)

Centralizes financial and analysis parameters used across all bundles:

- **Federal Tax Credit**: 30% (0.30)
- **Analysis Period**: 25 years
- **Discount Rates**: 6.24% (0.0624)
- **Tax Rates**: 26% (0.26)
- **Escalation Rates**: O&M 2.5%, Electricity 1.66%
- **Solar System Defaults**: Capacity, installed cost, O&M costs
- **Storage System Defaults**: Max kW and kWh

Usage:
```python
from src.global_settings import get_global_settings

settings = get_global_settings()
tax_credit = settings.federal_tax_credit_rate  # 0.30
analysis_years = settings.analysis_years  # 25
```

### 2. Bundles (`src/bundles/`)

Each bundle encapsulates domain-specific logic:

#### Solar Bundle (`src/bundles/solar/`)
- **Purpose**: Solar energy production estimates
- **API**: NREL PVWatts API
- **Tool Name**: `solar_production_tool`
- **Exports**: `get_tool(llm, callback_manager, nrel_client, location_service) -> QueryEngineTool`

#### Transportation Bundle (`src/bundles/transportation/`)
- **Purpose**: EV charging station location queries
- **Data Source**: Vector store index
- **Tool Name**: `transportation_tool`
- **Exports**: `get_tool(llm, vector_store_service, callback_manager, top_k, use_reranking, rerank_top_n, location_filters) -> QueryEngineTool`

#### Utility Bundle (`src/bundles/utility/`)
- **Purpose**: Electricity rates and utility cost queries
- **Data Source**: Vector store index
- **Tool Name**: `utility_tool`
- **Exports**: `get_tool(llm, vector_store_service, callback_manager, top_k, use_reranking, rerank_top_n, location_filters) -> QueryEngineTool`

#### Optimization Bundle (`src/bundles/optimization/`)
- **Purpose**: REopt optimization for solar/storage sizing and financial analysis
- **API**: NREL REopt v3 API
- **Tool Name**: `optimization_tool`
- **Exports**: `get_tool(llm, reopt_service, nrel_client, callback_manager) -> QueryEngineTool`

### 3. Orchestrator (`src/orchestrator.py`)

The `RAGOrchestrator` class manages the initialization of `SubQuestionQueryEngine` with dynamically loaded bundles.

**Key Features**:
- Dynamically creates tools from bundles
- Configures custom prompt template for sub-question generation
- Handles tool name mapping (fixes LLM routing errors)
- Integrates observability via callback manager

**Usage**:
```python
from src.orchestrator import RAGOrchestrator

orchestrator = RAGOrchestrator(
    llm=llm,
    vector_store_service=vector_store_service,
    enable_observability=True
)

# Create tools
tools = orchestrator.create_tools(
    top_k=5,
    use_reranking=False,
    nrel_client=nrel_client,
    location_service=location_service,
    reopt_service=reopt_service
)

# Create SubQuestionQueryEngine
router_query_engine = orchestrator.create_sub_question_query_engine(tools)
```

### 4. Debug Utils (`src/debug_utils.py`)

Provides observability integration with LlamaIndex callbacks:

```python
from src.debug_utils import setup_global_observability, enable_debug_mode

# Enable simple observability
callback_manager = setup_global_observability(handler_type="simple")

# Or enable debug mode (verbose logging)
enable_debug_mode()
```

## Integration with RAG Service

To integrate the new architecture into `RAGService`, replace the tool creation logic with:

```python
from src.orchestrator import RAGOrchestrator

# In RAGService.__init__ or query method:
orchestrator = RAGOrchestrator(
    llm=llm,
    vector_store_service=self.vector_store_service,
    enable_observability=True
)

# Create tools with location filters if available
location_filters = []  # Build from detected_location_info
tools = orchestrator.create_tools(
    top_k=top_k,
    use_reranking=use_reranking,
    rerank_top_n=rerank_top_n,
    location_filters=location_filters,
    nrel_client=self.nrel_client,
    location_service=self.location_service,
    reopt_service=self.reopt_service
)

# Create SubQuestionQueryEngine
router_query_engine = orchestrator.create_sub_question_query_engine(tools)
```

## Benefits

1. **Vertical Scalability**: Each bundle can be developed, tested, and deployed independently
2. **Standardized Interface**: All bundles export `get_tool()` with consistent signature
3. **Centralized Configuration**: GlobalSettings ensures consistent financial parameters
4. **Observability**: Built-in tracing of sub-questions across bundles
5. **Maintainability**: Domain logic is encapsulated and easier to understand
6. **Testability**: Each bundle can be tested in isolation

## Next Steps

1. Refactor `RAGService.query()` to use `RAGOrchestrator`
2. Update tests to use the new bundle architecture
3. Consider adding more bundles (e.g., `weather`, `grid`, `pricing`)
4. Add bundle-specific prompt templates if needed
5. Implement bundle versioning for backward compatibility

