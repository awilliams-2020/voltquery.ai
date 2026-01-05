-- Migration script for creating the energy documents vector table in Supabase
-- Run this in your Supabase SQL Editor: https://supabase.com/dashboard/project/[PROJECT]/sql
--
-- IMPORTANT: Choose the correct embedding dimension based on your LLM_MODE:
--   - LLM_MODE=cloud (OpenAI): Use vector(1536) - DEFAULT BELOW
--   - LLM_MODE=local (Ollama): Use vector(768) - Change line 13 to vector(768)
--
-- Note: If you don't run this migration, the table will be created automatically
-- by the VectorStoreService with the correct dimension based on your LLM_MODE setting.

-- Enable pgvector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the energy_documents table with pgvector support
CREATE TABLE IF NOT EXISTS energy_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    metadata JSONB,
    embedding vector(1536), -- DEFAULT: OpenAI (1536 dims). For Ollama, change to vector(768)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index for vector similarity search
CREATE INDEX IF NOT EXISTS energy_documents_embedding_idx ON energy_documents 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Create index for metadata queries
CREATE INDEX IF NOT EXISTS energy_documents_metadata_idx ON energy_documents USING GIN (metadata);

-- Create index for station_id lookups (for EV stations)
CREATE INDEX IF NOT EXISTS energy_documents_station_id_idx ON energy_documents ((metadata->>'station_id'));

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Drop trigger if it exists, then create it
DROP TRIGGER IF EXISTS update_energy_documents_updated_at ON energy_documents;
CREATE TRIGGER update_energy_documents_updated_at BEFORE UPDATE ON energy_documents
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Alternative: If you already created the table with the wrong dimension, you can alter it:
-- For Ollama (local mode) - change from 1536 to 768:
--   ALTER TABLE energy_documents ALTER COLUMN embedding TYPE vector(768);
--   DROP INDEX IF EXISTS energy_documents_embedding_idx;
--   CREATE INDEX energy_documents_embedding_idx ON energy_documents 
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
--
-- For OpenAI (cloud mode) - change from 768 to 1536:
--   ALTER TABLE energy_documents ALTER COLUMN embedding TYPE vector(1536);
--   DROP INDEX IF EXISTS energy_documents_embedding_idx;
--   CREATE INDEX energy_documents_embedding_idx ON energy_documents 
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

