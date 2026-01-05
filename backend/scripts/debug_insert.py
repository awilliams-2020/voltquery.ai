#!/usr/bin/env python3
"""
Debug script to test document insertion and see what happens.
This will show detailed error messages if insertion fails.
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


async def debug_insert():
    """Debug document insertion with detailed logging."""
    print("=" * 60)
    print("Debugging Document Insertion")
    print("=" * 60)
    
    llm_mode = os.getenv("LLM_MODE", "local")
    print(f"\nLLM Mode: {llm_mode}")
    print(f"Environment variables:")
    print(f"  SUPABASE_URL: {'Set' if os.getenv('SUPABASE_URL') else 'NOT SET'}")
    print(f"  SUPABASE_DB_URL: {'Set' if os.getenv('SUPABASE_DB_URL') else 'NOT SET'}")
    print(f"  DATABASE_URL: {'Set' if os.getenv('DATABASE_URL') else 'NOT SET'}")
    
    try:
        # Initialize services
        print("\n1. Initializing vector store service...")
        vector_service = VectorStoreService(llm_mode=llm_mode)
        print(f"   Table name: {vector_service.settings.supabase_table_name}")
        print(f"   Embedding dimension: {vector_service.get_embedding_dimension()}")
        
        vector_store = vector_service.get_vector_store()
        print(f"   Vector store type: {type(vector_store)}")
        print(f"   Collection name: {vector_store._collection.name if hasattr(vector_store, '_collection') and vector_store._collection else 'N/A'}")
        
        index = vector_service.get_index()
        print("   ✓ Index initialized")
        
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
        print(f"   ✓ Created test document")
        print(f"     ID: {test_doc.id_}")
        print(f"     Text length: {len(test_doc.text)}")
        print(f"     Metadata keys: {list(test_doc.metadata.keys())}")
        
        # Insert the document
        print("\n3. Inserting document into vector store...")
        print("   (This will embed the document and store it)")
        try:
            # Enable verbose logging
            import logging
            logging.basicConfig(level=logging.DEBUG)
            
            index.insert(test_doc)
            print("   ✓ Document inserted successfully!")
            print("   ✓ Embedding generated and stored")
            
        except Exception as e:
            print(f"   ❌ ERROR inserting document!")
            print(f"   Error type: {type(e).__name__}")
            print(f"   Error message: {str(e)}")
            print("\n   Full traceback:")
            import traceback
            traceback.print_exc()
            return
        
        # Wait a moment for database to sync
        print("\n4. Waiting for database to sync...")
        await asyncio.sleep(1)
        
        # Try to retrieve it
        print("\n5. Attempting to retrieve document...")
        try:
            from llama_index.core.retrievers import VectorIndexRetriever
            retriever = VectorIndexRetriever(
                index=index,
                similarity_top_k=5
            )
            nodes = retriever.retrieve("test station")
            print(f"   ✓ Retrieved {len(nodes)} nodes")
            
            if nodes:
                found_test = False
                for node in nodes:
                    if hasattr(node, 'node_id') and 'test' in str(node.node_id).lower():
                        found_test = True
                        break
                    if hasattr(node, 'metadata') and node.metadata.get('station_id') == 'test_123':
                        found_test = True
                        break
                
                if found_test:
                    print("   ✓ Test document found in retrieval!")
                else:
                    print("   ⚠️  Test document not found in retrieval (but other nodes were)")
            else:
                print("   ⚠️  No nodes retrieved")
        except Exception as e:
            print(f"   ❌ Error retrieving: {str(e)}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "=" * 60)
        print("Debug complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Check Supabase dashboard - look for table matching collection name")
        print("2. Run SQL query to check all tables:")
        print("   SELECT tablename FROM pg_tables WHERE schemaname = 'public';")
        print("3. Check vecs collection directly (if accessible)")
        
    except Exception as e:
        print(f"\n❌ Error during debug: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_insert())

