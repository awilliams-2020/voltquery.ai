from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import stations, llm, rag, stripe, history, electricity, urdb, clerk
from app.services.vector_store_service import VectorStoreService
from app.services.llm_service import LLMService
import os
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="VoltQuery.ai API", version="1.0.0")

# Configure CORS - allow frontend URL from environment variable
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
# Allow both the configured frontend URL and localhost for development
cors_origins = [
    frontend_url,
    "http://localhost:3000",  # Local development
    "https://voltquery.ai",  # Production frontend
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(stations.router, prefix="/api", tags=["stations"])
app.include_router(llm.router, prefix="/api", tags=["llm"])
app.include_router(rag.router, prefix="/api", tags=["rag"])
app.include_router(stripe.router, prefix="/api", tags=["stripe"])
app.include_router(clerk.router, prefix="/api", tags=["clerk"])
app.include_router(history.router, prefix="/api", tags=["history"])
app.include_router(electricity.router, prefix="/api", tags=["electricity"])
app.include_router(urdb.router, prefix="/api", tags=["urdb"])


@app.get("/")
async def root():
    return {"message": "VoltQuery.ai API"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.on_event("startup")
async def startup_event():
    """
    Ensure the vecs cosine distance index exists on startup.
    This is idempotent - it won't recreate if the index already exists.
    """
    try:
        # Auto-detect LLM mode
        llm_service = LLMService()
        llm_mode = llm_service.settings.llm_mode if hasattr(llm_service.settings, 'llm_mode') else os.getenv("LLM_MODE", "local")
        
        # Ensure index exists (idempotent operation)
        vector_store_service = VectorStoreService(llm_mode=llm_mode)
        vector_store_service.ensure_index_exists()
        logger.info(f"Vector store index verified/created for LLM mode: {llm_mode}")
    except Exception as e:
        # Don't fail startup if index creation fails - it's just a performance optimization
        logger.warning(f"Could not ensure vector store index exists on startup: {e}. This is not critical.")

