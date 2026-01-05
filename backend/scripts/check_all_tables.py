#!/usr/bin/env python3
"""
Script to check all tables in Supabase to find where vecs stores data.
vecs library might create tables with different names or structures.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic_settings import BaseSettings
from supabase import create_client


class SupabaseSettings(BaseSettings):
    supabase_url: str
    supabase_key: str
    
    class Config:
        env_file = ".env"
        extra = "ignore"


def check_all_tables():
    """Check all tables in Supabase to find vector data."""
    print("=" * 60)
    print("Checking All Tables in Supabase")
    print("=" * 60)
    
    settings = SupabaseSettings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)
    
    # Query information_schema to find all tables
    print("\n1. Finding all tables in the database...")
    try:
        # Use Supabase REST API to query pg_tables
        # Note: This requires direct database access, so we'll use a SQL query via Supabase
        # For now, let's check common vecs table names
        
        # vecs typically creates tables with pattern: collection_name_<hash>
        # Or it might use a different schema
        
        print("\n2. Checking energy_documents table...")
        try:
            response = supabase.table("energy_documents").select("id").limit(1).execute()
            count = len(response.data) if hasattr(response, 'data') else 0
            print(f"   energy_documents: {count} rows")
        except Exception as e:
            print(f"   energy_documents: Error - {str(e)}")
        
        # Check for vecs-specific tables
        # vecs might create tables like: vecs_energy_documents or similar
        print("\n3. Checking for vecs-related tables...")
        vecs_table_names = [
            "vecs_energy_documents",
            "energy_documents_vecs",
            "collections",
            "vecs_collections",
        ]
        
        for table_name in vecs_table_names:
            try:
                response = supabase.table(table_name).select("id").limit(1).execute()
                count = len(response.data) if hasattr(response, 'data') else 0
                print(f"   {table_name}: {count} rows")
            except Exception as e:
                # Table doesn't exist or can't access
                pass
        
        print("\n4. To check all tables via SQL, run this in Supabase SQL Editor:")
        print("""
SELECT 
    schemaname,
    tablename,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = tablename) as column_count
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
        """)
        
        print("\n5. To check for vecs collections, run:")
        print("""
SELECT * FROM information_schema.tables 
WHERE table_schema = 'public' 
AND (table_name LIKE '%vecs%' OR table_name LIKE '%collection%' OR table_name LIKE '%energy_documents%')
ORDER BY table_name;
        """)
        
        print("\n6. To check if vecs created a different structure, run:")
        print("""
SELECT 
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'public'
AND table_name LIKE '%energy_documents%'
ORDER BY table_name, ordinal_position;
        """)
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Check complete!")
    print("=" * 60)
    print("\nNote: vecs library might store data in a different table structure.")
    print("Run the SQL queries above in Supabase SQL Editor to find all tables.")


if __name__ == "__main__":
    check_all_tables()

