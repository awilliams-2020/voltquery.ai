#!/usr/bin/env python3
"""
Script to check if documents are being stored in the vector database.
This will query the energy_documents table and show what's actually stored.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.vector_store_service import VectorStoreService
from app.services.rag_service import RAGService
from supabase import create_client
from pydantic_settings import BaseSettings


class SupabaseSettings(BaseSettings):
    supabase_url: str
    supabase_key: str
    
    class Config:
        env_file = ".env"
        extra = "ignore"


async def check_vector_store():
    """Check what's stored in the vector database."""
    print("=" * 60)
    print("Checking Vector Store Contents")
    print("=" * 60)
    
    # Get Supabase client
    settings = SupabaseSettings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)
    
    # Query the energy_documents table
    print("\n1. Querying energy_documents table...")
    try:
        response = supabase.table("energy_documents").select("*").limit(10).execute()
        rows = response.data if hasattr(response, 'data') else []
        
        print(f"   Found {len(rows)} rows in energy_documents table")
        
        if rows:
            print("\n   Sample rows:")
            for i, row in enumerate(rows[:3], 1):
                print(f"\n   Row {i}:")
                print(f"     ID: {row.get('id')}")
                print(f"     Content (first 100 chars): {row.get('content', '')[:100]}...")
                print(f"     Metadata: {row.get('metadata', {})}")
                print(f"     Has embedding: {row.get('embedding') is not None}")
                print(f"     Created at: {row.get('created_at')}")
        else:
            print("   ⚠️  Table is empty!")
            
    except Exception as e:
        print(f"   ❌ Error querying table: {str(e)}")
    
    # Check total count
    print("\n2. Getting total count...")
    try:
        count_response = supabase.table("energy_documents").select("id", count="exact").execute()
        total_count = count_response.count if hasattr(count_response, 'count') else len(rows)
        print(f"   Total documents in energy_documents: {total_count}")
    except Exception as e:
        print(f"   ❌ Error getting count: {str(e)}")
    
    # Check metadata distribution
    print("\n3. Checking metadata distribution...")
    try:
        # Get all rows to analyze metadata
        all_response = supabase.table("energy_documents").select("metadata").execute()
        all_rows = all_response.data if hasattr(all_response, 'data') else []
        
        if all_rows:
            domains = {}
            cities = {}
            states = {}
            
            for row in all_rows:
                metadata = row.get('metadata', {})
                domain = metadata.get('domain', 'unknown')
                city = metadata.get('city', 'unknown')
                state = metadata.get('state', 'unknown')
                
                domains[domain] = domains.get(domain, 0) + 1
                if city != 'unknown':
                    cities[city] = cities.get(city, 0) + 1
                if state != 'unknown':
                    states[state] = states.get(state, 0) + 1
            
            print(f"   Domains: {domains}")
            print(f"   Top 10 cities: {dict(sorted(cities.items(), key=lambda x: x[1], reverse=True)[:10])}")
            print(f"   States: {dict(sorted(states.items(), key=lambda x: x[1], reverse=True))}")
        else:
            print("   No data to analyze")
            
    except Exception as e:
        print(f"   ❌ Error analyzing metadata: {str(e)}")
    
    # Test retrieval
    print("\n4. Testing retrieval from vector store...")
    try:
        llm_mode = os.getenv("LLM_MODE", "local")
        vector_service = VectorStoreService(llm_mode=llm_mode)
        index = vector_service.get_index()
        
        # Try to retrieve some nodes
        from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
        
        # Try retrieving transportation domain
        trans_filter = MetadataFilters(
            filters=[MetadataFilter(key="domain", value="transportation", operator=FilterOperator.EQ)]
        )
        from llama_index.core import VectorIndexRetriever
        
        retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=5,
            filters=trans_filter
        )
        
        nodes = retriever.retrieve("charging stations")
        print(f"   Retrieved {len(nodes)} nodes for 'charging stations' query")
        
        if nodes:
            print("\n   Sample retrieved nodes:")
            for i, node in enumerate(nodes[:2], 1):
                print(f"\n   Node {i}:")
                print(f"     Text (first 100 chars): {node.text[:100] if hasattr(node, 'text') else 'N/A'}...")
                print(f"     Metadata: {node.metadata if hasattr(node, 'metadata') else {}}")
        else:
            print("   ⚠️  No nodes retrieved!")
            
    except Exception as e:
        print(f"   ❌ Error testing retrieval: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Check complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(check_vector_store())

