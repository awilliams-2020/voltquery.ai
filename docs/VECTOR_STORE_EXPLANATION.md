# Vector Store Data Storage Explanation

## How Data is Stored

The `energy_documents` table in Supabase stores **vector embeddings** of documents, not raw station records. This is how LlamaIndex's SupabaseVectorStore works.

### Table Structure

The `energy_documents` table has this structure:
- `id` (UUID) - Unique identifier for each document
- `content` (TEXT) - The text content of the document (e.g., station description)
- `metadata` (JSONB) - Metadata about the document (city, state, zip, domain, etc.)
- `embedding` (vector) - The vector embedding of the content (768 or 1536 dimensions)
- `created_at` (TIMESTAMP) - When the document was created
- `updated_at` (TIMESTAMP) - When the document was last updated

### What Gets Stored

When stations are indexed:
1. **Station data** is converted to `Document` objects with:
   - `text`: Formatted station description (name, address, connector types, etc.)
   - `metadata`: JSON object with `domain`, `station_id`, `city`, `state`, `zip`, `network`, etc.

2. **Documents are embedded** using the embedding model (Ollama or OpenAI)

3. **Embeddings are stored** in the `energy_documents` table with:
   - `content`: The station text
   - `metadata`: All station metadata as JSON
   - `embedding`: The vector representation

### Why the Table Might Appear Empty

1. **Wrong table name**: LlamaIndex might be using a different table name
2. **Insertion errors**: Errors during insertion might be silently caught
3. **Wrong database**: You might be looking at a different database
4. **Schema mismatch**: The table structure might not match what LlamaIndex expects

## How to Check if Data is Stored

### Option 1: Query the Table Directly

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

-- Check by city
SELECT 
    metadata->>'city' as city,
    metadata->>'state' as state,
    COUNT(*) as count
FROM energy_documents
WHERE metadata->>'domain' = 'transportation'
GROUP BY metadata->>'city', metadata->>'state'
ORDER BY count DESC
LIMIT 20;
```

### Option 2: Use the Check Script

Run the diagnostic script (requires Supabase credentials in `.env`):

```bash
cd backend
source venv/bin/activate
python scripts/check_vector_store.py
```

### Option 3: Check Application Logs

When stations are indexed, you should see:
- `"Successfully indexed X stations"` messages
- Any error messages if insertion fails

## Troubleshooting

### If the Table is Empty

1. **Check if indexing is actually happening**:
   - Look for API calls to `/api/rag/query` that trigger station fetching
   - Check application logs for indexing messages

2. **Check for insertion errors**:
   - The improved error handling will now print errors
   - Look for `"Warning: Failed to insert document"` messages

3. **Verify table structure**:
   - Make sure the table exists and has the correct schema
   - Check that the embedding dimension matches your LLM_MODE:
     - Local (Ollama): 768 dimensions
     - Cloud (OpenAI): 1536 dimensions

4. **Check database connection**:
   - Verify `SUPABASE_DB_URL` or `DATABASE_URL` is correct
   - Test the connection

### If Data Exists But Queries Don't Work

1. **Check metadata filters**: Make sure metadata keys match what's stored
2. **Check embedding dimension**: Ensure it matches your LLM_MODE
3. **Check vector index**: The `energy_documents_embedding_idx` should exist

## Example: What a Stored Document Looks Like

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "content": "Station Name: GM DELIVERY DELIVERY BAY. Address: 2594 W Michigan St, Sidney, OH, 45365. Network: ChargePoint Network. Connector Types: J1772. Charging Ports: 1 Level 2 Charging port(s)...",
  "metadata": {
    "domain": "transportation",
    "station_id": "12345",
    "station_name": "GM DELIVERY DELIVERY BAY",
    "city": "Sidney",
    "state": "OH",
    "zip": "45365",
    "network": "ChargePoint Network",
    "connector_types": "J1772",
    "level2_count": 1,
    "dc_fast_count": 0
  },
  "embedding": [0.123, -0.456, ...],  // Vector of 768 or 1536 numbers
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

## Important Notes

- **Both stations AND utility rates** are stored in the same `energy_documents` table
- They're differentiated by the `domain` field in metadata (`transportation` vs `utility`)
- The table name `energy_documents` is configurable via `SUPABASE_TABLE_NAME` env var (defaults to `energy_documents`)
- LlamaIndex handles all the embedding and storage automatically when you call `index.insert(doc)`

