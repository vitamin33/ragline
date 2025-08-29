"""
Retrieve Menu Tool

Tool for retrieving menu items using RAG search with vector similarity.
Supports category filtering, dietary restrictions, and intelligent ranking.
"""

import os
import sys
from typing import Any, Dict, List

# Add path for RAG imports
sys.path.insert(0, "../../../packages")

from .base import BaseTool, ToolError

# Import RAG components
try:
    from rag import (
        SAMPLE_MENU_ITEMS,
        RetrievalContext,
        create_embedding_manager,
        retrieve_menu_items,
    )

    RAG_AVAILABLE = True
except ImportError as e:
    print(f"Warning: RAG not available for retrieve_menu tool: {e}")
    RAG_AVAILABLE = False


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
                    "description": "Search query for menu items (e.g., 'pizza', 'spicy', 'chicken')",
                },
                "category": {
                    "type": "string",
                    "enum": ["appetizers", "mains", "desserts", "beverages", "sides"],
                    "description": "Menu category to filter by",
                },
                "dietary_restrictions": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "vegetarian",
                            "vegan",
                            "gluten-free",
                            "dairy-free",
                            "keto",
                            "low-carb",
                        ],
                    },
                    "description": "Dietary restrictions to filter by",
                },
                "max_price": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Maximum price filter",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Maximum number of items to return",
                },
            },
        }

    def validate_args(self, **kwargs) -> Dict[str, Any]:
        """Validate retrieve menu arguments."""
        # Set defaults
        args = {"limit": kwargs.get("limit", 10), **kwargs}

        # Validate limit
        if args["limit"] < 1 or args["limit"] > 50:
            raise ToolError("Limit must be between 1 and 50")

        # Validate max_price
        if "max_price" in args and args["max_price"] < 0:
            raise ToolError("Max price must be non-negative")

        return args

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute menu retrieval using RAG search.

        Args:
            query: Search query string
            category: Category filter
            dietary_restrictions: List of dietary restrictions
            max_price: Maximum price filter
            limit: Number of items to return

        Returns:
            Enhanced menu search results with RAG context and relevance scoring
        """
        query = kwargs.get("query", "")
        category = kwargs.get("category")
        dietary_restrictions = kwargs.get("dietary_restrictions", [])
        max_price = kwargs.get("max_price")
        limit = kwargs.get("limit", 10)

        # If RAG not available, fall back to mock data
        if not RAG_AVAILABLE:
            return await self._fallback_mock_search(kwargs)

        try:
            # Create embedding manager
            database_url = os.getenv("DATABASE_URL")
            api_key = os.getenv("OPENAI_API_KEY")

            if not api_key:
                # Use sample data search if no API key
                return await self._sample_data_search(kwargs)

            if not database_url:
                # Use sample data search if no database
                return await self._sample_data_search(kwargs)

            # Initialize RAG system
            embedding_manager = await create_embedding_manager(
                provider="openai", api_key=api_key, database_url=database_url
            )

            # Create user context for personalized search
            user_preferences = {}
            if dietary_restrictions:
                user_preferences["dietary_restrictions"] = dietary_restrictions
            if category:
                user_preferences["favorite_category"] = category

            # Build search query
            search_query = self._build_search_query(query, category, dietary_restrictions)

            # Perform RAG search
            retrieved_docs = await retrieve_menu_items(
                embedding_manager=embedding_manager,
                query=search_query,
                user_preferences=user_preferences,
                max_results=limit * 2,  # Get more for filtering
            )

            # Apply additional filters
            filtered_results = []
            for retrieved_doc in retrieved_docs:
                item_metadata = retrieved_doc.document.metadata

                # Price filter
                if max_price and item_metadata.get("price", 0) > max_price:
                    continue

                # Category filter (if not already in query)
                if category and item_metadata.get("category") != category:
                    continue

                # Availability filter
                if not item_metadata.get("available", True):
                    continue

                filtered_results.append(retrieved_doc)

            # Limit results
            final_results = filtered_results[:limit]

            # Format results with RAG context
            items = []
            rag_context = []

            for retrieved_doc in final_results:
                metadata = retrieved_doc.document.metadata

                # Format item data
                item = {
                    "id": metadata.get("id", "unknown"),
                    "name": metadata.get("name", "Unknown Item"),
                    "category": metadata.get("category", "unknown"),
                    "price": metadata.get("price", 0.0),
                    "description": metadata.get("description", ""),
                    "dietary_info": metadata.get("dietary_info", []),
                    "available": metadata.get("available", True),
                    "rating": metadata.get("rating"),
                    "rag_relevance": {
                        "similarity_score": retrieved_doc.similarity_score,
                        "relevance_score": retrieved_doc.relevance_score,
                        "rank": retrieved_doc.rank,
                        "retrieval_reason": retrieved_doc.retrieval_reason,
                    },
                }
                items.append(item)

                # Add to RAG context
                rag_context.append(
                    {
                        "content": retrieved_doc.document.content,
                        "relevance": retrieved_doc.similarity_score,
                        "reason": retrieved_doc.retrieval_reason,
                    }
                )

            await embedding_manager.close()

            # Enhanced result with RAG context
            result = {
                "search_method": "rag_vector_search",
                "items": items,
                "total_found": len(filtered_results),
                "returned": len(final_results),
                "rag_context": {
                    "query_processed": search_query,
                    "retrieved_documents": len(retrieved_docs),
                    "filtered_results": len(filtered_results),
                    "context_items": rag_context,
                },
                "filters_applied": {
                    "query": query or None,
                    "category": category,
                    "dietary_restrictions": dietary_restrictions,
                    "max_price": max_price,
                    "user_preferences": user_preferences,
                },
            }

            if not final_results:
                raise ToolError(f"No menu items found matching '{search_query}' with specified filters")

            return result

        except Exception as e:
            # Fall back to sample data search on error
            print(f"RAG search failed, falling back to sample data: {e}")
            return await self._sample_data_search(kwargs)

    def _build_search_query(self, query: str, category: str, dietary_restrictions: List[str]) -> str:
        """Build enhanced search query for RAG."""

        parts = []

        if query:
            parts.append(query)

        if category:
            parts.append(f"category: {category}")

        if dietary_restrictions:
            dietary_text = ", ".join(dietary_restrictions)
            parts.append(f"dietary options: {dietary_text}")

        return " ".join(parts) if parts else "menu items"

    async def _sample_data_search(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Search using sample data when RAG/database not available."""

        query = kwargs.get("query", "")
        category = kwargs.get("category")
        dietary_restrictions = kwargs.get("dietary_restrictions", [])
        max_price = kwargs.get("max_price")
        limit = kwargs.get("limit", 10)

        # Use sample data from ingestion module
        if RAG_AVAILABLE:
            from rag.ingestion import SAMPLE_MENU_ITEMS

            menu_items = SAMPLE_MENU_ITEMS
        else:
            # Inline fallback data
            menu_items = [
                {
                    "id": "item_1",
                    "name": "Margherita Pizza",
                    "category": "mains",
                    "price": 16.99,
                    "description": "Fresh mozzarella, tomatoes, and basil on thin crust",
                    "dietary_info": ["vegetarian"],
                    "available": True,
                    "rating": 4.5,
                },
                {
                    "id": "item_3",
                    "name": "Vegan Buddha Bowl",
                    "category": "mains",
                    "price": 13.99,
                    "description": "Quinoa, roasted vegetables, tahini dressing",
                    "dietary_info": ["vegan", "vegetarian", "gluten-free"],
                    "available": True,
                    "rating": 4.7,
                },
            ]

        # Apply filters
        filtered_items = []

        for item in menu_items:
            # Skip unavailable items
            if not item.get("available", True):
                continue

            # Category filter
            if category and item.get("category") != category:
                continue

            # Price filter
            if max_price and item.get("price", 0) > max_price:
                continue

            # Dietary restrictions filter
            if dietary_restrictions:
                item_dietary = item.get("dietary_info", [])
                if not any(restriction in item_dietary for restriction in dietary_restrictions):
                    continue

            # Query filter (simple text search)
            if query:
                query_lower = query.lower()
                name = item.get("name", "").lower()
                description = item.get("description", "").lower()
                if query_lower not in name and query_lower not in description:
                    continue

            # Add relevance score for consistency
            item_with_score = dict(item)
            item_with_score["rag_relevance"] = {
                "similarity_score": 0.8,  # Mock score
                "relevance_score": 0.8,
                "rank": len(filtered_items) + 1,
                "retrieval_reason": "sample data match",
            }

            filtered_items.append(item_with_score)

        # Apply limit
        limited_items = filtered_items[:limit]

        result = {
            "search_method": "sample_data_search",
            "items": limited_items,
            "total_found": len(filtered_items),
            "returned": len(limited_items),
            "rag_context": {
                "query_processed": query or "menu items",
                "note": "Using sample data - RAG search unavailable",
            },
            "filters_applied": {
                "query": query or None,
                "category": category,
                "dietary_restrictions": dietary_restrictions,
                "max_price": max_price,
            },
        }

        if not limited_items:
            raise ToolError("No menu items found matching the specified criteria")

        return result

    async def _fallback_mock_search(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Minimal fallback when RAG imports fail."""

        query = kwargs.get("query", "")
        limit = kwargs.get("limit", 3)

        # Minimal mock data
        mock_items = [
            {
                "id": "mock_1",
                "name": "Pizza (Mock)",
                "category": "mains",
                "price": 15.99,
                "description": "Mock pizza item",
                "dietary_info": ["vegetarian"],
                "available": True,
                "rag_relevance": {
                    "similarity_score": 0.5,
                    "relevance_score": 0.5,
                    "rank": 1,
                    "retrieval_reason": "fallback mock data",
                },
            }
        ]

        return {
            "search_method": "fallback_mock",
            "items": mock_items[:limit],
            "total_found": len(mock_items),
            "returned": min(len(mock_items), limit),
            "note": "RAG system unavailable - using fallback data",
        }
