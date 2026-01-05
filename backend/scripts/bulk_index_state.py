#!/usr/bin/env python3
"""
Bulk indexing script for NREL EV stations by state.

This script downloads all stations for a target state and bulk embeds them
using Ollama (free, local). Perfect for local development and over-indexing.

Usage:
    python scripts/bulk_index_state.py --state OH
    python scripts/bulk_index_state.py --state CA --limit 1000  # Limit for testing
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.nrel_client import NRELClient
from app.services.document_service import DocumentService
from app.services.vector_store_service import VectorStoreService
from app.services.llm_service import LLMService


async def bulk_index_state(
    state: str,
    llm_mode: str = "local",
    batch_size: int = 100,
    limit: int = None
):
    """
    Bulk index all stations for a state.
    
    Args:
        state: 2-letter US state code (e.g., "OH")
        llm_mode: LLM mode ("local" or "cloud")
        batch_size: Number of stations to process in each batch
        limit: Optional limit on total stations to index (for testing)
    """
    print(f"🚀 Starting bulk indexing for state: {state}")
    print(f"   Mode: {llm_mode}")
    print(f"   Batch size: {batch_size}")
    if limit:
        print(f"   Limit: {limit} stations")
    print()
    
    # Initialize services
    print("📡 Initializing services...")
    nrel_client = NRELClient()
    document_service = DocumentService()
    
    # Get LLM mode from environment or use default
    llm_service = LLMService()
    actual_llm_mode = llm_service.settings.llm_mode if hasattr(llm_service.settings, 'llm_mode') else llm_mode
    
    vector_store_service = VectorStoreService(llm_mode=actual_llm_mode)
    
    # Pre-check: Verify embedding model is available before proceeding
    print("   Checking embedding model...")
    try:
        embed_model = vector_store_service.get_embed_model()
        # Test the embedding model with a simple query to ensure it works
        test_embedding = await embed_model.aget_text_embedding("test")
        print(f"   ✅ Embedding model ready (dimension: {len(test_embedding)})")
    except ValueError as e:
        print(f"   ❌ {e}")
        print()
        print("💡 To fix this:")
        if actual_llm_mode == "local":
            print(f"   1. Make sure Ollama is running: ollama serve")
            print(f"   2. Pull the embedding model: ollama pull nomic-embed-text")
        else:
            print(f"   1. Set OPENAI_API_KEY in your .env file")
        print()
        return
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg or "not found" in error_msg.lower():
            print(f"   ❌ Embedding model not found: {error_msg}")
            print()
            print("💡 To fix this:")
            if actual_llm_mode == "local":
                print(f"   1. Make sure Ollama is running: ollama serve")
                print(f"   2. Pull the embedding model: ollama pull nomic-embed-text")
            else:
                print(f"   1. Set OPENAI_API_KEY in your .env file")
            print()
            return
        print(f"   ❌ Error initializing embedding model: {e}")
        print()
        return
    
    index = vector_store_service.get_index()
    
    print("✅ Services initialized")
    print()
    
    # Fetch all stations for the state
    print(f"📥 Fetching stations for {state}...")
    try:
        if limit:
            # Fetch limited number for testing
            stations = await nrel_client.get_stations_by_state(
                state=state,
                limit=limit
            )
        else:
            # Fetch all stations
            stations = await nrel_client.get_all_stations_by_state(state=state)
        
        total_stations = len(stations)
        print(f"✅ Fetched {total_stations} stations")
        print()
        
        if total_stations == 0:
            print("⚠️  No stations found for this state.")
            return
        
    except Exception as e:
        print(f"❌ Error fetching stations: {e}")
        return
    
    # Process in batches
    print(f"🔄 Processing {total_stations} stations in batches of {batch_size}...")
    print()
    
    indexed_count = 0
    skipped_count = 0
    
    for i in range(0, total_stations, batch_size):
        batch = stations[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_stations + batch_size - 1) // batch_size
        
        print(f"📦 Processing batch {batch_num}/{total_batches} ({len(batch)} stations)...")
        
        try:
            # Convert to documents
            documents = document_service.stations_to_documents(batch)
            
            # Bulk insert documents for better performance
            # This allows the embedding model to process multiple texts in batch
            try:
                # Bulk insert entire batch at once
                index.insert(documents)
                indexed_count += len(documents)
                print(f"   ✅ Bulk indexed {len(documents)} stations (Total: {indexed_count}/{total_stations})")
            except ValueError as e:
                # Model not found errors should have been caught earlier, but handle gracefully
                error_msg = str(e)
                if "not found" in error_msg.lower() or "404" in error_msg:
                    print(f"   ❌ Critical error: {error_msg}")
                    print(f"   💡 Please pull the embedding model: ollama pull nomic-embed-text")
                    return
                # If bulk insert fails, fall back to individual inserts
                print(f"   ⚠️  Bulk insert failed, falling back to individual inserts: {str(e)[:100]}")
                for doc in documents:
                    try:
                        index.insert(doc)
                        indexed_count += 1
                    except ValueError as doc_e:
                        error_msg = str(doc_e)
                        if "not found" in error_msg.lower() or "404" in error_msg:
                            print(f"   ❌ Critical error: {error_msg}")
                            print(f"   💡 Please pull the embedding model: ollama pull nomic-embed-text")
                            return
                        skipped_count += 1
                        if skipped_count <= 5:  # Only print first few errors
                            print(f"   ⚠️  Skipped station: {str(doc_e)[:100]}")
                    except Exception as doc_e:
                        skipped_count += 1
                        if skipped_count <= 5:  # Only print first few errors
                            print(f"   ⚠️  Skipped station: {str(doc_e)[:100]}")
            except Exception as e:
                # If bulk insert fails with other error, fall back to individual inserts
                print(f"   ⚠️  Bulk insert failed, falling back to individual inserts: {str(e)[:100]}")
                for doc in documents:
                    try:
                        index.insert(doc)
                        indexed_count += 1
                    except Exception as doc_e:
                        skipped_count += 1
                        if skipped_count <= 5:  # Only print first few errors
                            print(f"   ⚠️  Skipped station: {str(doc_e)[:100]}")
            
            print()
            
        except Exception as e:
            print(f"   ❌ Error processing batch: {e}")
            print()
            continue
    
    # Summary
    print("=" * 60)
    print("📊 Indexing Summary")
    print("=" * 60)
    print(f"State: {state}")
    print(f"Total stations fetched: {total_stations}")
    print(f"Successfully indexed: {indexed_count}")
    print(f"Skipped/errors: {skipped_count}")
    print(f"Success rate: {(indexed_count/total_stations*100):.1f}%")
    print("=" * 60)
    print()
    print("✅ Bulk indexing complete!")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk index NREL EV stations for a state"
    )
    parser.add_argument(
        "--state",
        type=str,
        required=True,
        help="2-letter US state code (e.g., OH, CA, NY)"
    )
    parser.add_argument(
        "--llm-mode",
        type=str,
        default="local",
        choices=["local", "cloud"],
        help="LLM mode (default: local)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of stations to process per batch (default: 100)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit total stations to index (for testing)"
    )
    
    args = parser.parse_args()
    
    # Validate state code
    if len(args.state) != 2:
        print("❌ Error: State code must be 2 letters (e.g., OH, CA)")
        sys.exit(1)
    
    # Run async function
    asyncio.run(bulk_index_state(
        state=args.state.upper(),
        llm_mode=args.llm_mode,
        batch_size=args.batch_size,
        limit=args.limit
    ))


if __name__ == "__main__":
    main()

