#!/usr/bin/env python3
"""
Script to create the vecs cosine distance index for the vector store.
This fixes the warning: "Query does not have a covering index for IndexMeasure.cosine_distance"

Usage:
    # Run from host (if PostgreSQL is accessible from host)
    python scripts/create_vecs_index.py
    python scripts/create_vecs_index.py --llm-mode local   # For Ollama embeddings (768 dims)
    python scripts/create_vecs_index.py --llm-mode cloud    # For OpenAI embeddings (1536 dims)
    python scripts/create_vecs_index.py --llm-mode openai   # For OpenAI embeddings (1536 dims)
    
    # Run inside Docker container (recommended if PostgreSQL is in Docker)
    docker exec -it voltquery-backend python scripts/create_vecs_index.py
    docker exec -it voltquery-backend python scripts/create_vecs_index.py --llm-mode local
    docker exec -it voltquery-backend python scripts/create_vecs_index.py --llm-mode cloud
    docker exec -it voltquery-backend python scripts/create_vecs_index.py --llm-mode openai
"""

import sys
import argparse
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.vector_store_service import VectorStoreService
from app.services.llm_service import LLMService


def create_index(llm_mode: str = None):
    """
    Create the vecs cosine distance index.
    
    Args:
        llm_mode: LLM mode ("local", "cloud", or "openai")
                  - "local": Uses Ollama embeddings (768 dimensions)
                  - "cloud": Uses OpenAI embeddings (1536 dimensions)
                  - "openai": Uses OpenAI embeddings (1536 dimensions)
                  If None, will auto-detect from LLM_MODE environment variable or .env file
    """
    # Auto-detect LLM mode from environment if not provided
    if llm_mode is None:
        llm_service = LLMService()
        llm_mode = llm_service.settings.llm_mode if hasattr(llm_service.settings, 'llm_mode') else os.getenv("LLM_MODE", "local")
        print(f"🔍 Auto-detected LLM mode from environment: {llm_mode}")
    
    print("🔧 Creating vecs cosine distance index...")
    print(f"   Mode: {llm_mode}")
    print()
    
    try:
        # Initialize vector store service
        vector_store_service = VectorStoreService(llm_mode=llm_mode)
        
        # Ensure index exists
        vector_store_service.ensure_index_exists()
        
        print()
        print("✅ Index creation complete!")
        print()
        print("Note: If you still see warnings, the index may take a moment to build.")
        print("Large collections may take several minutes to index.")
        
    except Exception as e:
        print(f"❌ Error creating index: {e}")
        print()
        print("This warning is not critical - queries will still work but may be slower.")
        print("You can safely ignore it if performance is acceptable.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Create vecs cosine distance index for vector store"
    )
    parser.add_argument(
        "--llm-mode",
        type=str,
        default=None,
        choices=["local", "cloud", "openai"],
        help="LLM mode: 'local' (Ollama, 768 dims), 'cloud' or 'openai' (OpenAI, 1536 dims). "
             "If not specified, will auto-detect from LLM_MODE environment variable or .env file"
    )
    
    args = parser.parse_args()
    
    create_index(llm_mode=args.llm_mode)


if __name__ == "__main__":
    main()

