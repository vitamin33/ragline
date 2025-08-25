"""
Base tool interface for RAGline LLM tools.

Defines the common structure and behavior for all LLM tools.
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standard tool execution result."""
    success: bool = Field(..., description="Whether the tool executed successfully")
    data: Optional[Any] = Field(None, description="Tool output data")
    error: Optional[str] = Field(None, description="Error message if failed")
    latency_ms: float = Field(..., description="Execution time in milliseconds")
    timestamp: datetime = Field(default_factory=datetime.now)


class ToolError(Exception):
    """Custom exception for tool execution errors."""
    pass


class BaseTool(ABC):
    """
    Abstract base class for all LLM tools.
    
    Each tool must implement:
    - execute(): Core tool functionality
    - get_schema(): OpenAI function schema
    - validate_args(): Argument validation
    """
    
    def __init__(self, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
        """Initialize tool with context."""
        self.tenant_id = tenant_id
        self.user_id = user_id
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name identifier."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM."""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """
        Execute the tool with given arguments.
        
        Args:
            **kwargs: Tool-specific arguments
            
        Returns:
            Tool execution result
            
        Raises:
            ToolError: If execution fails
        """
        pass
    
    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """
        Return OpenAI function schema for this tool.
        
        Returns:
            OpenAI function definition
        """
        pass
    
    def validate_args(self, **kwargs) -> Dict[str, Any]:
        """
        Validate tool arguments.
        
        Args:
            **kwargs: Arguments to validate
            
        Returns:
            Validated arguments
            
        Raises:
            ToolError: If validation fails
        """
        # Default implementation - subclasses can override
        return kwargs
    
    async def run(self, **kwargs) -> ToolResult:
        """
        Execute tool with timing and error handling.
        
        Args:
            **kwargs: Tool arguments
            
        Returns:
            ToolResult with execution details
        """
        start_time = time.time()
        
        try:
            # Validate arguments
            validated_args = self.validate_args(**kwargs)
            
            # Execute tool
            result = await self.execute(**validated_args)
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            
            return ToolResult(
                success=True,
                data=result,
                latency_ms=latency_ms
            )
            
        except ToolError as e:
            latency_ms = (time.time() - start_time) * 1000
            return ToolResult(
                success=False,
                error=str(e),
                latency_ms=latency_ms
            )
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return ToolResult(
                success=False,
                error=f"Unexpected error: {str(e)}",
                latency_ms=latency_ms
            )
    
    def to_openai_function(self) -> Dict[str, Any]:
        """Convert tool to OpenAI function definition."""
        schema = self.get_schema()
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema
            }
        }