#!/usr/bin/env python3
"""
Script to find the actual table name that vecs is using.
vecs library creates its own table structure.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.vector_store_service import VectorStoreService
from pydantic_settings import BaseSettings
from supabase import create_client


class SupabaseSettings(BaseSettings):
    supabase_url: str
    supabase_key: str
    
    class Config:
        env_file = ".env"
        extra = "ignore"


def find_vecs_table():
    """Find the actual table name vecs is using."""
    print("=" * 60)
    print("Finding vecs Table")
    print("=" * 60)
    
    llm_mode = os.getenv("LLM_MODE", "local")
    
    try:
        # Get vector store
        print("\n1. Getting vector store...")
        vector_service = VectorStoreService(llm_mode=llm_mode)
        vector_store = vector_service.get_vector_store()
        collection = vector_store._collection
        
        print(f"   Collection name: {collection.name}")
        
        # vecs typically creates tables with the collection name
        # But it might add a prefix or suffix
        collection_name = collection.name
        
        # Check what table vecs is actually using
        print("\n2. Checking vecs collection internals...")
        print(f"   Collection object: {type(collection)}")
        
        # Try to access vecs internal table name
        if hasattr(collection, '_table_name'):
            print(f"   Table name (from _table_name): {collection._table_name}")
        elif hasattr(collection, 'table_name'):
            print(f"   Table name (from table_name): {collection.table_name}")
        elif hasattr(collection, '__dict__'):
            attrs = {k: v for k, v in collection.__dict__.items() if 'table' in k.lower() or 'name' in k.lower()}
            if attrs:
                print(f"   Relevant attributes: {attrs}")
        
        # Now check Supabase for tables
        print("\n3. Checking Supabase for matching tables...")
        settings = SupabaseSettings()
        supabase = create_client(settings.supabase_url, settings.supabase_key)
        
        # Query all tables
        # Note: We can't directly query pg_tables via Supabase REST API
        # So we'll try to query the collection name directly
        
        print(f"\n4. Try querying these table names in Supabase SQL Editor:")
        print(f"   - {collection_name}")
        print(f"   - vecs_{collection_name}")
        print(f"   - {collection_name}_vecs")
        print(f"   - {collection_name}_collection")
        
        print(f"\n5. Run this SQL to find all tables:")
        print(f"""
SELECT tablename 
FROM pg_tables 
WHERE schemaname = 'public' 
AND (
    tablename = '{collection_name}' OR
    tablename LIKE '%{collection_name}%' OR
    tablename LIKE '%vecs%' OR
    tablename LIKE '%collection%'
)
ORDER BY tablename;
        """)
        
        print(f"\n6. To check if data exists in {collection_name}, run:")
        print(f"""
SELECT COUNT(*) FROM {collection_name};
        """)
        
        # Try to query the collection directly via vecs
        print(f"\n7. Checking collection via vecs...")
        try:
            # Try to get some records
            records = collection.query(
                data=None,
                limit=1,
                include_value=False,
                include_metadata=False
            )
            print(f"   Found {len(records) if records else 0} records in collection")
        except Exception as e:
            print(f"   Could not query collection: {str(e)}")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Check complete!")
    print("=" * 60)


if __name__ == "__main__":
    find_vecs_table()


