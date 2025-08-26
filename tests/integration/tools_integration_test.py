#!/usr/bin/env python3
"""
Test script for RAGline LLM tools.
Run this to validate tool implementations and schemas.
"""

import asyncio
import json
import sys
from typing import Dict, Any

# Add services to path
sys.path.insert(0, 'services/llm')

try:
    from tools.manager import ToolManager
    from tools.base import BaseTool
    from tools import TOOLS
    TOOLS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import tools: {e}")
    TOOLS_AVAILABLE = False


async def test_tools():
    """Test all available tools."""
    
    if not TOOLS_AVAILABLE:
        print("❌ Tools not available - skipping tests")
        return
    
    print("🧪 Testing RAGline LLM Tools")
    print("=" * 50)
    
    # Initialize tool manager
    manager = ToolManager(tenant_id="test_tenant", user_id="test_user")
    
    print(f"\n1. Tool Registration")
    print(f"   Available tools: {manager.get_available_tools()}")
    print(f"   Total count: {len(manager.tools)}")
    
    # Test OpenAI function schemas
    print(f"\n2. OpenAI Function Schemas")
    functions = manager.get_openai_functions()
    for func in functions:
        name = func["function"]["name"]
        print(f"   ✅ {name}: {func['function']['description']}")
    
    # Test retrieve_menu tool
    print(f"\n3. Testing retrieve_menu tool")
    try:
        result = await manager.execute_tool("retrieve_menu", {
            "query": "pizza", 
            "category": "mains",
            "limit": 3
        })
        
        if result.success:
            data = result.data
            print(f"   ✅ Success: Found {data['returned']} items")
            print(f"   📊 Query: {data['filters_applied']['query']}")
            print(f"   🍕 First item: {data['items'][0]['name'] if data['items'] else 'None'}")
        else:
            print(f"   ❌ Failed: {result.error}")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test apply_promos tool
    print(f"\n4. Testing apply_promos tool")
    try:
        result = await manager.execute_tool("apply_promos", {
            "promo_code": "SAVE20",
            "order_total": 30.00
        })
        
        if result.success:
            data = result.data
            print(f"   ✅ Success: Applied {data['promo_applied']['code']}")
            print(f"   💰 Discount: ${data['order_summary']['discount_amount']}")
            print(f"   🎯 Final total: ${data['order_summary']['final_total']}")
        else:
            print(f"   ❌ Failed: {result.error}")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test confirm tool
    print(f"\n5. Testing confirm tool")
    try:
        result = await manager.execute_tool("confirm", {
            "action": "place_order",
            "details": {
                "items": [
                    {"name": "Margherita Pizza", "quantity": 1, "price": 16.99},
                    {"name": "Caesar Salad", "quantity": 1, "price": 12.99}
                ],
                "total": 29.98,
                "delivery_address": "123 Main St"
            }
        })
        
        if result.success:
            data = result.data
            print(f"   ✅ Success: {data['action']} confirmation")
            print(f"   📝 Message: {data['message']}")
            print(f"   🎯 Total: ${data['order_summary']['total']}")
        else:
            print(f"   ❌ Failed: {result.error}")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test error handling
    print(f"\n6. Testing Error Handling")
    
    # Test invalid tool
    result = await manager.execute_tool("invalid_tool", {})
    print(f"   Invalid tool: {'✅' if not result.success else '❌'} {result.error}")
    
    # Test invalid promo code
    result = await manager.execute_tool("apply_promos", {
        "promo_code": "INVALID123", 
        "order_total": 20.00
    })
    print(f"   Invalid promo: {'✅' if not result.success else '❌'} {result.error}")
    
    # Test invalid arguments
    result = await manager.execute_tool("retrieve_menu", {
        "limit": 100  # Over maximum
    })
    print(f"   Invalid args: {'✅' if not result.success else '❌'} {result.error}")
    
    # Test tool schemas
    print(f"\n7. Schema Validation")
    schema = manager.get_tools_schema()
    for tool_name, tool_info in schema["tools"].items():
        if "error" not in tool_info:
            print(f"   ✅ {tool_name}: Schema valid")
        else:
            print(f"   ❌ {tool_name}: {tool_info['error']}")
    
    # Test OpenAI tool call format
    print(f"\n8. Testing OpenAI Tool Call Format")
    mock_tool_calls = [
        {
            "id": "call_123",
            "function": {
                "name": "retrieve_menu",
                "arguments": json.dumps({"query": "chicken", "limit": 2})
            }
        }
    ]
    
    try:
        results = await manager.execute_tool_calls(mock_tool_calls)
        if results:
            result = json.loads(results[0]["content"])
            print(f"   ✅ OpenAI format: {result['success']}")
            if result["success"]:
                items_found = result["data"]["returned"]
                print(f"   📊 Items found: {items_found}")
            else:
                print(f"   ⚠️  Tool call succeeded but query had no results: {result.get('error', 'Unknown error')}")
        else:
            print(f"   ❌ No results returned")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print(f"\n✅ Tool testing completed!")


if __name__ == "__main__":
    if not TOOLS_AVAILABLE:
        print("⚠️  Tools not available. Make sure you're running from the correct directory.")
        sys.exit(1)
    
    asyncio.run(test_tools())