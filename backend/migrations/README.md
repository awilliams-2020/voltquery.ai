# Running Migrations in Supabase

Follow these steps to run the database migrations in your Supabase project.

## Step 1: Access Supabase SQL Editor

1. Go to [https://supabase.com](https://supabase.com) and sign in
2. Select your project (or create a new one if you haven't already)
3. In the left sidebar, click on **"SQL Editor"**
4. Click **"New query"** to create a new SQL query

## Step 2: Run Migration 001 - Vector Store Table

1. Open the file `001_create_ev_stations_table.sql` in your editor
2. **Important**: Choose the correct embedding dimension based on your `LLM_MODE`:
   - **LLM_MODE=cloud (OpenAI)**: Use as-is with `vector(1536)` - DEFAULT
   - **LLM_MODE=local (Ollama)**: Change line 13 from `vector(1536)` to `vector(768)`
3. Copy the entire contents of the file
4. Paste it into the Supabase SQL Editor
5. Click **"Run"** (or press `Ctrl+Enter` / `Cmd+Enter`)
6. You should see "Success. No rows returned" if it worked
7. **Note**: If you skip this migration, the table will be created automatically by the VectorStoreService with the correct dimension

## Step 3: Run Migration 002 - SaaS Tables

1. Open the file `002_create_saas_tables.sql` in your editor
2. Copy the entire contents of the file
3. Paste it into the Supabase SQL Editor (you can clear the previous query or use a new one)
4. Click **"Run"**
5. You should see "Success. No rows returned" if it worked

## Step 4: Verify Tables Were Created

1. In Supabase, go to **"Table Editor"** in the left sidebar
2. You should see these tables:
   - `energy_documents` - For vector embeddings (EV stations, utility rates, etc.)
   - `users` - For user accounts
   - `queries` - For query history
   - `subscriptions` - For subscription management

## Alternative: Using Supabase CLI (Advanced)

If you have the Supabase CLI installed:

```bash
# Install Supabase CLI (if not installed)
npm install -g supabase

# Login to Supabase
supabase login

# Link your project
supabase link --project-ref your-project-ref

# Run migrations
supabase db push
```

## Troubleshooting

### Error: "extension vector does not exist"
- Make sure you're running migration 001 first
- The `CREATE EXTENSION IF NOT EXISTS vector;` command should enable it

### Error: "relation already exists"
- This is okay! The migrations use `IF NOT EXISTS` so they're safe to run multiple times
- If you want to start fresh, you can drop tables first (be careful!)

### Embedding Dimension Mismatch
- **OpenAI embeddings**: Use `vector(1536)` (default in migration 001)
- **Ollama nomic-embed-text**: Use `vector(768)`
- If you created the table with the wrong dimension, you can alter it:
  ```sql
  -- For Ollama (change from 1536 to 768):
  ALTER TABLE energy_documents ALTER COLUMN embedding TYPE vector(768);
  DROP INDEX IF EXISTS energy_documents_embedding_idx;
  CREATE INDEX energy_documents_embedding_idx ON energy_documents 
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
  
  -- For OpenAI (change from 768 to 1536):
  ALTER TABLE energy_documents ALTER COLUMN embedding TYPE vector(1536);
  DROP INDEX IF EXISTS energy_documents_embedding_idx;
  CREATE INDEX energy_documents_embedding_idx ON energy_documents 
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
  ```

## Quick Copy-Paste Commands

### For OpenAI embeddings (cloud mode):
Run `001_create_ev_stations_table.sql` as-is (default)

### For Ollama embeddings (local mode):
Run `001_create_ev_stations_table.sql` but change line 13:
```sql
embedding vector(768), -- Changed from 1536 to 768
```

Then run `002_create_saas_tables.sql` normally.

