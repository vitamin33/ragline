"""
RAGline LLM Tools Package

This package contains tool implementations for LLM function calling.
Each tool provides specific functionality that can be called by the AI assistant.
"""

from .apply_promos import ApplyPromosTool
from .base import BaseTool, ToolError, ToolResult
from .confirm import ConfirmTool
from .knowledge.search_knowledge_base import SearchKnowledgeBaseTool
from .retrieve_menu import RetrieveMenuTool

# Tool registry for easy access
TOOLS = {
    "retrieve_menu": RetrieveMenuTool,
    "apply_promos": ApplyPromosTool,
    "confirm": ConfirmTool,
    "search_knowledge_base": SearchKnowledgeBaseTool,
}

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolError",
    "RetrieveMenuTool",
    "ApplyPromosTool",
    "ConfirmTool",
    "SearchKnowledgeBaseTool",
    "TOOLS",
]
