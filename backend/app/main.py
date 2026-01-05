from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.routers import stations, llm, rag, stripe, history, electricity, urdb

app = FastAPI(title="NREL RAG SaaS API", version="1.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js default port
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

