"""
RAGline LLM Tools Package

This package contains tool implementations for LLM function calling.
Each tool provides specific functionality that can be called by the AI assistant.
"""

from .apply_promos import ApplyPromosTool
from .base import BaseTool, ToolError, ToolResult
from .confirm import ConfirmTool
from .retrieve_menu import RetrieveMenuTool

# Tool registry for easy access
TOOLS = {
    "retrieve_menu": RetrieveMenuTool,
    "apply_promos": ApplyPromosTool,
    "confirm": ConfirmTool,
}

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolError",
    "RetrieveMenuTool",
    "ApplyPromosTool",
    "ConfirmTool",
    "TOOLS",
]
