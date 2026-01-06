# Backend - VoltQuery.ai API

FastAPI backend for EV Infrastructure RAG SaaS application.

## Quick Setup

### Option 1: Automated Setup (Recommended)

```bash
cd backend
./setup.sh
```

### Option 2: Manual Setup

1. **Install python3-venv** (if not already installed):
```bash
sudo apt install python3.12-venv
# OR
sudo apt install python3-venv
```

2. **Create virtual environment**:
```bash
python3 -m venv venv
# OR if python3.12 is available:
python3.12 -m venv venv
```

3. **Activate virtual environment**:
```bash
source venv/bin/activate
```

4. **Upgrade pip**:
```bash
pip install --upgrade pip
```

5. **Install dependencies**:
```bash
pip install -r requirements.txt
```

## Configuration

1. Copy `.env.example` to `.env` and fill in your API keys:
```bash
cp .env.example .env
```

2. Configure environment variables in `.env`:
   - `NREL_API_KEY`: Get from https://developer.nrel.gov/signup/
   - `OPENEI_API_KEY`: Get from https://apps.openei.org/services/api/signup/ (required for URDB)
   - `GEMINI_API_KEY`: Required only if `LLM_MODE=cloud`
   - `LLM_MODE`: Set to `local` (Ollama) or `cloud` (Gemini)
   - `SUPABASE_URL`: Your Supabase project URL
   - `SUPABASE_KEY`: Your Supabase anon/service key
   - `SUPABASE_DB_URL`: PostgreSQL connection string from Supabase (used for both ORM and vector store)
   - `DATABASE_URL`: Optional - PostgreSQL connection string (will use SUPABASE_DB_URL if not set)
   - `OPENAI_API_KEY`: Required when `LLM_MODE=cloud` for embeddings
   - `CLERK_SECRET_KEY`: Your Clerk secret key
   - `STRIPE_SECRET_KEY`: Your Stripe secret key
   - `STRIPE_WEBHOOK_SECRET`: Your Stripe webhook secret
   - `STRIPE_PRICE_ID`: Your Stripe price ID for Premium plan
   - `FRONTEND_URL`: Frontend URL (default: http://localhost:3000)

3. **Set up Supabase Vector Database**:
   
   - Create a Supabase project at https://supabase.com
   - Run the migration scripts in `migrations/` folder:
     - `001_create_ev_stations_table.sql` - For vector store
     - `002_create_saas_tables.sql` - For users, queries, subscriptions
   - Get your connection string from Supabase Dashboard → Settings → Database
   - For local mode (Ollama), the table uses 768-dimensional vectors
   - For cloud mode (OpenAI), the table uses 1536-dimensional vectors
   - Update the migration script accordingly before running

4. **LLM Configuration**:
   
   **For Local Development (LLM_MODE=local)**:
   - Install and run Ollama: https://ollama.ai/
   - Pull models:
     - `ollama pull llama2` (for LLM)
     - `ollama pull nomic-embed-text` (for embeddings)
   - Default model is `llama2`, configurable via `OLLAMA_MODEL` env var
   - Default Ollama URL is `http://localhost:11434`, configurable via `OLLAMA_BASE_URL`
   
   **For Cloud Deployment (LLM_MODE=cloud)**:
   - Set `LLM_MODE=cloud` in `.env`
   - Set `GEMINI_API_KEY` with your Google AI API key
   - Set `OPENAI_API_KEY` for embeddings (uses text-embedding-3-small)
   - Uses Gemini 1.5 Pro by default

## Running the Server

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Run development server
uvicorn app.main:app --reload --port 8000
```

The API will be available at http://localhost:8000

API documentation: http://localhost:8000/docs

## Database Setup

Run the migration scripts in your Supabase SQL Editor:

1. `migrations/001_create_ev_stations_table.sql` - Creates vector store table
   - For OpenAI (cloud mode): Use as-is with `vector(1536)` - DEFAULT
   - For Ollama (local mode): Change line 13 to `vector(768)`
2. `migrations/002_create_saas_tables.sql` - Creates users, queries, subscriptions tables

## Bulk Indexing (Local Development)

For local development, you can "over-index" entire states using the bulk indexing script:

```bash
# Make sure Ollama is running and models are pulled
ollama serve
ollama pull nomic-embed-text

# Bulk index all stations for Ohio
python scripts/bulk_index_state.py --state OH

# Test with a limit first
python scripts/bulk_index_state.py --state OH --limit 100
```

See `BULK_INDEXING.md` for detailed instructions.

## API Endpoints

### LLM Endpoints

- `POST /api/llm/chat`: Chat with the configured LLM
  ```json
  {
    "prompt": "What is an EV charging station?"
  }
  ```

- `GET /api/llm/info`: Get information about the currently configured LLM

### Station Endpoints

- `POST /api/fetch-stations`: Fetch EV charging stations by zip code
  ```json
  {
    "zip_code": "80202"
  }
  ```

### RAG Endpoints

- `POST /api/rag/query`: Perform a RAG query to get natural language answers about EV charging stations
  ```json
  {
    "question": "Where can I charge my Tesla?",
    "zip_code": "80202",  // Optional: will fetch and index stations if provided
    "top_k": 5  // Optional: number of relevant stations to retrieve
  }
  ```
  
  **Requires authentication** - Include headers:
  - `X-Clerk-User-Id`: User's Clerk ID
  - `X-Clerk-Email`: User's email
  
  **Features:**
  - Automatic reranking using LLM (enabled by default)
  - Retrieves top candidates, then reranks to select most relevant
  - Compensates for llama2's reasoning limitations vs Gemini

- `POST /api/rag/index-stations`: Fetch stations from NREL and index them into the vector database
  ```json
  {
    "zip_code": "80202",
    "limit": 50  // Optional: max number of stations to fetch
  }
  ```

- `POST /api/rag/bulk-index-state`: Bulk index ALL stations for a state (perfect for local over-indexing)
  ```json
  {
    "state": "OH",  // 2-letter state code
    "batch_size": 100,  // Optional: stations per batch (default: 100)
    "limit": null  // Optional: limit total stations (for testing)
  }
  ```
  
  **Perfect for local development**: Download entire state datasets and bulk embed using Ollama (free!)

### History Endpoints

- `GET /api/history/queries`: Get user's query history
- `GET /api/history/stats`: Get user's query statistics

### Stripe Endpoints

- `POST /api/stripe/create-checkout`: Create Stripe checkout session
- `POST /api/stripe/create-portal`: Create Stripe customer portal session
- `POST /api/stripe/webhook`: Handle Stripe webhook events
