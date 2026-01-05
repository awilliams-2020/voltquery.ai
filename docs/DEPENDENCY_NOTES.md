# Dependency Notes

## Known Conflicts

### HTTPX Version Conflict
- **Supabase** requires: `httpx<0.25.0,>=0.24.0`
- **Ollama** requires: `httpx>=0.27`

**Status**: This is a known conflict. The `ollama` package will show a warning, but `llama-index-llms-ollama` should still work because:
1. LlamaIndex packages manage their own HTTP clients internally
2. The `ollama` package is a transitive dependency, not directly used
3. When making requests, LlamaIndex uses its own httpx instance

**Impact**: Low - functionality should work despite the warning.

### Resolution
- Keep `httpx==0.24.1` for Supabase compatibility
- Accept the warning from `ollama` package
- Test Ollama functionality to ensure it works

## Pydantic Version
- **Updated to**: `pydantic>=2.11.5` (required by llama-index packages)
- **Compatible with**: FastAPI 0.109.0

## LlamaIndex Version Constraints

### Core Version
- **Required**: `llama-index-core>=0.10.5,<0.11.0`
- **Reason**: All llama-index integration packages require core <0.11.0
- **Note**: RouterQueryEngine uses `LLMSingleSelector` (in core) instead of `PydanticSingleSelector`
  to avoid requiring `llama-index-program-openai` (which has version conflicts with core 0.10.x)

### Pillow Version
- **Required**: `pillow>=10.2.0,<11.0.0`
- **Reason**: `llama-index-llms-gemini` requires pillow <11.0.0

## Testing
To verify everything works:
```bash
source venv/bin/activate
python -c "from app.services.llm_service import LLMService; print('✓ LLM Service works')"
python -c "from app.services.vector_store_service import VectorStoreService; print('✓ Vector Store works')"
python -c "from app.services.rag_service import RAGService; print('✓ RAG Service works')"
```

