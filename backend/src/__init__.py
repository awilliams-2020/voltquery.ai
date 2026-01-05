"""
Modular Tool-Bundle Architecture for RAG System.

This package provides:
- Bundles: Domain-specific tool implementations (solar, transportation, utility, optimization)
- Orchestrator: SubQuestionQueryEngine initialization and tool registration
- GlobalSettings: Centralized financial and analysis parameters
- Debug utilities: Observability and tracing support
"""

from src.global_settings import get_global_settings, set_global_settings, GlobalSettings
from src.orchestrator import RAGOrchestrator, ToolNameMappingParser
from src.debug_utils import setup_global_observability, enable_debug_mode

__all__ = [
    "get_global_settings",
    "set_global_settings",
    "GlobalSettings",
    "RAGOrchestrator",
    "ToolNameMappingParser",
    "setup_global_observability",
    "enable_debug_mode",
]

