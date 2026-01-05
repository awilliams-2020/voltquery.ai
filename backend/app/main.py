from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.routers import stations, llm, rag, stripe, history, electricity, urdb
import os

app = FastAPI(title="NREL RAG SaaS API", version="1.0.0")

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
app.include_router(history.router, prefix="/api", tags=["history"])
app.include_router(electricity.router, prefix="/api", tags=["electricity"])
app.include_router(urdb.router, prefix="/api", tags=["urdb"])


@app.get("/")
async def root():
    return {"message": "NREL RAG SaaS API"}


@app.get("/health")
async def health():
    return {"status": "healthy"}

