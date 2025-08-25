"""
Retrieve Menu Tool

Tool for retrieving menu items based on search queries and filters.
Supports category filtering and dietary restrictions.
"""

from typing import Any, Dict, List, Optional
from .base import BaseTool, ToolError


class RetrieveMenuTool(BaseTool):
    """Tool for retrieving menu items with search and filtering capabilities."""
    
    @property
    def name(self) -> str:
        return "retrieve_menu"
    
    @property  
    def description(self) -> str:
        return "Retrieve menu items based on search query, category, and dietary restrictions"
    
    def get_schema(self) -> Dict[str, Any]:
        """Return OpenAI function schema."""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for menu items (e.g., 'pizza', 'spicy', 'chicken')"
                },
                "category": {
                    "type": "string", 
                    "enum": ["appetizers", "mains", "desserts", "beverages", "sides"],
                    "description": "Menu category to filter by"
                },
                "dietary_restrictions": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["vegetarian", "vegan", "gluten-free", "dairy-free", "keto", "low-carb"]
                    },
                    "description": "Dietary restrictions to filter by"
                },
                "max_price": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Maximum price filter"
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Maximum number of items to return"
                }
            }
        }
    
    def validate_args(self, **kwargs) -> Dict[str, Any]:
        """Validate retrieve menu arguments."""
        # Set defaults
        args = {
            "limit": kwargs.get("limit", 10),
            **kwargs
        }
        
        # Validate limit
        if args["limit"] < 1 or args["limit"] > 50:
            raise ToolError("Limit must be between 1 and 50")
        
        # Validate max_price
        if "max_price" in args and args["max_price"] < 0:
            raise ToolError("Max price must be non-negative")
        
        return args
    
    async def execute(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Execute menu retrieval.
        
        Args:
            query: Search query string
            category: Category filter  
            dietary_restrictions: List of dietary restrictions
            max_price: Maximum price filter
            limit: Number of items to return
            
        Returns:
            List of menu items matching criteria
        """
        query = kwargs.get("query", "")
        category = kwargs.get("category")
        dietary_restrictions = kwargs.get("dietary_restrictions", [])
        max_price = kwargs.get("max_price")
        limit = kwargs.get("limit", 10)
        
        # Mock menu data - in production this would query a database
        mock_menu = [
            {
                "id": "item_1",
                "name": "Margherita Pizza",
                "category": "mains",
                "price": 16.99,
                "description": "Fresh mozzarella, tomatoes, and basil on thin crust",
                "dietary_info": ["vegetarian"],
                "available": True
            },
            {
                "id": "item_2", 
                "name": "Grilled Chicken Caesar Salad",
                "category": "mains",
                "price": 14.99,
                "description": "Romaine lettuce, grilled chicken, parmesan, croutons",
                "dietary_info": ["gluten-free"],
                "available": True
            },
            {
                "id": "item_3",
                "name": "Vegan Buddha Bowl",
                "category": "mains", 
                "price": 13.99,
                "description": "Quinoa, roasted vegetables, tahini dressing",
                "dietary_info": ["vegan", "vegetarian", "gluten-free"],
                "available": True
            },
            {
                "id": "item_4",
                "name": "Chocolate Lava Cake",
                "category": "desserts",
                "price": 8.99,
                "description": "Warm chocolate cake with molten center, vanilla ice cream",
                "dietary_info": ["vegetarian"],
                "available": True
            },
            {
                "id": "item_5",
                "name": "Garlic Bread",
                "category": "appetizers",
                "price": 6.99,
                "description": "Crispy bread with garlic butter and herbs",
                "dietary_info": ["vegetarian"],
                "available": True
            },
            {
                "id": "item_6",
                "name": "Spicy Buffalo Wings",
                "category": "appetizers",
                "price": 12.99,
                "description": "Traditional buffalo wings with celery and blue cheese",
                "dietary_info": [],
                "available": True
            }
        ]
        
        # Apply filters
        filtered_items = []
        
        for item in mock_menu:
            # Skip unavailable items
            if not item["available"]:
                continue
            
            # Category filter
            if category and item["category"] != category:
                continue
                
            # Price filter
            if max_price and item["price"] > max_price:
                continue
            
            # Dietary restrictions filter
            if dietary_restrictions:
                if not any(restriction in item["dietary_info"] for restriction in dietary_restrictions):
                    continue
            
            # Query filter (search in name and description)
            if query:
                query_lower = query.lower()
                if (query_lower not in item["name"].lower() and 
                    query_lower not in item["description"].lower()):
                    continue
            
            filtered_items.append(item)
        
        # Apply limit
        limited_items = filtered_items[:limit]
        
        # Add search metadata
        result = {
            "items": limited_items,
            "total_found": len(filtered_items),
            "returned": len(limited_items),
            "filters_applied": {
                "query": query or None,
                "category": category,
                "dietary_restrictions": dietary_restrictions,
                "max_price": max_price
            }
        }
        
        if not limited_items:
            raise ToolError("No menu items found matching the specified criteria")
        
        return result