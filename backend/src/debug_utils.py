"""
Debug utilities for observability and tracing.

Provides callback manager setup for LlamaIndex without verbose output.
"""

from typing import Optional
from llama_index.core.callbacks import CallbackManager


def setup_global_observability(
    handler_type: str = "simple",
    callback_manager: Optional[CallbackManager] = None
) -> CallbackManager:
    """
    Set up callback manager for observability without verbose output.
    
    Creates a callback manager that can be used for event tracking,
    but doesn't print prompts/messages to avoid cluttering logs.
    
    Args:
        handler_type: Ignored (kept for backward compatibility)
        callback_manager: Optional existing callback manager to extend
        
    Returns:
        CallbackManager instance (no handlers added to avoid verbose output)
    """
    # Create or extend callback manager
    if callback_manager is None:
        callback_manager = CallbackManager()
    
    # Don't add any handlers to avoid printing prompts/messages
    # The callback manager can still be used for event tracking if needed
    # but won't produce verbose output
    
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

