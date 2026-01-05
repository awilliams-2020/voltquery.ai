# After Bulk Indexing - What's Next?

## ✅ What You've Done

After running bulk indexing, your EV charging station data is now:
- ✅ Downloaded from NREL API
- ✅ Embedded using Ollama (`nomic-embed-text`)
- ✅ Stored in Supabase vector database

## 🚀 What You Need Running for Queries

To query your indexed data, you need these services running:

### 1. **Ollama Server** (Required for Local Mode)

**Why?** The RAG system needs Ollama for:
- **Embedding user queries** (using `nomic-embed-text`)
- **Generating responses** (using `llama2` or your configured LLM)

**Start it:**
```bash
ollama serve
```

**Make sure models are pulled:**
```bash
ollama pull nomic-embed-text  # For embeddings
ollama pull llama2            # For LLM responses (or your configured model)
```

### 2. **FastAPI Backend Server** (Required)

**Why?** This serves the RAG query endpoints.

**Start it:**
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

### 3. **Supabase** (Already Running)

Your Supabase database is already set up and contains your indexed data. No action needed!

## 📝 Quick Test

Once everything is running, test your indexed data:

```bash
# Test query (requires authentication headers)
curl -X POST http://localhost:8000/api/rag/query \
  -H "Content-Type: application/json" \
  -H "X-Clerk-User-Id: your-user-id" \
  -H "X-Clerk-Email: your-email@example.com" \
  -d '{
    "question": "Where can I charge my Tesla in Ohio?",
    "top_k": 5
  }'
```

Or use the frontend at `http://localhost:3000` (if running).

## 🔄 What Happens During a Query?

1. **User asks a question** → "Where can I charge my Tesla?"
2. **Query is embedded** → Uses Ollama `nomic-embed-text` to convert question to vector
3. **Similarity search** → Finds relevant stations in Supabase vector database
4. **Reranking** → Uses Ollama LLM (`llama2`) to rerank and select top results
5. **Response generation** → Uses Ollama LLM to generate natural language answer
6. **Return answer** → User gets answer with source stations

## 🎯 Summary: What Needs to Run

| Service | Required For | Status |
|---------|-------------|--------|
| **Ollama** | Embedding queries + generating responses | ⚠️ **Must be running** |
| **FastAPI Backend** | Serving API endpoints | ⚠️ **Must be running** |
| **Supabase** | Vector database (already indexed) | ✅ **Already set up** |
| **Frontend** (optional) | Web UI | Optional |

## 💡 Pro Tips

1. **Keep Ollama Running**: Leave `ollama serve` running in a terminal while developing
2. **Check Models**: Verify models are pulled with `ollama list`
3. **Monitor Logs**: Watch FastAPI logs for query processing
4. **Test Incrementally**: Start with simple queries, then try complex ones

## 🐛 Troubleshooting

### "Ollama connection refused"
```bash
# Start Ollama
ollama serve
```

### "Model not found"
```bash
# Pull required models
ollama pull nomic-embed-text
ollama pull llama2
```

### "No stations indexed"
- Check Supabase: Your data should be in the `energy_documents` table
- Verify indexing completed successfully
- Check the bulk indexing script output

### "Query returns empty results"
- Verify stations were actually indexed (check Supabase)
- Try a broader query (e.g., "charging stations" instead of specific location)
- Check that your query is being embedded correctly

## 🎉 You're Ready!

Once Ollama and FastAPI are running, you can start querying your indexed EV charging station data!

