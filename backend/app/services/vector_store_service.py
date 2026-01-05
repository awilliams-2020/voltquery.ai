from typing import Optional
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.vector_stores.supabase import SupabaseVectorStore
from llama_index.core.embeddings import BaseEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.embeddings.ollama import OllamaEmbedding
from pydantic_settings import BaseSettings
from supabase import create_client, Client


class VectorStoreSettings(BaseSettings):
    supabase_url: str
    supabase_key: str
    # Use SUPABASE_DB_URL, fallback to DATABASE_URL for compatibility
    supabase_db_url: str = ""
    database_url: str = ""
    supabase_table_name: str = "energy_documents"  # Table name in Supabase
    openai_api_key: Optional[str] = None  # Required for cloud mode embeddings
    # Ollama configuration (for local mode)
    ollama_embedding_model: str = "nomic-embed-text"  # Ollama embedding model
    ollama_base_url: str = "http://localhost:11434"  # Ollama server URL
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields from .env file
    
    @property
    def db_url(self) -> str:
        """Get database URL, preferring SUPABASE_DB_URL."""
        url = self.supabase_db_url or self.database_url
        if not url:
            raise ValueError(
                "Either SUPABASE_DB_URL or DATABASE_URL must be set in environment variables"
            )
        return url


class VectorStoreService:
    """
    Service for managing Supabase Vector Store integration with LlamaIndex.
    Uses pgvector for storing embeddings.
    """
    
    def __init__(self, llm_mode: str = "local"):
        self.settings = VectorStoreSettings()
        self.llm_mode = llm_mode
        self._supabase_client: Optional[Client] = None
        self._vector_store: Optional[SupabaseVectorStore] = None
        self._embed_model: Optional[BaseEmbedding] = None
        self._index: Optional[VectorStoreIndex] = None
    
    def get_supabase_client(self) -> Client:
        """Get or create Supabase client."""
        if self._supabase_client is None:
            self._supabase_client = create_client(
                self.settings.supabase_url,
                self.settings.supabase_key
            )
        return self._supabase_client
    
    def get_embed_model(self) -> BaseEmbedding:
        """Get embedding model based on LLM_MODE."""
        if self._embed_model is None:
            if self.llm_mode == "local":
                # Use Ollama embeddings for local development
                # nomic-embed-text has 768 dimensions
                try:
                    self._embed_model = OllamaEmbedding(
                        model_name=self.settings.ollama_embedding_model,
                        base_url=self.settings.ollama_base_url
                    )
                except Exception as e:
                    error_msg = str(e)
                    if "404" in error_msg or "not found" in error_msg.lower():
                        raise ValueError(
                            f"Ollama embedding model '{self.settings.ollama_embedding_model}' not found. "
                            f"Please pull it first by running: ollama pull {self.settings.ollama_embedding_model}\n"
                            f"Make sure Ollama is running at {self.settings.ollama_base_url}"
                        ) from e
                    raise
            else:
                # Use OpenAI embeddings for cloud
                if not self.settings.openai_api_key:
                    raise ValueError(
                        "OPENAI_API_KEY must be set when LLM_MODE=cloud"
                    )
                self._embed_model = OpenAIEmbedding(
                    api_key=self.settings.openai_api_key,
                    model="text-embedding-3-small",
                    dimension=1536
                )
        return self._embed_model
    
    def get_embedding_dimension(self) -> int:
        """Get embedding dimension based on the model."""
        embed_model = self.get_embed_model()
        if self.llm_mode == "local":
            return 768  # Ollama nomic-embed-text dimension
        else:
            return 1536  # OpenAI text-embedding-3-small dimension
    
    def get_vector_store(self) -> SupabaseVectorStore:
        """Get or create Supabase Vector Store."""
        if self._vector_store is None:
            embed_dim = self.get_embedding_dimension()
            self._vector_store = SupabaseVectorStore(
                postgres_connection_string=self.settings.db_url,
                collection_name=self.settings.supabase_table_name,
                dimension=embed_dim,
            )
        return self._vector_store
    
    def get_index(self) -> VectorStoreIndex:
        """Get or create Vector Store Index."""
        if self._index is None:
            vector_store = self.get_vector_store()
            storage_context = StorageContext.from_defaults(
                vector_store=vector_store
            )
            self._index = VectorStoreIndex.from_vector_store(
                vector_store=vector_store,
                storage_context=storage_context,
                embed_model=self.get_embed_model()
            )
        return self._index
    
    
    def reset(self):
        """Reset all cached instances."""
        self._supabase_client = None
        self._vector_store = None
        self._embed_model = None
        self._index = None

