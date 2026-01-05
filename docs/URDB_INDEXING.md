# URDB Background Task Implementation

## Overview

The URDB (Utility Rate Database) background task system fetches and indexes comprehensive utility rate data from OpenEI's URDB API. This massive dataset is indexed by zip code metadata for fast lookups in RAG queries.

## Prerequisites

### OpenEI API Key

**Important:** OpenEI requires its own API key, separate from the NREL API key.

1. **Get Your API Key**: Sign up at https://apps.openei.org/services/api/signup/
2. **Add to Environment**: Add `OPENEI_API_KEY` to your `.env` file:
   ```bash
   OPENEI_API_KEY=your_openei_api_key_here
   ```

The OpenEI API key is different from the NREL API key used for EV charging stations.

## Features

- **Background Processing**: Long-running tasks run asynchronously without blocking the API
- **Batch Processing**: Processes zip codes in batches to manage memory and API rate limits
- **Zip Code Indexing**: All data is tagged with zip code metadata for efficient filtering
- **Domain Tagging**: URDB data is tagged with `domain: "utility"` for router-based queries
- **Status Tracking**: Real-time task status tracking via task IDs

## API Endpoints

### 1. Fetch URDB by Zip Codes

```bash
POST /api/urdb/fetch
```

**Request Body:**
```json
{
  "zip_codes": ["80202", "10001", "90210"],
  "sector": "residential",
  "fetch_batch_size": 10,
  "index_batch_size": 50,
  "delay_between_batches": 1.0
}
```

**Response:**
```json
{
  "task_id": "uuid-here",
  "status": "queued",
  "message": "URDB fetch task started for 3 zip codes",
  "check_status_url": "/api/urdb/status/uuid-here"
}
```

### 2. Fetch URDB by State

```bash
POST /api/urdb/fetch-by-state
```

**Request Body:**
```json
{
  "state": "OH",
  "sector": "residential",
  "fetch_batch_size": 10,
  "index_batch_size": 50,
  "delay_between_batches": 1.0,
  "limit": 100
}
```

**Note:** The `limit` parameter is useful for testing. Without it, the system will attempt to process all zip codes in the state.

### 3. Check Task Status

```bash
GET /api/urdb/status/{task_id}
```

**Response:**
```json
{
  "status": "running",
  "progress": 45,
  "message": "Processing URDB batch 5/10...",
  "zip_codes_count": 100
}
```

**Status Values:**
- `queued`: Task is waiting to start
- `running`: Task is currently processing
- `completed`: Task finished successfully
- `failed`: Task encountered an error

## How It Works

### Step 1: Fetch URDB Data

1. **Geocode Zip Codes**: Each zip code is geocoded to get latitude/longitude
2. **API Requests**: URDB API is called with location parameters
3. **Batch Processing**: Multiple zip codes are processed concurrently in batches
4. **Rate Limiting**: Delays between batches prevent API rate limit issues

### Step 2: Index Data

1. **Document Conversion**: URDB data is converted to LlamaIndex Documents
2. **Metadata Tagging**: Each document is tagged with:
   - `domain: "utility"` (for router filtering)
   - `zip`: Zip code (for fast lookups)
   - `utility_name`: Utility company name
   - `residential_rate`, `commercial_rate`, `industrial_rate`: Rate information
3. **Vector Embedding**: Documents are embedded using the configured embedding model
4. **Storage**: Embedded documents are stored in Supabase vector database

### Step 3: Query Integration

Once indexed, URDB data is automatically:
- **Routed**: RouterQueryEngine routes utility questions to the utility domain
- **Retrieved**: Vector similarity search finds relevant utility rate information
- **Used**: LLM generates answers using retrieved URDB context

## Usage Examples

### Example 1: Index Specific Zip Codes

```bash
curl -X POST http://localhost:8000/api/urdb/fetch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "zip_codes": ["80202", "10001", "90210"],
    "sector": "residential"
  }'
```

### Example 2: Index All Zip Codes in a State (Limited)

```bash
curl -X POST http://localhost:8000/api/urdb/fetch-by-state \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "state": "OH",
    "limit": 50,
    "sector": "residential"
  }'
```

### Example 3: Check Task Status

```bash
curl http://localhost:8000/api/urdb/status/{task_id} \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Configuration

### Batch Sizes

- **fetch_batch_size**: Number of zip codes to fetch concurrently (default: 10)
  - Lower = slower but safer for rate limits
  - Higher = faster but may hit rate limits
  
- **index_batch_size**: Number of documents to index per batch (default: 50)
  - Adjust based on memory constraints

### Rate Limiting

- **delay_between_batches**: Seconds to wait between fetch batches (default: 1.0)
  - Increase if hitting API rate limits
  - Decrease for faster processing (if allowed by API)

## Data Structure

### URDB Document Metadata

```json
{
  "domain": "utility",
  "zip": "80202",
  "utility_name": "Xcel Energy",
  "location": "80202",
  "residential_rate": 0.12,
  "commercial_rate": 0.10,
  "industrial_rate": 0.08,
  "eiaid": "12345"
}
```

### Document Text Format

```
Utility Company: Xcel Energy. Location: 80202. Residential Rate: $0.12/kWh. Commercial Rate: $0.10/kWh. Industrial Rate: $0.08/kWh. EIA Utility ID: 12345.
```

## Performance Considerations

### Large Datasets

For large states or many zip codes:
1. **Use Limits**: Start with `limit` parameter for testing
2. **Monitor Status**: Check task status regularly
3. **Batch Sizes**: Adjust batch sizes based on system resources
4. **Rate Limits**: Respect API rate limits with appropriate delays

### Memory Usage

- Each document is embedded before storage
- Batch processing helps manage memory
- Consider system resources when setting batch sizes

## Integration with RAG

Once URDB data is indexed:

1. **Automatic Routing**: Questions about electricity costs are routed to utility domain
2. **Vector Search**: Similarity search finds relevant utility rate information
3. **Context Retrieval**: Retrieved URDB documents provide context for LLM
4. **Answer Generation**: LLM generates answers using URDB data

### Example Query Flow

**User Query:** "What's the electricity cost in Denver?"

1. RouterQueryEngine detects utility-related question
2. Routes to utility domain retriever
3. Retrieves URDB documents for Denver zip codes
4. LLM generates answer using retrieved URDB context

## Troubleshooting

### Task Stuck in "Queued"

- Check if background tasks are running
- Verify FastAPI server is running
- Check server logs for errors

### Task Failed

- Check task status for error message
- Verify OpenEI API key is valid (separate from NREL API key)
- Ensure `OPENEI_API_KEY` is set in environment variables
- Check network connectivity
- Review API rate limits
- Verify API key at: https://apps.openei.org/services/api/signup/

### No Data Retrieved

- Verify zip codes are valid
- Check URDB API availability
- Review API response format
- Check geocoding service availability

## Future Improvements

- [ ] Use comprehensive zip code database instead of ranges
- [ ] Add progress callbacks for real-time updates
- [ ] Implement task cancellation
- [ ] Add retry logic for failed requests
- [ ] Cache geocoding results
- [ ] Add data freshness tracking
- [ ] Implement incremental updates

