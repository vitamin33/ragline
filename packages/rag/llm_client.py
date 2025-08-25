"""
LLM Client for RAGline

Unified client for OpenAI API and local models (via OPENAI_API_BASE override).
Includes retry logic, timeout handling, and streaming support.
"""

import asyncio
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
import time

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


class LLMConfig(BaseModel):
    """LLM client configuration."""
    
    # API Configuration
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_BASE"))
    organization: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_ORG_ID"))
    
    # Model Configuration
    model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=0.7)
    max_tokens: Optional[int] = Field(default=1000)
    
    # Retry Configuration
    max_retries: int = Field(default=3)
    retry_delay: float = Field(default=1.0)
    retry_backoff: float = Field(default=2.0)
    
    # Timeout Configuration
    request_timeout: float = Field(default=60.0)
    stream_timeout: float = Field(default=120.0)
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.api_key and not self.base_url:
            logger.warning("No OpenAI API key or base URL provided. Set OPENAI_API_KEY or OPENAI_API_BASE.")


class ChatMessage(BaseModel):
    """Chat message model compatible with OpenAI format."""
    role: str = Field(..., description="Message role: user, assistant, system, tool")
    content: Optional[str] = Field(None, description="Message content")
    name: Optional[str] = Field(None, description="Name of the message sender")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Tool calls")
    tool_call_id: Optional[str] = Field(None, description="Tool call ID for tool responses")


class LLMResponse(BaseModel):
    """LLM response model."""
    content: str = Field(default="")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None)
    finish_reason: Optional[str] = Field(None)
    usage: Optional[Dict[str, Any]] = Field(None)  # Changed from int to Any to handle complex usage objects
    model: Optional[str] = Field(None)


class LLMClient:
    """
    Unified LLM client supporting OpenAI API and local models.
    
    Features:
    - Automatic retry with exponential backoff
    - Timeout handling for requests and streams
    - Support for tool calling
    - Streaming and non-streaming responses
    - Local model support via OPENAI_API_BASE override
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """Initialize LLM client with configuration."""
        self.config = config or LLMConfig()
        self._client: Optional[AsyncOpenAI] = None
        
        # Initialize client
        self._init_client()
        
        logger.info(f"LLM Client initialized with model: {self.config.model}")
        if self.config.base_url:
            logger.info(f"Using custom base URL: {self.config.base_url}")
    
    def _init_client(self):
        """Initialize OpenAI client with configuration."""
        try:
            client_kwargs = {
                "api_key": self.config.api_key,
                "timeout": self.config.request_timeout,
                "max_retries": 0,  # We handle retries manually
            }
            
            if self.config.base_url:
                client_kwargs["base_url"] = self.config.base_url
                logger.info(f"Configured for local model at: {self.config.base_url}")
            
            if self.config.organization:
                client_kwargs["organization"] = self.config.organization
            
            self._client = AsyncOpenAI(**client_kwargs)
            
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise
    
    async def _retry_with_backoff(self, func, *args, **kwargs):
        """Execute function with retry logic and exponential backoff."""
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            
            except openai.RateLimitError as e:
                last_exception = e
                if attempt < self.config.max_retries:
                    wait_time = self.config.retry_delay * (self.config.retry_backoff ** attempt)
                    logger.warning(f"Rate limit hit, retrying in {wait_time:.1f}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait_time)
                    continue
                raise
                
            except (openai.APITimeoutError, openai.APIConnectionError) as e:
                last_exception = e
                if attempt < self.config.max_retries:
                    wait_time = self.config.retry_delay * (self.config.retry_backoff ** attempt)
                    logger.warning(f"API error, retrying in {wait_time:.1f}s (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(wait_time)
                    continue
                raise
                
            except openai.APIError as e:
                # Don't retry on client errors (4xx)
                if hasattr(e, 'status_code') and 400 <= e.status_code < 500:
                    logger.error(f"Client error (no retry): {e}")
                    raise
                
                last_exception = e
                if attempt < self.config.max_retries:
                    wait_time = self.config.retry_delay * (self.config.retry_backoff ** attempt)
                    logger.warning(f"Server error, retrying in {wait_time:.1f}s (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(wait_time)
                    continue
                raise
                
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise
        
        # If we get here, all retries failed
        raise last_exception
    
    async def chat_completion(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        **kwargs
    ) -> Union[LLMResponse, AsyncGenerator[Dict[str, Any], None]]:
        """
        Create chat completion with optional tool calling and streaming.
        
        Args:
            messages: List of chat messages
            tools: Optional list of tools for function calling
            stream: Enable streaming response
            **kwargs: Additional OpenAI API parameters
        
        Returns:
            LLMResponse for non-streaming, AsyncGenerator for streaming
        """
        
        if not self._client:
            raise RuntimeError("LLM client not initialized")
        
        # Convert messages to OpenAI format
        openai_messages = [
            {
                "role": msg.role,
                "content": msg.content,
                **({k: v for k, v in {
                    "name": msg.name,
                    "tool_calls": msg.tool_calls,
                    "tool_call_id": msg.tool_call_id
                }.items() if v is not None})
            }
            for msg in messages
        ]
        
        # Prepare request parameters
        request_params = {
            "model": kwargs.get("model", self.config.model),
            "messages": openai_messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "stream": stream,
        }
        
        # Add tools if provided
        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = kwargs.get("tool_choice", "auto")
        
        if stream:
            return self._stream_completion(request_params)
        else:
            return await self._complete_chat(request_params)
    
    async def _complete_chat(self, params: Dict[str, Any]) -> LLMResponse:
        """Complete non-streaming chat request."""
        async def _make_request():
            response = await self._client.chat.completions.create(**params)
            return response
        
        response = await self._retry_with_backoff(_make_request)
        
        choice = response.choices[0]
        message = choice.message
        
        # Handle usage data safely
        usage_data = None
        if response.usage:
            try:
                usage_data = response.usage.model_dump()
            except Exception:
                # Fallback to basic usage info if validation fails
                usage_data = {
                    "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0),
                    "completion_tokens": getattr(response.usage, 'completion_tokens', 0),
                    "total_tokens": getattr(response.usage, 'total_tokens', 0)
                }
        
        # Handle tool calls safely
        tool_calls_data = None
        if message.tool_calls:
            try:
                if hasattr(message.tool_calls, 'model_dump'):
                    tool_calls_data = message.tool_calls.model_dump()
                else:
                    # Convert tool calls to dict format
                    tool_calls_data = [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in message.tool_calls
                    ]
            except Exception as e:
                logger.warning(f"Error processing tool calls: {e}")
                tool_calls_data = None
        
        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls_data,
            finish_reason=choice.finish_reason,
            usage=usage_data,
            model=response.model
        )
    
    async def _stream_completion(self, params: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream chat completion with timeout handling."""
        async def _make_stream():
            return await self._client.chat.completions.create(**params)
        
        stream = await self._retry_with_backoff(_make_stream)
        
        try:
            start_time = time.time()
            async for chunk in stream:
                # Check stream timeout
                if time.time() - start_time > self.config.stream_timeout:
                    logger.warning("Stream timeout exceeded")
                    break
                
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue
                
                # Extract chunk data
                chunk_data = {
                    "id": chunk.id,
                    "model": chunk.model,
                    "created": chunk.created,
                }
                
                delta = choice.delta
                if delta:
                    if delta.content:
                        chunk_data.update({
                            "type": "content",
                            "delta": {"content": delta.content},
                            "finish_reason": choice.finish_reason
                        })
                    
                    if delta.tool_calls:
                        # Convert tool calls to dict format
                        tool_calls_data = []
                        for tc in delta.tool_calls:
                            tool_call_dict = {
                                "id": getattr(tc, 'id', None),
                                "type": getattr(tc, 'type', 'function'),
                                "function": {
                                    "name": getattr(tc.function, 'name', None) if tc.function else None,
                                    "arguments": getattr(tc.function, 'arguments', None) if tc.function else None
                                }
                            }
                            tool_calls_data.append(tool_call_dict)
                        
                        chunk_data.update({
                            "type": "tool_calls",
                            "delta": {"tool_calls": tool_calls_data},
                            "finish_reason": choice.finish_reason
                        })
                
                if choice.finish_reason:
                    chunk_data["finish_reason"] = choice.finish_reason
                
                yield chunk_data
                
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield {"type": "error", "error": str(e)}
        finally:
            # Ensure stream is closed
            if hasattr(stream, 'close'):
                await stream.close()
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on LLM service."""
        try:
            # Simple completion to test API connectivity
            response = await self.chat_completion(
                messages=[ChatMessage(role="user", content="Hello")],
                stream=False
            )
            
            return {
                "status": "healthy",
                "model": self.config.model,
                "base_url": self.config.base_url or "openai",
                "response_length": len(response.content),
                "usage": response.usage
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "model": self.config.model,
                "base_url": self.config.base_url or "openai"
            }


# Default client instance
_default_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create default LLM client instance."""
    global _default_client
    
    if _default_client is None:
        _default_client = LLMClient()
    
    return _default_client


def configure_llm_client(config: LLMConfig):
    """Configure global LLM client."""
    global _default_client
    _default_client = LLMClient(config)


# Convenience functions
async def chat(messages: List[ChatMessage], **kwargs) -> LLMResponse:
    """Convenience function for non-streaming chat."""
    client = get_llm_client()
    return await client.chat_completion(messages, stream=False, **kwargs)


async def stream_chat(messages: List[ChatMessage], **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
    """Convenience function for streaming chat."""
    client = get_llm_client()
    async for chunk in await client.chat_completion(messages, stream=True, **kwargs):
        yield chunk