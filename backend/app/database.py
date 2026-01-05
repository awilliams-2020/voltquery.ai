from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    # Use SUPABASE_DB_URL if available, fallback to DATABASE_URL for compatibility
    database_url: str = ""
    supabase_db_url: str = ""
    
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


# Get database URL from environment
settings = DatabaseSettings()

# Create engine
engine = create_engine(
    settings.db_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

