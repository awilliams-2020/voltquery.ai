from typing import Optional, Union
from llama_index.core.llms import LLM
from llama_index.llms.ollama import Ollama
from llama_index.llms.gemini import Gemini
from llama_index.llms.openai import OpenAI
from pydantic_settings import BaseSettings


class LLMSettings(BaseSettings):
    llm_mode: str = "local"  # "local", "cloud" (Gemini), or "openai"
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    ollama_model: str = "llama2"  # Default Ollama model
    ollama_base_url: str = "http://localhost:11434"  # Default Ollama URL
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields from .env file


class LLMService:
    """
    Service for managing LLM instances based on LLM_MODE environment variable.
    - LLM_MODE=local: Uses Ollama (free, local development)
    - LLM_MODE=cloud: Uses Gemini (cloud deployment)
    - LLM_MODE=openai: Uses OpenAI (cloud deployment)
    """
    
    def __init__(self):
        self.settings = LLMSettings()
        self._llm: Optional[LLM] = None
    
    def get_llm(self) -> LLM:
        """
        Get the appropriate LLM instance based on LLM_MODE.
        Returns a singleton instance (creates if doesn't exist).
        """
        if self._llm is None:
            self._llm = self._create_llm()
        return self._llm
    
    def _create_llm(self) -> LLM:
        """
        Create LLM instance based on LLM_MODE setting.
        """
        if self.settings.llm_mode == "local":
            return self._create_ollama_llm()
        elif self.settings.llm_mode == "cloud":
            return self._create_gemini_llm()
        elif self.settings.llm_mode == "openai":
            return self._create_openai_llm()
        else:
            raise ValueError(
                f"Invalid LLM_MODE: {self.settings.llm_mode}. "
                "Must be 'local', 'cloud', or 'openai'"
            )
    
    def _create_ollama_llm(self) -> Ollama:
        """
        Create Ollama LLM instance for local development.
        """
        return Ollama(
            model=self.settings.ollama_model,
            base_url=self.settings.ollama_base_url,
            request_timeout=180.0,  # Increased to 3 minutes for complex prompts
            # Add generation limits to prevent hanging
            additional_kwargs={
                "num_predict": 512,  # Limit output tokens to prevent long generations
                "temperature": 0.7,
                "top_p": 0.9,
            },
            # Set context window to match model's actual capacity
            context_window=3900,  # Model reports 3900, not 4096
        )
    
    def _create_gemini_llm(self) -> Gemini:
        """
        Create Gemini LLM instance for cloud deployment.
        """
        if not self.settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY must be set when LLM_MODE=cloud"
            )
        
        return Gemini(
            api_key=self.settings.gemini_api_key,
            model_name="models/gemini-1.5-pro",
        )
    
    def _create_openai_llm(self) -> OpenAI:
        """
        Create OpenAI LLM instance for cloud deployment.
        """
        if not self.settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY must be set when LLM_MODE=openai"
            )
        
        return OpenAI(
            api_key=self.settings.openai_api_key,
            model="gpt-4o-mini",  # You can change this to gpt-4o, gpt-3.5-turbo, etc.
        )
    
    def reset(self):
        """
        Reset the LLM instance (useful for testing or reconfiguration).
        """
        self._llm = None

