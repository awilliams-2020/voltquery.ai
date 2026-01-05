"""
Debug utilities for observability and tracing.

Provides global observability integration with LlamaIndex callbacks
to trace sub-questions across different bundles.
"""

from typing import Optional
from llama_index.core.callbacks import CallbackManager
from llama_index.core.callbacks.simple_llm_handler import SimpleLLMHandler
from llama_index.core.callbacks.schema import CBEventType


def setup_global_observability(
    handler_type: str = "simple",
    callback_manager: Optional[CallbackManager] = None
) -> CallbackManager:
    """
    Set up global observability for tracing sub-questions across bundles.
    
    This integrates llama_index.core.set_global_handler to enable tracing
    of sub-questions and tool calls across different bundles.
    
    Args:
        handler_type: Type of handler to use ("simple" or "verbose")
        callback_manager: Optional existing callback manager to extend
        
    Returns:
        CallbackManager instance configured with observability
    """
    from llama_index.core import set_global_handler
    
    # Set global handler for observability
    if handler_type == "simple":
        set_global_handler("simple")
    elif handler_type == "verbose":
        # For verbose mode, create a custom handler
        handler = SimpleLLMHandler()
        set_global_handler(handler)
    else:
        raise ValueError(f"Unknown handler_type: {handler_type}. Use 'simple' or 'verbose'")
    
    # Create or extend callback manager
    if callback_manager is None:
        callback_manager = CallbackManager()
    
    # Add simple handler to callback manager for tracing
    simple_handler = SimpleLLMHandler()
    callback_manager.add_handler(simple_handler)
    
    return callback_manager


def enable_debug_mode() -> None:
    """
    Enable debug mode with verbose logging.
    Convenience function for development.
    """
    setup_global_observability(handler_type="simple")
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("llama_index").setLevel(logging.DEBUG)

