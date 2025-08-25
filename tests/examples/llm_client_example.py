#!/usr/bin/env python3
"""
Test script for LLM client functionality.
Run this to test OpenAI integration and local model support.
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add packages to path
sys.path.insert(0, 'packages')

from rag.llm_client import LLMClient, LLMConfig, ChatMessage


async def test_llm_client():
    """Test LLM client with different configurations."""
    
    print("🧪 Testing RAGline LLM Client")
    print("=" * 50)
    
    # Test 1: Health check without API key
    print("\n1. Testing client initialization...")
    config = LLMConfig(
        model="gpt-4o-mini",
        max_tokens=100,
        temperature=0.7
    )
    
    client = LLMClient(config)
    health = await client.health_check()
    print(f"Health check: {health['status']}")
    
    if health['status'] == 'unhealthy':
        print(f"Error: {health.get('error', 'Unknown error')}")
        print("\n📝 TO ADD API KEY:")
        print("   1. Set environment variable: export OPENAI_API_KEY='your-key-here'")
        print("   2. Or create a .env file with: OPENAI_API_KEY=your-key-here")
        print("   3. Or pass it directly to LLMConfig(api_key='your-key')")
        
        print("\n🏠 FOR LOCAL MODELS:")
        print("   1. Set OPENAI_API_BASE='http://localhost:1234/v1' (for LM Studio)")
        print("   2. Or OPENAI_API_BASE='http://localhost:11434/v1' (for Ollama)")
        print("   3. Set OPENAI_API_KEY='not-needed' (any value for local models)")
        return
    
    # Test 2: Simple chat completion
    print("\n2. Testing non-streaming chat...")
    messages = [
        ChatMessage(role="system", content="You are a helpful assistant for RAGline."),
        ChatMessage(role="user", content="Hello! What can you do?")
    ]
    
    try:
        response = await client.chat_completion(messages, stream=False)
        print(f"Response: {response.content[:100]}...")
        print(f"Model: {response.model}")
        print(f"Usage: {response.usage}")
        
    except Exception as e:
        print(f"Chat completion error: {e}")
        return
    
    # Test 3: Streaming chat
    print("\n3. Testing streaming chat...")
    try:
        stream_messages = [
            ChatMessage(role="user", content="Count to 5 slowly")
        ]
        
        print("Streaming response: ", end="", flush=True)
        async for chunk in await client.chat_completion(stream_messages, stream=True):
            if chunk.get("type") == "content" and chunk.get("delta", {}).get("content"):
                print(chunk["delta"]["content"], end="", flush=True)
        
        print("\n✅ Streaming test completed")
        
    except Exception as e:
        print(f"Streaming error: {e}")
        return
    
    # Test 4: Tool calling (mock)
    print("\n4. Testing tool calling...")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"}
                    },
                    "required": ["location"]
                }
            }
        }
    ]
    
    tool_messages = [
        ChatMessage(role="user", content="What's the weather in San Francisco?")
    ]
    
    try:
        response = await client.chat_completion(
            tool_messages, 
            tools=tools,
            stream=False
        )
        
        if response.tool_calls:
            print("✅ Tool calling supported")
            print(f"Tool calls: {len(response.tool_calls)} calls made")
        else:
            print("ℹ️  No tool calls made (model might not support it)")
        
        print(f"Response: {response.content[:100]}...")
        
    except Exception as e:
        print(f"Tool calling error: {e}")
    
    print("\n✅ LLM Client test completed!")


if __name__ == "__main__":
    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_API_BASE")
    
    if not api_key and not base_url:
        print("⚠️  No OpenAI API key or base URL found.")
        print("\nTo test with OpenAI API:")
        print("   export OPENAI_API_KEY='your-api-key-here'")
        print("\nTo test with local models:")
        print("   export OPENAI_API_BASE='http://localhost:1234/v1'")
        print("   export OPENAI_API_KEY='not-needed'")
        print("\nRunning test anyway to show configuration...")
    
    asyncio.run(test_llm_client())