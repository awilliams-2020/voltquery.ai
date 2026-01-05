from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.llm_service import LLMService

router = APIRouter()
llm_service = LLMService()


class LLMRequest(BaseModel):
    prompt: str


class LLMResponse(BaseModel):
    response: str
    mode: str


@router.post("/llm/chat", response_model=LLMResponse)
async def chat_with_llm(request: LLMRequest):
    """
    Chat with the configured LLM (Ollama or Gemini based on LLM_MODE).
    """
    try:
        llm = llm_service.get_llm()
        response = await llm.acomplete(request.prompt)
        
        # Extract text from response (LlamaIndex returns CompletionResponse objects)
        response_text = response.text if hasattr(response, "text") else str(response)
        
        return LLMResponse(
            response=response_text,
            mode=llm_service.settings.llm_mode
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/info")
async def get_llm_info():
    """
    Get information about the currently configured LLM.
    """
    try:
        llm = llm_service.get_llm()
        return {
            "mode": llm_service.settings.llm_mode,
            "model_type": type(llm).__name__,
            "model_name": getattr(llm, "model", "N/A") if hasattr(llm, "model") else "N/A",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

