# VoltQuery.ai - Complete Project Documentation

> **Last Updated**: 2026-01-06  
> **Status**: Living Document - Update this file when making architectural or significant implementation changes

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Technology Stack](#technology-stack)
4. [Key Features](#key-features)
5. [Project Structure](#project-structure)
6. [Key Workflows](#key-workflows)
7. [API Endpoints](#api-endpoints)
8. [Environment Variables](#environment-variables)
9. [Deployment](#deployment)
10. [Design Patterns](#design-patterns)
11. [Development Workflow](#development-workflow)
12. [Recent Changes & Improvements](#recent-changes--improvements)
13. [Dependencies & Version Constraints](#dependencies--version-constraints)
14. [Vector Store Architecture](#vector-store-architecture)
15. [SSE Streaming](#sse-streaming)
16. [Vector Store Freshness Strategy](#vector-store-freshness-strategy)
17. [Future Enhancements](#future-enhancements)

---

## Overview

**VoltQuery.ai** is a comprehensive RAG (Retrieval-Augmented Generation) SaaS application that provides AI-powered insights for electric vehicle (EV) infrastructure, electricity rates, solar energy production, and energy system optimization. The platform leverages multiple NREL (National Renewable Energy Laboratory) APIs and advanced AI orchestration to answer complex, multi-faceted questions about clean energy systems.

### Core Purpose

The application enables users to ask natural language questions about:
- **EV Charging Stations**: Find charging locations, connector types, and availability
- **Electricity Rates**: Compare utility rates, time-of-use pricing, and charging costs
- **Solar Energy**: Estimate solar production, savings, and system sizing
- **Energy Optimization**: Calculate ROI, NPV, and optimal system configurations

---

## Architecture

### High-Level Architecture

```
┌─────────────────┐
│   Frontend      │  Next.js 15 (App Router)
│   (Port 3000)   │  TypeScript, Tailwind CSS, Shadcn UI
└────────┬────────┘
         │ HTTP/REST
         │
┌────────▼────────┐
│   Backend       │  FastAPI (Python 3.12)
│   (Port 8000)   │  SQLAlchemy, LlamaIndex RAG
└────────┬────────┘
         │
    ┌────┴────┬──────────┬──────────────┐
    │         │          │              │
┌───▼───┐ ┌──▼───┐ ┌────▼────┐ ┌───────▼──────┐
│ NREL  │ │OpenEI│ │Supabase │ │   Gemini     │
│ APIs  │ │ URDB │ │pgvector │ │  1.5 Pro     │
└───────┘ └──────┘ └─────────┘ └──────────────┘
```

### Modular Tool-Bundle Architecture

The RAG system uses a modular architecture that supports vertical scalability by encapsulating domain logic into separate bundles. Each bundle exports a standardized `get_tool()` function that returns a `QueryEngineTool` with high-quality metadata.

#### Directory Structure

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
    ├── optimization/
    │   └── __init__.py         # get_tool() function + OptimizationQueryEngine
    └── buildings/
        └── __init__.py         # get_tool() function
```

#### Components

**1. GlobalSettings** (`src/global_settings.py`)
- Centralizes financial and analysis parameters used across all bundles
- Federal Tax Credit: 30% (0.30)
- Analysis Period: 25 years
- Discount Rates: 6.24% (0.0624)
- Tax Rates: 26% (0.26)
- Escalation Rates: O&M 2.5%, Electricity 1.66%

**2. Bundles** (`src/bundles/`)
Each bundle encapsulates domain-specific logic:
- **Solar Bundle**: Solar energy production estimates via NREL PVWatts API
- **Transportation Bundle**: EV charging station location queries via vector store
- **Utility Bundle**: Electricity rates and utility cost queries via vector store
- **Optimization Bundle**: REopt optimization for solar/storage sizing and financial analysis
- **Buildings Bundle**: Building code and energy efficiency queries

**3. Orchestrator** (`src/orchestrator.py`)
- Manages initialization of `SubQuestionQueryEngine` with dynamically loaded bundles
- Dynamically creates tools from bundles
- Configures custom prompt template for sub-question generation
- Handles tool name mapping (fixes LLM routing errors)
- Integrates observability via callback manager

---

## Technology Stack

### Frontend
- **Framework**: Next.js 15 with App Router
- **Language**: TypeScript
- **Styling**: Tailwind CSS + Shadcn UI components
- **Authentication**: Clerk (@clerk/nextjs v5.0.0)
- **Payments**: Stripe integration
- **State Management**: React hooks (useState, useEffect)
- **Icons**: Lucide React

### Backend
- **Framework**: FastAPI (Python 3.12)
- **Database**: Supabase PostgreSQL with pgvector extension
- **ORM**: SQLAlchemy 2.0
- **Authentication**: Clerk middleware (header-based: X-Clerk-User-Id, X-Clerk-Email)
- **API Client**: httpx (<0.25.0 for Supabase compatibility)
- **Environment**: python-dotenv, pydantic-settings

### AI & RAG
- **RAG Framework**: LlamaIndex (core >=0.10.5,<0.11.0)
- **LLM Options** (configurable via `LLM_MODE`):
  - Local: Ollama (llama-index-llms-ollama) - default for development
  - Cloud: Gemini 1.5 Pro (llama-index-llms-gemini)
  - Cloud: OpenAI (llama-index-llms-openai)
- **Embeddings**: 
  - Cloud: OpenAI text-embedding-3-small (1536 dimensions)
  - Local: Ollama nomic-embed-text (768 dimensions)
- **Vector Store**: Supabase pgvector (llama-index-vector-stores-supabase)
- **Query Engine**: SubQuestionQueryEngine with custom orchestration

### External APIs
- **NREL Alternative Fuels Data Center**: EV charging station data
- **NREL PVWatts API**: Solar production estimates
- **OpenEI URDB API**: Utility rate database
- **NREL REopt API**: Energy system optimization

---

## Key Features

### 1. Multi-Domain RAG System

The application uses a sophisticated **SubQuestionQueryEngine** pattern that breaks complex user questions into sub-questions and routes them to specialized tools:

#### Domain Bundles (`backend/src/bundles/`)

1. **Transportation Bundle** (`transportation/`)
   - Finds EV charging stations by location
   - Filters by connector type (J1772, CCS, CHAdeMO, Tesla)
   - Supports DC fast charging and Level 2 stations
   - Uses vector search over indexed station data

2. **Utility Bundle** (`utility/`)
   - Retrieves electricity rates from URDB
   - Supports time-of-use rate analysis
   - Calculates charging costs at different times
   - Compares utility rates across locations

3. **Solar Bundle** (`solar/`)
   - Estimates solar production using PVWatts API
   - Calculates system size, orientation, tilt
   - Provides monthly/annual production estimates
   - Integrates with location service for coordinates

4. **Optimization Bundle** (`optimization/`)
   - Uses NREL REopt API for energy system optimization
   - Calculates ROI, NPV, payback periods
   - Determines optimal solar/storage sizing
   - **2026 Tax Credit Awareness**: Handles OBBBA changes
     - Residential purchase: 0% ITC (expired 2025)
     - Residential lease: 30% ITC (still eligible)
     - Commercial: 30% if construction starts before July 4, 2026

5. **Buildings Bundle** (`buildings/`)
   - Building code and energy efficiency queries
   - Vector search over indexed building code documents

### 2. Intelligent Query Orchestration

The `RAGOrchestrator` (`backend/src/orchestrator.py`) manages:
- **Dynamic Tool Loading**: Loads tools from bundles at runtime
- **Sub-Question Generation**: Uses custom prompt templates to break queries
- **Tool Name Mapping**: Corrects LLM tool name errors automatically
- **Robust Parsing**: Handles malformed JSON responses from LLM
- **Response Synthesis**: Combines multiple tool results into coherent answers
- **Scenario Comparison**: Explicitly compares purchase vs lease scenarios for 2026 solar questions

### 3. Vector Store & Embeddings

- **Data Indexing**: EV stations, utility rates, building codes, and related documents are embedded and stored in Supabase pgvector
- **Semantic Search**: Uses vector similarity search to find relevant context
- **Reranking**: Optional LLM-based reranking for improved relevance
- **Location Filtering**: Metadata filters for geographic queries

### 4. SaaS Features

#### Authentication & Authorization
- Clerk-based authentication
- User context passed via headers to backend
- Protected API endpoints

#### Subscription Management
- **Free Tier**: 3 queries/month
- **Premium Tier**: Unlimited queries (configurable via Stripe)
- Query limits enforced per subscription plan
- Stripe webhook integration for subscription events

#### Query History
- Tracks all user queries
- Stores query text, responses, and metadata
- Query statistics dashboard

### 5. Caching & Performance

- **Response Caching**: TTL-based caching for expensive API calls
  - Utility rates: 24 hours
  - Solar estimates: 1 hour
  - Geocoding: 30 days
- **Circuit Breakers**: Prevents cascading failures from external APIs
- **Async Operations**: All I/O operations use async/await

### 6. Stability & Observability

- **Structured Logging**: JSON-formatted logs for query events, API calls, circuit breaker state changes
- **Circuit Breaker Pattern**: Prevents calling failing services repeatedly
- **Input Validation**: Validates user inputs before processing
- **Error Handling**: Graceful degradation and clear error messages
- **Retry Logic**: Exponential backoff retry service for transient failures
- **Query Refinement**: Preprocesses queries to improve retrieval accuracy
- **Freshness Checking**: TTL-based freshness checking for vector store data

---

## Project Structure

```
voltquery.ai/
├── backend/
│   ├── app/
│   │   ├── routers/          # API endpoints (thin controllers)
│   │   │   ├── stations.py   # EV station endpoints
│   │   │   ├── rag.py        # RAG query endpoint
│   │   │   ├── electricity.py # Electricity rate endpoints
│   │   │   ├── urdb.py       # URDB endpoints
│   │   │   ├── stripe.py     # Payment endpoints
│   │   │   └── history.py    # Query history endpoints
│   │   ├── services/         # Business logic layer
│   │   │   ├── rag_service.py        # Main RAG orchestration
│   │   │   ├── nrel_client.py        # NREL API client
│   │   │   ├── bcl_client.py         # Building Component Library client
│   │   │   ├── vector_store_service.py # Vector DB operations
│   │   │   ├── cache_service.py      # Response caching
│   │   │   ├── circuit_breaker.py    # Failure protection
│   │   │   ├── location_service.py   # Geocoding
│   │   │   ├── logger_service.py     # Structured logging
│   │   │   ├── validators.py         # Input validation
│   │   │   ├── reopt_service.py      # REopt API client
│   │   │   ├── freshness_checker.py  # Vector store freshness checking
│   │   │   ├── query_refiner.py      # Query preprocessing
│   │   │   ├── retry_service.py      # Retry logic with exponential backoff
│   │   │   ├── document_service.py   # Document conversion utilities
│   │   │   ├── rag_settings.py       # RAG configuration settings
│   │   │   ├── stripe_service.py    # Stripe integration
│   │   │   ├── urdb_service.py       # URDB API client
│   │   │   └── user_service.py      # User management
│   │   ├── models/           # SQLAlchemy ORM models
│   │   │   ├── user.py
│   │   │   ├── query.py
│   │   │   └── subscription.py
│   │   └── middleware/       # Auth, CORS, etc.
│   ├── src/
│   │   ├── orchestrator.py   # RAG orchestrator
│   │   ├── global_settings.py # Financial constants
│   │   ├── debug_utils.py    # Observability utilities
│   │   └── bundles/          # Domain-specific tools
│   │       ├── transportation/
│   │       ├── utility/
│   │       ├── solar/
│   │       ├── optimization/
│   │       └── buildings/
│   └── migrations/           # Database migrations
├── frontend/
│   ├── app/                  # Next.js App Router
│   │   ├── (auth)/           # Auth routes
│   │   ├── history/          # Query history page
│   │   └── page.tsx          # Main dashboard
│   ├── components/
│   │   ├── rag-query-form.tsx    # Query input form
│   │   ├── rag-response-card.tsx # Response display
│   │   └── ui/               # Shadcn UI components
│   └── lib/
│       └── utils.ts          # Utility functions
└── docker-compose.yml        # Multi-container setup
```

---

## Key Workflows

### 1. User Query Flow

```
User Question
    ↓
Frontend: RAGQueryForm component
    ↓
POST /api/rag/query
    ↓
Backend: RAGService.process_query()
    ↓
RAGOrchestrator.create_sub_question_query_engine()
    ↓
LLM generates sub-questions
    ↓
SubQuestionQueryEngine routes to tools:
    - transportation_tool → Vector search → NREL API (if needed)
    - utility_tool → Vector search → URDB API (if needed)
    - solar_production_tool → PVWatts API
    - optimization_tool → REopt API
    - buildings_tool → Vector search → BCL API (if needed)
    ↓
Response synthesizer combines results
    ↓
Return formatted answer with citations
```

### 2. EV Station Search Flow

```
User: "Find DC fast charging stations in zip 80202"
    ↓
Sub-question: "Where are DC fast charging stations in zip 80202?"
    ↓
transportation_tool:
    1. Geocode zip → coordinates
    2. Vector search for stations near coordinates
    3. Filter by DC fast charging capability
    4. Return top results
    ↓
Response: List of stations with addresses, connector types, etc.
```

### 3. Solar ROI Analysis Flow (2026)

```
User: "What's the ROI for solar in zip 80202 in 2026?"
    ↓
Orchestrator generates TWO sub-questions:
    1. "Optimal solar/storage size and NPV for zip 80202 with purchase (0% ITC)?"
    2. "Optimal solar/storage size and NPV for zip 80202 with lease (30% ITC)?"
    ↓
Both call optimization_tool with different financing scenarios
    ↓
Response synthesizer compares:
    - Purchase NPV: $0 (non-viable due to 0% credit)
    - Lease NPV: $X (viable due to 30% credit)
    ↓
Final answer explains: "Under 2026 OBBBA rules, buying with cash is 
non-viable, but a lease is viable because the developer keeps the 30% credit."
```

---

## API Endpoints

### Main Endpoints

- `POST /api/rag/query-stream` - Main RAG query endpoint with SSE streaming
  - Body: `{ "question": "...", "zip_code": "80202" (optional), "top_k": 5 }`
  - Returns: Server-Sent Events stream with event types: `status`, `tool`, `chunk`, `done`, `error`
  - Authentication: Required (Clerk headers)
  - Note: This is the primary query endpoint. The non-streaming endpoint has been removed.

- `POST /api/rag/index-stations` - Index EV stations for a zip code
  - Body: `{ "zip_code": "80202", "limit": 50 }`
  - Returns: `{ "indexed": 10, "failed": 0, "zip_code": "80202" }`

- `POST /api/rag/bulk-index-state` - Bulk index all stations for a state
  - Body: `{ "state": "OH", "batch_size": 100, "limit": null }`
  - Returns: Bulk indexing results

- `POST /api/fetch-stations` - Direct EV station lookup
  - Body: `{ "zip_code": "80202" }`
  - Returns: `{ "zip_code": "80202", "stations": [...] }`

- `POST /api/utility-rates` - Get utility rates by location
  - Body: `{ "location": "80202" }` or `{ "lat": 39.7392, "lon": -104.9903 }`
  - Returns: Utility rate data

- `POST /api/utility-rates/zip` - Get utility rates by zip code
  - Body: `{ "zip_code": "80202" }`
  - Returns: Utility rate data

- `POST /api/urdb/fetch` - Fetch URDB data
  - Body: URDB query parameters
  - Returns: URDB rate data

- `POST /api/urdb/fetch-by-state` - Fetch URDB data by state
  - Body: `{ "state": "CO" }`
  - Returns: Task ID for async processing

- `GET /api/urdb/status/{task_id}` - Check URDB fetch status
  - Returns: Task status and results

- `GET /api/history/queries` - Get user query history
  - Headers: `X-Clerk-User-Id`, `X-Clerk-Email`
  - Returns: List of user queries

- `GET /api/history/stats` - Query usage statistics
  - Headers: `X-Clerk-User-Id`, `X-Clerk-Email`
  - Returns: `{ "queries_used": 5, "query_limit": 10, "plan": "free" }`

- `POST /api/stripe/create-checkout` - Create Stripe checkout session
  - Returns: `{ "url": "https://checkout.stripe.com/..." }`

- `POST /api/stripe/create-portal` - Create Stripe customer portal session
  - Returns: `{ "url": "https://billing.stripe.com/..." }`

- `POST /api/stripe/cancel-subscription` - Cancel subscription
  - Returns: Cancellation confirmation

- `POST /api/stripe/webhook` - Stripe webhook endpoint
  - Handles subscription events

- `GET /api/clerk/webhook` - Clerk webhook endpoint (GET)
- `POST /api/clerk/webhook` - Clerk webhook endpoint (POST)
  - Handles user authentication events

- `POST /api/llm/chat` - Direct LLM chat endpoint
  - Body: `{ "message": "..." }`
  - Returns: LLM response

- `GET /api/llm/info` - Get LLM service information
  - Returns: LLM configuration and status

---

## Environment Variables

### Backend
- `NREL_API_KEY` - NREL API key (required)
- `LLM_MODE` - LLM mode: `"local"` (Ollama), `"cloud"` (Gemini), or `"openai"` (default: `"local"`)
- `GEMINI_API_KEY` - Google Gemini API key (required if `LLM_MODE=cloud`)
- `OPENAI_API_KEY` - OpenAI API key (required if `LLM_MODE=openai`)
- `SUPABASE_URL` - Supabase project URL (optional, for REST API)
- `SUPABASE_KEY` - Supabase service role key (optional, for REST API)
- `SUPABASE_DB_URL` - Supabase PostgreSQL connection string (preferred)
- `DATABASE_URL` - Database connection string (fallback if `SUPABASE_DB_URL` not set)
- `SUPABASE_TABLE_NAME` - Vector store table name (default: `energy_documents`)
- `STRIPE_SECRET_KEY` - Stripe secret key (required for payments)
- `CLERK_SECRET_KEY` - Clerk secret key (required for authentication)
- `FRONTEND_URL` - Frontend URL for CORS (default: `http://localhost:3000`)
- `OLLAMA_BASE_URL` - Ollama server URL (default: `http://localhost:11434`)
- `OLLAMA_MODEL` - Ollama model name (default: `llama2`)
- `OLLAMA_EMBEDDING_MODEL` - Ollama embedding model (default: `nomic-embed-text`)

### Frontend
- `NEXT_PUBLIC_API_URL` - Backend API URL (default: `http://localhost:8000`)
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` - Clerk publishable key (required)
- `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` - Stripe publishable key (required for payments)

---

## Deployment

The project uses Docker Compose for containerized deployment:

```yaml
services:
  backend:  # FastAPI on port 8000
  frontend: # Next.js on port 3000
```

Both services include:
- Health checks
- Volume mounts for development
- Network isolation
- Environment variable configuration

---

## Design Patterns

1. **Service Layer Pattern**: Business logic separated from API routes
2. **Dependency Injection**: Services receive dependencies via constructor
3. **Circuit Breaker Pattern**: Protects against external API failures
4. **Caching Strategy**: TTL-based caching for expensive operations
5. **Modular Bundles**: Domain-specific tools organized in bundles
6. **Sub-Question Decomposition**: Complex queries broken into sub-queries
7. **Response Synthesis**: Multiple tool results combined intelligently

---

## Development Workflow

1. **Backend**: Run `uvicorn app.main:app --reload` on port 8000
2. **Frontend**: Run `npm run dev` on port 3000
3. **Database**: Supabase handles migrations automatically
4. **Testing**: pytest for backend, Jest for frontend (if configured)

---

## Recent Changes & Improvements

### Stability Improvements
- ✅ Structured logging with JSON format
- ✅ Response caching with TTL-based expiration
- ✅ Circuit breaker pattern for external APIs
- ✅ Input validation service
- ✅ Retry logic with exponential backoff
- ✅ Query refinement and preprocessing
- ✅ Freshness checking for vector store data

### Architecture Improvements
- ✅ Modular bundle architecture for vertical scalability
- ✅ Centralized global settings for financial constants
- ✅ RAG orchestrator for dynamic tool loading

### Performance Optimizations
- ✅ Vector search with metadata filtering
- ✅ Response caching reduces API calls by ~70-90%
- ✅ Async operations throughout
- ✅ Bulk indexing scripts for development

### Notable Features

**2026 Tax Credit Awareness**
- Automatically generates purchase vs lease comparison queries
- Explains tax credit differences in responses
- Uses correct ITC percentages for each scenario

**Robust Error Handling**
- Custom JSON parsers handle malformed LLM responses
- Tool name mapping corrects LLM routing errors
- Circuit breakers prevent cascading failures
- Comprehensive logging for debugging
- **Rate Limit Handling**: All external APIs (NREL Stations, Utility Rates, PVWatts, REopt) handle HTTP 429 rate limit errors with descriptive messages, rate limit header extraction, and proper error propagation

---

## Dependencies & Version Constraints

### Known Conflicts

**HTTPX Version Conflict**
- **Supabase** requires: `httpx<0.25.0,>=0.24.0`
- **Ollama** requires: `httpx>=0.27`
- **Resolution**: Keep `httpx==0.24.1` for Supabase compatibility. The `ollama` package will show a warning, but `llama-index-llms-ollama` should still work because LlamaIndex packages manage their own HTTP clients internally.

**Pydantic Version**
- **Required**: `pydantic>=2.11.5` (required by llama-index packages)
- **Compatible with**: FastAPI 0.109.0

**LlamaIndex Version Constraints**
- **Core**: `llama-index-core>=0.10.5,<0.11.0` (all integration packages require core <0.11.0)
- **Note**: RouterQueryEngine uses `LLMSingleSelector` (in core) instead of `PydanticSingleSelector` to avoid requiring `llama-index-program-openai` (which has version conflicts with core 0.10.x)

**Pillow Version**
- **Required**: `pillow>=10.2.0,<11.0.0` (required by `llama-index-llms-gemini`)

---

## Vector Store Architecture

### How Data is Stored

The `energy_documents` table in Supabase stores **vector embeddings** of documents, not raw records. This is how LlamaIndex's SupabaseVectorStore works.

**Table Structure**:
- `id` (UUID) - Unique identifier for each document
- `content` (TEXT) - The text content of the document (e.g., station description)
- `metadata` (JSONB) - Metadata about the document (city, state, zip, domain, etc.)
- `embedding` (vector) - The vector embedding of the content (768 or 1536 dimensions)
- `created_at` (TIMESTAMP) - When the document was created
- `updated_at` (TIMESTAMP) - When the document was last updated

**What Gets Stored**:
1. Station/utility/building data is converted to `Document` objects with:
   - `text`: Formatted description
   - `metadata`: JSON object with `domain`, `station_id`, `city`, `state`, `zip`, `network`, etc.
2. Documents are embedded using the embedding model (Ollama or OpenAI)
3. Embeddings are stored in the `energy_documents` table

**Important Notes**:
- Both stations AND utility rates are stored in the same `energy_documents` table
- They're differentiated by the `domain` field in metadata (`transportation` vs `utility` vs `buildings`)
- The table name `energy_documents` is configurable via `SUPABASE_TABLE_NAME` env var
- Vector dimensions: 768 (Ollama) or 1536 (OpenAI) - must match your `LLM_MODE`

### Troubleshooting Vector Store

**Check if data exists**:
```sql
-- Check total count
SELECT COUNT(*) FROM energy_documents;

-- See sample records
SELECT 
    id,
    LEFT(content, 100) as content_preview,
    metadata->>'city' as city,
    metadata->>'state' as state,
    metadata->>'domain' as domain,
    created_at
FROM energy_documents
LIMIT 10;

-- Check metadata distribution
SELECT 
    metadata->>'domain' as domain,
    COUNT(*) as count
FROM energy_documents
GROUP BY metadata->>'domain';
```

**Common Issues**:
- **Table appears empty**: Check table name, verify insertion errors in logs, confirm correct database
- **Queries don't work**: Check metadata filters match stored keys, verify embedding dimension matches LLM_MODE, ensure vector index exists (`energy_documents_embedding_idx`)

---

## SSE Streaming

### Overview

Server-Sent Events (SSE) streaming provides real-time progress updates for RAG queries, improving user experience with transparent progress feedback.

### Implementation

**Backend Endpoint**: `POST /api/rag/query-stream`
- Returns `StreamingResponse` with `text/event-stream` media type
- Emits SSE events for progress updates, tool calls, and final response
- Handles errors gracefully and saves query history after completion

**Event Types**:
- `status`: Progress updates (analyzing, searching, retrieving, synthesizing)
- `tool`: Tool call notifications (transportation_tool, utility_tool, solar_production_tool, optimization_tool)
- `chunk`: Answer text chunks (ready for future LLM streaming support)
- `done`: Final response with sources and metadata
- `error`: Error messages

**Frontend Integration**:
- Uses `ReadableStream` API to read SSE stream
- Parses SSE format: `event: <type>\ndata: <json>\n\n`
- Updates UI in real-time based on event types
- Shows actual progress stages from backend

### Benefits

1. **Real-time Feedback**: Users see actual progress instead of simulated stages
2. **Transparency**: Shows which tools are being called and when
3. **Better UX**: No more waiting with no feedback
4. **Future-ready**: Structure supports streaming answer chunks when LLM streaming is added

**Note**: The non-streaming `/api/rag/query` endpoint has been removed. All queries now use the streaming endpoint `/api/rag/query-stream`.

---

## Vector Store Freshness Strategy

### Two-Layer Caching Architecture

The system uses a **two-layer caching strategy**:

```
User Query
    ↓
[RAGService] Check Vector Store
    ├─ Hit? → Use vector store data (with freshness check)
    └─ Miss? → Fetch from API
        ↓
    [NRELClient/BCLClient] Check API Cache
        ├─ Hit? → Return cached API response
        └─ Miss? → Call External API
            ↓
        Cache API response (with TTL)
            ↓
    Index into Vector Store (with indexed_at timestamp)
```

### Current TTL Configuration

**API Response Cache Layer** (`CacheService`):
- Utility Rates: 24 hours TTL
- BCL Measures: 24 hours TTL
- Geocoding: 30 days TTL
- Solar Estimates: 1 hour TTL

**Vector Store Layer** (Recommended TTL):
- Transportation (stations): 30 days
- Utility (rates): 7 days (longer than API cache)
- Buildings (BCL): 90 days

**Rationale**: Vector store TTL should typically be longer than API cache TTL because:
- Vector store updates are more expensive (embedding + indexing)
- API cache handles short-term freshness
- Vector store TTL handles longer-term staleness

### Freshness Checking Best Practices

**Timestamp-Based Tracking**:
- Store `indexed_at` timestamp in document metadata (ISO 8601 format)
- Compare cached data age against configurable TTL
- Refresh data if it exceeds the TTL threshold

**Metadata Structure**:
```python
metadata = {
    "domain": "transportation",
    "indexed_at": "2024-01-15T10:30:00Z",
    "source": "nrel_api",
    "ttl_hours": 720,  # 30 days
}
```

**Refresh Strategy**:
- Check freshness before using cached data
- Fetch fresh data if stale, but consider using cached data immediately for better UX
- Implement background refresh for non-critical updates

---

## Future Enhancements

### Additional Domain Bundles

Based on NREL's open data APIs, potential new bundles:

**1. Climate Bundle** (Priority: HIGH)
- **NREL API**: National Solar Radiation Database (NSRDB) API
- **Provides**: Historical weather patterns, solar radiation data (GHI, DNI, DHI), temperature, wind speed
- **Use Cases**: "What's the average solar radiation in Denver?", "How does climate affect solar production?"
- **Integration Value**: Complements solar bundle with detailed climate context, enables seasonal analysis

**2. Wind Bundle** (Priority: MEDIUM-HIGH)
- **NREL API**: Wind Integration National Dataset (WIND) Toolkit
- **Provides**: Wind resource data, wind speed measurements, wind power density estimates
- **Use Cases**: "What's the wind resource potential in zip 80202?", "Compare wind vs solar potential"
- **Integration Value**: Enables multi-renewable energy analysis (solar + wind)

**3. Wave Bundle** (Priority: LOW-MEDIUM)
- **NREL API**: Wave resource data services
- **Provides**: Wave energy resource data, wave height and period measurements
- **Use Cases**: Primarily coastal/offshore energy projects
- **Integration Value**: Niche use case, complements wind bundle for offshore renewable energy

**Bundle Implementation Pattern**:
Each new bundle should follow the existing pattern:
```
backend/src/bundles/{bundle_name}/
├── __init__.py          # get_tool() function
└── query_engine.py      # Optional: Custom query engine if needed
```

### Other Enhancements

- More sophisticated reranking algorithms
- Real-time data updates with event-driven architecture
- Advanced analytics dashboard
- Multi-language support
- Query refinement and expansion
- Hybrid search (semantic + keyword)
- LLM streaming for answer generation (chunk events)
- Progress percentages and tool results preview

---

**Note**: This document serves as the single source of truth for current project state and architecture. Historical documentation has been consolidated here.

