# Troubleshooting Empty energy_documents Table

## The Issue

The `energy_documents` table appears empty in Supabase, but RLS is disabled.

## Root Cause

LlamaIndex's `SupabaseVectorStore` uses the **`vecs`** library, which creates its own table structure. The `vecs` library might:
1. Create tables with different names
2. Use a different schema structure
3. Store data in a format that doesn't match our migration

## How vecs Works

When you call `SupabaseVectorStore(collection_name="energy_documents")`, the `vecs` library:
- Creates a "collection" (not necessarily a table named `energy_documents`)
- Stores data in a specific format optimized for vector search
- May create tables with names like `vecs_energy_documents` or use a different structure

## Diagnostic Steps

### Step 1: Check What Tables Actually Exist

Run this SQL in Supabase SQL Editor:

```sql
-- List all tables in public schema
SELECT 
    tablename,
    schemaname
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
```

Look for tables that might contain your data:
- `energy_documents` (our expected table)
- `vecs_energy_documents` (vecs might create this)
- Any table with "collection" in the name
- Any table with "vecs" in the name

### Step 2: Check Table Structure

If you find a table, check its structure:

```sql
-- Check columns in energy_documents
SELECT 
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
AND table_name = 'energy_documents'
ORDER BY ordinal_position;
```

### Step 3: Test Document Insertion

Run the debug script to see if insertion is working:

```bash
cd backend
source venv/bin/activate
python scripts/debug_insert.py
```

This will:
- Show detailed error messages if insertion fails
- Display what collection vecs is using
- Test if documents can be inserted and retrieved

### Step 4: Check Application Logs

When you make a query that triggers station indexing, check your application logs for:
- `"Successfully indexed X stations"` messages
- `"Warning: Failed to insert document"` errors
- Any database connection errors

## Possible Solutions

### Solution 1: vecs Created a Different Table

If `vecs` created a table with a different name, you have two options:

**Option A**: Use the table vecs created
- Find the actual table name vecs is using
- Update your queries to use that table

**Option B**: Force vecs to use your table
- Drop the vecs-created collection
- Ensure your `energy_documents` table matches vecs' expected structure
- Let vecs recreate it

### Solution 2: Table Structure Mismatch

The `vecs` library expects a specific table structure. Your migration might not match exactly.

Check vecs documentation for the exact table structure it expects, or let vecs create the table automatically by:
1. Dropping your `energy_documents` table
2. Letting `SupabaseVectorStore` create it automatically (it will create the collection on first use)

### Solution 3: Insertion Errors

If insertion is failing silently, the improved error handling should now show errors. Check:
- Application logs for insertion errors
- Database connection issues
- Embedding model availability (Ollama running, OpenAI API key valid)

## Quick Test

Run this to see what's actually happening:

```bash
cd backend
source venv/bin/activate

# Test insertion
python scripts/debug_insert.py

# Check all tables
python scripts/check_all_tables.py
```

Then check Supabase SQL Editor with:

```sql
-- Count rows in energy_documents
SELECT COUNT(*) FROM energy_documents;

-- If count is 0, check for other tables
SELECT tablename FROM pg_tables 
WHERE schemaname = 'public' 
AND (tablename LIKE '%vecs%' OR tablename LIKE '%collection%' OR tablename LIKE '%energy_documents%');
```

## Expected Behavior

When documents are inserted successfully:
1. The `vecs` library creates/uses a collection
2. Documents are embedded and stored
3. You should see rows in the table (or vecs collection)
4. Queries should retrieve the documents

If queries are working (like your Sidney example), then data IS being stored somewhere - we just need to find where!

