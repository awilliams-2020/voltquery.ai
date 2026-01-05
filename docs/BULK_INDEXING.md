# Bulk Indexing Guide

## Overview

For local development, you can "over-index" by downloading entire state datasets and bulk embedding them using Ollama (free, local). This gives you comprehensive coverage without API costs.

## Quick Start

### Option 1: Using the Python Script (Recommended)

```bash
cd backend
source venv/bin/activate

# Bulk index all stations for Ohio
python scripts/bulk_index_state.py --state OH

# Test with a limit first
python scripts/bulk_index_state.py --state OH --limit 100

# Customize batch size
python scripts/bulk_index_state.py --state OH --batch-size 50
```

### Option 2: Using the API Endpoint

```bash
# Bulk index all stations for Ohio
curl -X POST http://localhost:8000/api/rag/bulk-index-state \
  -H "Content-Type: application/json" \
  -d '{"state": "OH"}'

# Test with a limit
curl -X POST http://localhost:8000/api/rag/bulk-index-state \
  -H "Content-Type: application/json" \
  -d '{"state": "OH", "limit": 100, "batch_size": 50}'
```

## Prerequisites

1. **Ollama Running**: Make sure Ollama is running
   ```bash
   ollama serve
   ```

2. **Embedding Model Pulled**: Pull the required embedding model
   ```bash
   ollama pull nomic-embed-text
   ```

3. **Supabase Configured**: Ensure your `.env` has:
   - `SUPABASE_DB_URL`: PostgreSQL connection string
   - `SUPABASE_URL`: Supabase project URL
   - `SUPABASE_KEY`: Supabase API key
   - `NREL_API_KEY`: NREL API key

4. **Database Table Created**: Run the migration `migrations/001_create_ev_stations_table.sql`
   - For Ollama (768 dims): Change line 13 to `vector(768)` before running
   - For OpenAI (1536 dims): Use as-is (default)
   - Note: The table will be created automatically by the service if it doesn't exist

## How It Works

1. **Fetch All Stations**: Downloads ALL stations for the target state from NREL API
2. **Batch Processing**: Processes stations in batches (default: 100) to manage memory
3. **Bulk Embedding**: Uses Ollama to embed each station (free, local)
4. **Vector Storage**: Stores embeddings in Supabase pgvector table

## State Codes

Use 2-letter US state codes:
- `OH` - Ohio
- `CA` - California
- `NY` - New York
- `TX` - Texas
- etc.

## Performance Tips

1. **Start Small**: Test with `--limit 100` first
2. **Batch Size**: Adjust `--batch-size` based on your system (default: 100)
3. **Large States**: States like CA or TX may have thousands of stations - be patient
4. **Monitor Progress**: The script shows progress for each batch

## Reranking

After bulk indexing, queries automatically use **LLM-based reranking** to improve results:

- Retrieves `top_k * 2` candidates initially
- Uses Ollama LLM (llama2) to rerank and select top 3 most relevant
- Compensates for llama2's slightly lower reasoning power compared to Gemini

Reranking is enabled by default but can be disabled in the query if needed.

## Example Workflow

```bash
# 1. Pull required models
ollama pull llama2
ollama pull nomic-embed-text

# 2. Start Ollama
ollama serve

# 3. Bulk index Ohio (test with limit first)
python scripts/bulk_index_state.py --state OH --limit 100

# 4. If successful, index all stations
python scripts/bulk_index_state.py --state OH

# 5. Query your indexed data
curl -X POST http://localhost:8000/api/rag/query \
  -H "Content-Type: application/json" \
  -H "X-Clerk-User-Id: your-user-id" \
  -H "X-Clerk-Email: your-email" \
  -d '{"question": "Where can I charge my Tesla in Ohio?"}'
```

## Troubleshooting

### "Model not found" error
```bash
ollama pull nomic-embed-text
```

### "Ollama connection refused"
```bash
# Make sure Ollama is running
ollama serve
```

### "Table does not exist"
Run the appropriate migration script in Supabase SQL Editor.

### Slow indexing
- Reduce `--batch-size` (e.g., 50)
- Check Ollama is running efficiently
- Consider indexing smaller states first

## Benefits of Over-Indexing Locally

✅ **Free**: Ollama runs locally, no API costs  
✅ **Comprehensive**: Full state coverage  
✅ **Fast Queries**: Pre-indexed data = instant retrieval  
✅ **Better RAG**: More context = better answers  
✅ **Development**: Perfect for local testing

