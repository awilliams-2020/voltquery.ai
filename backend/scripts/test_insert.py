#!/usr/bin/env python3
"""
Test script to verify document insertion is working.
This will attempt to insert a test document and check if it appears in the database.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.vector_store_service import VectorStoreService
from app.services.document_service import DocumentService
from llama_index.core import Document


async def test_insert():
    """Test inserting a document into the vector store."""
    print("=" * 60)
    print("Testing Document Insertion")
    print("=" * 60)
    
    llm_mode = os.getenv("LLM_MODE", "local")
    print(f"\nLLM Mode: {llm_mode}")
    
    try:
        # Initialize services
        print("\n1. Initializing vector store service...")
        vector_service = VectorStoreService(llm_mode=llm_mode)
        index = vector_service.get_index()
        print("   ✓ Vector store initialized")
        
        # Create a test document
        print("\n2. Creating test document...")
        test_doc = Document(
            text="Test Station: 123 Main St, Test City, TS, 12345. Network: Test Network. Connector Types: J1772.",
            metadata={
                "domain": "transportation",
                "station_id": "test_123",
                "station_name": "Test Station",
                "city": "Test City",
                "state": "TS",
                "zip": "12345",
                "network": "Test Network"
            },
            id_="test_station_123"
        )
        print(f"   ✓ Created test document: {test_doc.id_}")
        
        # Insert the document
        print("\n3. Inserting document into vector store...")
        try:
            index.insert(test_doc)
            print("   ✓ Document inserted successfully")
        except Exception as e:
            print(f"   ❌ Error inserting document: {str(e)}")
            import traceback
            traceback.print_exc()
            return
        
        # Try to retrieve it
        print("\n4. Retrieving document from vector store...")
        try:
            from llama_index.core import VectorIndexRetriever
            retriever = VectorIndexRetriever(
                index=index,
                similarity_top_k=5
            )
            nodes = retriever.retrieve("test station")
            print(f"   ✓ Retrieved {len(nodes)} nodes")
            
            if nodes:
                print("\n   Sample retrieved nodes:")
                for i, node in enumerate(nodes[:2], 1):
                    print(f"\n   Node {i}:")
                    print(f"     ID: {node.node_id if hasattr(node, 'node_id') else 'N/A'}")
                    print(f"     Text (first 100 chars): {node.text[:100] if hasattr(node, 'text') else 'N/A'}...")
                    print(f"     Metadata: {node.metadata if hasattr(node, 'metadata') else {}}")
            else:
                print("   ⚠️  No nodes retrieved - this might indicate RLS issues")
        except Exception as e:
            print(f"   ❌ Error retrieving document: {str(e)}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Check Supabase dashboard - you should see a row in energy_documents table")
        print("2. If table still appears empty, run the RLS fix migration:")
        print("   migrations/003_fix_rls_policies.sql")
        print("3. Query the table directly:")
        print("   SELECT COUNT(*) FROM energy_documents;")
        
    except Exception as e:
        print(f"\n❌ Error during test: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_insert())

