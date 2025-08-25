"""
Chat endpoint with streaming support via SSE and WebSocket.
Supports tool calling and RAG-enhanced responses.
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Use StreamingResponse instead of EventSourceResponse for now
try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:
    # Fallback to StreamingResponse if sse-starlette not available
    EventSourceResponse = StreamingResponse


class ChatMessage(BaseModel):
    """Chat message model."""
    role: str = Field(..., description="Message role: user, assistant, system")
    content: str = Field(..., description="Message content")
    timestamp: Optional[datetime] = None


class ChatRequest(BaseModel):
    """Chat request payload."""
    messages: List[ChatMessage] = Field(..., description="Conversation messages")
    stream: bool = Field(default=True, description="Enable streaming response")
    tools_enabled: bool = Field(default=True, description="Enable tool calling")
    tenant_id: Optional[str] = Field(None, description="Tenant ID for multi-tenancy")
    user_id: Optional[str] = Field(None, description="User ID for context")


class ChatResponse(BaseModel):
    """Chat response payload."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    choices: List[Dict[str, Any]] = Field(default_factory=list)
    usage: Optional[Dict[str, int]] = None
    created: int = Field(default_factory=lambda: int(datetime.now().timestamp()))


class ToolCall(BaseModel):
    """Tool call event model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str = Field(default="function")
    function: Dict[str, Any] = Field(..., description="Function details")


router = APIRouter()


# Connection manager for WebSocket connections
class ConnectionManager:
    """Manages WebSocket connections for real-time chat."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
    
    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)


manager = ConnectionManager()


async def generate_chat_stream(request: ChatRequest) -> AsyncGenerator[str, None]:
    """Generate streaming chat response with tool calling support."""
    
    # TODO: Initialize LLM client
    # TODO: Process messages and context
    # TODO: Handle RAG retrieval if needed
    # TODO: Execute tool calls if requested
    
    # Mock streaming response for now
    response_chunks = [
        "I'm",
        " a",
        " RAGline",
        " LLM",
        " service",
        " with",
        " RAG",
        " capabilities.",
        " I can",
        " help",
        " with",
        " tool",
        " calling",
        " and",
        " streaming",
        " responses."
    ]
    
    for i, chunk in enumerate(response_chunks):
        # Simulate tool call at chunk 5
        if i == 5 and request.tools_enabled:
            tool_call = ToolCall(
                function={
                    "name": "retrieve_menu",
                    "arguments": json.dumps({"query": "popular items"})
                }
            )
            
            # Emit tool call event
            yield f"data: {json.dumps({'type': 'tool_call', 'tool_call': tool_call.dict()})}\n\n"
            
            # Simulate tool execution delay
            await asyncio.sleep(0.1)
            
            # Emit tool result
            tool_result = {
                "type": "tool_result",
                "tool_call_id": tool_call.id,
                "result": "Found 3 popular menu items"
            }
            yield f"data: {json.dumps(tool_result)}\n\n"
        
        # Emit text chunk
        chunk_data = {
            "type": "text",
            "delta": {"content": chunk},
            "finish_reason": None if i < len(response_chunks) - 1 else "stop"
        }
        
        yield f"data: {json.dumps(chunk_data)}\n\n"
        
        # Simulate streaming delay
        await asyncio.sleep(0.05)
    
    # Final done event
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


@router.post("/completions", response_model=ChatResponse)
async def chat_completions(request: ChatRequest):
    """
    Create chat completion with optional streaming.
    
    Supports:
    - Tool calling (retrieve_menu, apply_promos, confirm)
    - RAG-enhanced responses
    - Multi-tenant context isolation
    """
    
    if request.stream:
        return StreamingResponse(
            generate_chat_stream(request),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream"
            }
        )
    else:
        # Non-streaming response
        # TODO: Implement non-streaming chat completion
        return ChatResponse(
            choices=[{
                "message": {
                    "role": "assistant",
                    "content": "Non-streaming response not yet implemented"
                },
                "finish_reason": "stop"
            }],
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        )


@router.get("/stream")
async def chat_stream_sse(messages: str, tools_enabled: bool = True):
    """
    Server-Sent Events endpoint for chat streaming.
    Alternative to WebSocket for simpler clients.
    """
    
    try:
        parsed_messages = json.loads(messages)
        request = ChatRequest(
            messages=[ChatMessage(**msg) for msg in parsed_messages],
            stream=True,
            tools_enabled=tools_enabled
        )
        
        return EventSourceResponse(generate_chat_stream(request))
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid messages format")


@router.websocket("/ws/{client_id}")
async def websocket_chat(websocket: WebSocket, client_id: str):
    """
    WebSocket endpoint for real-time chat.
    Supports bidirectional communication and tool calling.
    """
    
    await manager.connect(websocket, client_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            try:
                request_data = json.loads(data)
                request = ChatRequest(**request_data)
                
                # Generate and stream response
                async for chunk in generate_chat_stream(request):
                    # Extract data part from SSE format
                    if chunk.startswith("data: "):
                        message_data = chunk[6:].strip()
                        if message_data:
                            await manager.send_personal_message(message_data, client_id)
                
            except (json.JSONDecodeError, ValueError) as e:
                error_msg = json.dumps({"type": "error", "message": f"Invalid request: {str(e)}"})
                await manager.send_personal_message(error_msg, client_id)
                
    except WebSocketDisconnect:
        manager.disconnect(client_id)


@router.get("/tools")
async def list_available_tools():
    """List available tools for LLM function calling."""
    
    return {
        "tools": [
            {
                "name": "retrieve_menu",
                "description": "Retrieve menu items based on query or filters",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "category": {"type": "string", "description": "Menu category filter"}
                    }
                }
            },
            {
                "name": "apply_promos", 
                "description": "Apply promotional codes or discounts",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "promo_code": {"type": "string", "description": "Promotional code"},
                        "order_id": {"type": "string", "description": "Order ID to apply promo to"}
                    }
                }
            },
            {
                "name": "confirm",
                "description": "Confirm order or action with user",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "action": {"type": "string", "description": "Action to confirm"},
                        "details": {"type": "object", "description": "Action details"}
                    }
                }
            }
        ]
    }