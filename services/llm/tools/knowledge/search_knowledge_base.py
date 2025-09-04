"""
Advanced Knowledge Base Search Tool

Implements sophisticated semantic search across multiple document types:
- Multi-document search across policies, FAQs, menu items, and context
- Advanced embedding-based retrieval with reranking
- Context aggregation and relevance scoring
- Query expansion and semantic understanding
- Business logic integration
"""

import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

# Add path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from ..base import BaseTool, ToolError

logger = logging.getLogger(__name__)

# Import RAG components
try:
    from packages.rag.embeddings import Document, EmbeddingConfig, create_embedding_manager
    from packages.rag.ingestion import SAMPLE_FAQ_ITEMS, SAMPLE_MENU_ITEMS, SAMPLE_POLICY_DOCUMENTS
    from packages.rag.retrieval import RetrievalContext, retrieve_menu_items

    RAG_AVAILABLE = True
except ImportError as e:
    logger.warning(f"RAG components not available: {e}")
    RAG_AVAILABLE = False

# Query expansion keywords
QUERY_EXPANSION_MAP = {
    "food": ["menu", "items", "dishes", "cuisine", "meals"],
    "dietary": ["vegan", "vegetarian", "gluten-free", "allergies", "restrictions"],
    "pricing": ["cost", "price", "discount", "promotion", "deals"],
    "delivery": ["shipping", "transport", "pickup", "time", "schedule"],
    "policy": ["rules", "terms", "conditions", "guidelines", "procedures"],
    "help": ["support", "assistance", "faq", "questions", "how-to"],
}

DOCUMENT_TYPE_WEIGHTS = {"menu_item": 1.0, "policy": 0.8, "faq": 0.9, "context": 0.7}


class SearchKnowledgeBaseTool(BaseTool):
    """
    Advanced knowledge base search tool with multi-document semantic search.

    Features:
    - Cross-document type search (menu, policies, FAQs)
    - Semantic similarity with embedding-based retrieval
    - Query expansion and context understanding
    - Business logic-aware relevance scoring
    - Result aggregation and deduplication
    """

    @property
    def name(self) -> str:
        return "search_knowledge_base"

    @property
    def description(self) -> str:
        return "Search across all knowledge base documents with advanced semantic understanding"

    def get_schema(self) -> Dict[str, Any]:
        """Return OpenAI function schema for knowledge base search."""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for knowledge base (natural language supported)",
                    "minLength": 1,
                },
                "document_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["menu_item", "policy", "faq", "all"]},
                    "description": "Document types to search (default: all)",
                    "default": ["all"],
                },
                "categories": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "appetizers",
                            "mains",
                            "desserts",
                            "beverages",
                            "sides",
                            "dietary",
                            "delivery",
                            "support",
                            "general",
                        ],
                    },
                    "description": "Categories to filter by",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Maximum number of results to return",
                },
                "similarity_threshold": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.3,
                    "description": "Minimum similarity threshold (0.0-1.0)",
                },
                "include_context": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include context aggregation",
                },
                "expand_query": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to expand query with related terms",
                },
                "rerank_results": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to apply business logic reranking",
                },
            },
            "required": ["query"],
        }

    def validate_args(self, **kwargs) -> Dict[str, Any]:
        """Validate knowledge base search arguments."""
        args = {"limit": 10, "similarity_threshold": 0.3, **kwargs}

        # Validate required query
        if not args.get("query", "").strip():
            raise ToolError("Query is required and cannot be empty")

        # Validate limit
        if args["limit"] < 1 or args["limit"] > 50:
            raise ToolError("Limit must be between 1 and 50")

        # Validate similarity threshold
        if args["similarity_threshold"] < 0.0 or args["similarity_threshold"] > 1.0:
            raise ToolError("Similarity threshold must be between 0.0 and 1.0")

        # Set defaults for optional parameters
        args.setdefault("document_types", ["all"])
        args.setdefault("categories", [])
        args.setdefault("include_context", True)
        args.setdefault("expand_query", True)
        args.setdefault("rerank_results", True)

        return args

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute advanced knowledge base search.

        Args:
            query: Natural language search query
            document_types: Types of documents to search
            categories: Categories to filter by
            limit: Maximum results
            similarity_threshold: Minimum similarity score
            include_context: Whether to aggregate context
            expand_query: Whether to expand query terms
            rerank_results: Whether to apply business reranking

        Returns:
            Comprehensive search results with semantic analysis
        """
        query = kwargs.get("query", "").strip()
        document_types = kwargs.get("document_types", ["all"])
        categories = kwargs.get("categories", [])
        limit = kwargs.get("limit", 10)
        similarity_threshold = kwargs.get("similarity_threshold", 0.3)
        include_context = kwargs.get("include_context", True)
        expand_query = kwargs.get("expand_query", True)
        rerank_results = kwargs.get("rerank_results", True)

        start_time = time.time()

        try:
            # Step 1: Query expansion
            if expand_query:
                expanded_query = self._expand_query(query)
                logger.debug(f"Query expanded: '{query}' -> '{expanded_query}'")
            else:
                expanded_query = query

            # Step 2: Multi-document search
            search_results = await self._multi_document_search(
                query=expanded_query,
                document_types=document_types,
                categories=categories,
                limit=limit * 3,  # Get more results for reranking
                similarity_threshold=similarity_threshold,
            )

            # Step 3: Business logic reranking
            if rerank_results:
                search_results = self._apply_business_reranking(search_results, query)

            # Step 4: Context aggregation
            aggregated_results = search_results[:limit]
            context_summary = None

            if include_context and aggregated_results:
                context_summary = self._aggregate_context(aggregated_results, query)

            # Step 5: Format enhanced results
            formatted_results = self._format_results(aggregated_results, context_summary)

            execution_time = (time.time() - start_time) * 1000

            # Build comprehensive response
            result = {
                "search_method": "advanced_knowledge_search",
                "query_processed": expanded_query,
                "query_original": query,
                "results": formatted_results,
                "total_found": len(search_results),
                "returned": len(aggregated_results),
                "context_summary": context_summary,
                "search_metadata": {
                    "document_types_searched": document_types,
                    "categories_filtered": categories,
                    "similarity_threshold": similarity_threshold,
                    "query_expanded": expand_query,
                    "results_reranked": rerank_results,
                    "context_included": include_context,
                    "execution_time_ms": round(execution_time, 2),
                },
                "relevance_analysis": {
                    "avg_similarity": sum(r.get("similarity_score", 0) for r in formatted_results)
                    / max(len(formatted_results), 1),
                    "document_type_distribution": self._analyze_document_distribution(formatted_results),
                    "category_distribution": self._analyze_category_distribution(formatted_results),
                },
            }

            if not aggregated_results:
                raise ToolError(f"No knowledge base documents found matching '{query}' with specified filters")

            return result

        except Exception as e:
            logger.error(f"Knowledge base search failed: {e}")
            # Fallback to basic search
            return await self._fallback_search(query, limit)

    def _expand_query(self, query: str) -> str:
        """Expand query with related terms for better semantic matching."""
        query_lower = query.lower()
        expanded_terms = set([query])

        # Add expansion terms based on query content
        for category, expansions in QUERY_EXPANSION_MAP.items():
            if category in query_lower or any(term in query_lower for term in expansions):
                expanded_terms.update(expansions[:3])  # Add top 3 related terms

        # Add semantic variations
        if "what" in query_lower or "how" in query_lower:
            expanded_terms.update(["help", "information", "guide"])

        if "where" in query_lower or "when" in query_lower:
            expanded_terms.update(["location", "time", "schedule"])

        return " ".join(expanded_terms)

    async def _multi_document_search(
        self, query: str, document_types: List[str], categories: List[str], limit: int, similarity_threshold: float
    ) -> List[Dict[str, Any]]:
        """
        Perform multi-document semantic search across different document types.
        """
        all_results = []

        # Determine which document types to search
        search_types = document_types if "all" not in document_types else ["menu_item", "policy", "faq"]

        for doc_type in search_types:
            try:
                type_results = await self._search_document_type(
                    query=query,
                    doc_type=doc_type,
                    categories=categories,
                    limit=limit // len(search_types) + 5,  # Distribute limit across types
                    similarity_threshold=similarity_threshold,
                )

                # Add document type weight
                for result in type_results:
                    result["type_weight"] = DOCUMENT_TYPE_WEIGHTS.get(doc_type, 0.5)
                    result["document_type"] = doc_type

                all_results.extend(type_results)

            except Exception as e:
                logger.warning(f"Search failed for document type {doc_type}: {e}")

        # Sort by weighted similarity score
        all_results.sort(key=lambda x: x.get("similarity_score", 0) * x.get("type_weight", 0.5), reverse=True)

        return all_results[:limit]

    async def _search_document_type(
        self, query: str, doc_type: str, categories: List[str], limit: int, similarity_threshold: float
    ) -> List[Dict[str, Any]]:
        """Search specific document type with semantic similarity."""

        if not RAG_AVAILABLE:
            return self._search_sample_data(query, doc_type, categories, limit)

        try:
            # Initialize embedding manager for search
            database_url = os.getenv("DATABASE_URL", "postgresql://ragline_user:secure_password@localhost:5433/ragline")
            api_key = os.getenv("OPENAI_API_KEY")

            if not api_key:
                return self._search_sample_data(query, doc_type, categories, limit)

            # Create embedding manager
            embedding_manager = await create_embedding_manager(
                provider="openai", api_key=api_key, database_url=database_url
            )

            # Generate query embedding using the manager's generate_embedding method
            query_embedding = await embedding_manager.generate_embedding(query)

            # Search with metadata filters
            filters = {"document_type": doc_type}
            if categories:
                # For menu items, use category directly; for others, search in content
                if doc_type == "menu_item" and any(
                    cat in ["appetizers", "mains", "desserts", "beverages", "sides"] for cat in categories
                ):
                    menu_categories = [
                        cat for cat in categories if cat in ["appetizers", "mains", "desserts", "beverages", "sides"]
                    ]
                    if menu_categories:
                        filters["category"] = menu_categories[0]

            # Perform similarity search
            similarity_results = await embedding_manager.vector_store.similarity_search(
                query_embedding=query_embedding, limit=limit, threshold=similarity_threshold, filters=filters
            )

            await embedding_manager.close()

            # Convert to standardized format
            results = []
            for sim_result in similarity_results:
                doc = sim_result.document
                result = {
                    "id": doc.id,
                    "content": doc.content,
                    "metadata": doc.metadata,
                    "similarity_score": sim_result.score,
                    "distance": sim_result.distance,
                    "document_type": doc_type,
                    "retrieval_method": "vector_similarity",
                }
                results.append(result)

            return results

        except Exception as e:
            logger.warning(f"Vector search failed for {doc_type}, falling back to sample data: {e}")
            return self._search_sample_data(query, doc_type, categories, limit)

    def _search_sample_data(self, query: str, doc_type: str, categories: List[str], limit: int) -> List[Dict[str, Any]]:
        """Fallback search using sample data with text matching."""

        query_lower = query.lower()
        results = []

        # Select appropriate sample data
        if doc_type == "menu_item":
            sample_data = (
                SAMPLE_MENU_ITEMS
                if RAG_AVAILABLE
                else [
                    {
                        "id": "item_1",
                        "name": "Margherita Pizza",
                        "description": "Classic pizza with fresh mozzarella, tomatoes, and basil",
                        "category": "mains",
                        "price": 16.99,
                        "dietary_info": ["vegetarian"],
                        "available": True,
                    }
                ]
            )
        elif doc_type == "policy":
            sample_data = (
                SAMPLE_POLICY_DOCUMENTS
                if RAG_AVAILABLE
                else [
                    {
                        "id": "policy_1",
                        "title": "Delivery Policy",
                        "content": "We deliver within 30-45 minutes during regular hours",
                        "category": "delivery",
                    }
                ]
            )
        elif doc_type == "faq":
            sample_data = (
                SAMPLE_FAQ_ITEMS
                if RAG_AVAILABLE
                else [
                    {
                        "id": "faq_1",
                        "question": "Do you offer vegan options?",
                        "answer": "Yes! We have several vegan options including our popular Vegan Buddha Bowl",
                        "category": "dietary",
                    }
                ]
            )
        else:
            return []

        # Search through sample data
        for item in sample_data:
            # Calculate simple text similarity score
            searchable_text = ""

            if doc_type == "menu_item":
                searchable_text = (
                    f"{item.get('name', '')} {item.get('description', '')} {' '.join(item.get('dietary_info', []))}"
                )
                item_category = item.get("category", "")
            elif doc_type == "policy":
                searchable_text = f"{item.get('title', '')} {item.get('content', '')}"
                item_category = item.get("category", "")
            elif doc_type == "faq":
                searchable_text = f"{item.get('question', '')} {item.get('answer', '')}"
                item_category = item.get("category", "")

            searchable_text = searchable_text.lower()

            # Apply category filter
            if categories and item_category and item_category not in categories:
                continue

            # Calculate text similarity (simple approach)
            query_terms = set(query_lower.split())
            text_terms = set(searchable_text.split())

            if query_terms & text_terms:  # If any terms match
                similarity_score = len(query_terms & text_terms) / len(query_terms | text_terms)

                result = {
                    "id": item.get("id", f"{doc_type}_{len(results)}"),
                    "content": searchable_text[:200] + "..." if len(searchable_text) > 200 else searchable_text,
                    "metadata": item,
                    "similarity_score": min(similarity_score + 0.3, 0.95),  # Boost for fallback
                    "distance": 1.0 - similarity_score,
                    "document_type": doc_type,
                    "retrieval_method": "text_similarity",
                }
                results.append(result)

        # Sort by similarity score and limit
        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results[:limit]

    def _apply_business_reranking(self, results: List[Dict[str, Any]], original_query: str) -> List[Dict[str, Any]]:
        """Apply business logic-based reranking to search results."""

        query_lower = original_query.lower()

        for result in results:
            base_score = result.get("similarity_score", 0)
            doc_type = result.get("document_type", "")
            metadata = result.get("metadata", {})

            # Business rule adjustments
            boost_factor = 1.0

            # Boost available items
            if doc_type == "menu_item" and metadata.get("available", True):
                boost_factor += 0.1

            # Boost high-rated items
            if doc_type == "menu_item" and metadata.get("rating", 0) > 4.5:
                boost_factor += 0.05

            # Boost popular items
            if doc_type == "menu_item" and metadata.get("order_count", 0) > 100:
                boost_factor += 0.05

            # Boost FAQ items for question-like queries
            if doc_type == "faq" and any(word in query_lower for word in ["what", "how", "why", "when", "where", "?"]):
                boost_factor += 0.15

            # Boost policy documents for policy-related queries
            if doc_type == "policy" and any(
                word in query_lower for word in ["policy", "rule", "delivery", "hours", "payment"]
            ):
                boost_factor += 0.1

            # Apply business hours context
            current_hour = time.localtime().tm_hour
            if doc_type == "menu_item" and 11 <= current_hour <= 22:  # Restaurant hours
                boost_factor += 0.02

            # Update similarity score with business logic
            result["business_boosted_score"] = min(base_score * boost_factor, 0.99)
            result["boost_factor"] = boost_factor
            result["reranking_applied"] = True

        # Re-sort by business-boosted score
        results.sort(key=lambda x: x.get("business_boosted_score", x.get("similarity_score", 0)), reverse=True)

        return results

    def _aggregate_context(self, results: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        """Aggregate context from search results for comprehensive understanding."""

        if not results:
            return {"summary": "No context available", "confidence": 0.0}

        # Analyze result patterns
        doc_types = {}
        categories = {}
        content_themes = set()

        for result in results:
            doc_type = result.get("document_type", "unknown")
            metadata = result.get("metadata", {})

            # Count document types
            doc_types[doc_type] = doc_types.get(doc_type, 0) + 1

            # Count categories
            category = metadata.get("category", "general")
            categories[category] = categories.get(category, 0) + 1

            # Extract content themes (simple keyword extraction)
            content = result.get("content", "").lower()
            for word in content.split():
                if len(word) > 4 and word.isalpha():
                    content_themes.add(word)

        # Generate context summary
        primary_doc_type = max(doc_types.items(), key=lambda x: x[1])[0] if doc_types else "unknown"
        primary_category = max(categories.items(), key=lambda x: x[1])[0] if categories else "general"

        # Calculate confidence based on result quality
        avg_similarity = sum(r.get("similarity_score", 0) for r in results) / len(results)
        result_diversity = len(set(r.get("document_type") for r in results))
        confidence = min((avg_similarity * 0.7 + result_diversity * 0.3), 0.95)

        context_summary = {
            "summary": f"Found {len(results)} relevant documents primarily about {primary_category} from {primary_doc_type} sources",
            "primary_document_type": primary_doc_type,
            "primary_category": primary_category,
            "confidence": round(confidence, 3),
            "content_themes": list(content_themes)[:10],  # Top 10 themes
            "document_distribution": doc_types,
            "category_distribution": categories,
            "recommendation": self._generate_recommendation(query, primary_doc_type, primary_category, avg_similarity),
        }

        return context_summary

    def _generate_recommendation(
        self, query: str, primary_doc_type: str, primary_category: str, avg_similarity: float
    ) -> str:
        """Generate actionable recommendation based on search results."""

        if avg_similarity > 0.8:
            confidence_level = "high confidence"
        elif avg_similarity > 0.6:
            confidence_level = "moderate confidence"
        else:
            confidence_level = "low confidence"

        if primary_doc_type == "menu_item":
            if primary_category in ["mains", "appetizers", "desserts"]:
                return f"Based on your query about '{query}', I found relevant menu items in {primary_category} with {confidence_level}. Consider browsing similar items or asking about specific dietary requirements."
            else:
                return f"Found menu items related to '{query}' with {confidence_level}. You might want to ask about availability or pricing."

        elif primary_doc_type == "faq":
            return f"Your question about '{query}' matches our FAQ items with {confidence_level}. The information should help answer your query."

        elif primary_doc_type == "policy":
            return f"Found policy information related to '{query}' with {confidence_level}. This covers our official guidelines and procedures."

        else:
            return f"Found diverse information about '{query}' across multiple document types with {confidence_level}."

    def _format_results(
        self, results: List[Dict[str, Any]], context_summary: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Format search results with enhanced metadata."""

        formatted = []

        for i, result in enumerate(results):
            metadata = result.get("metadata", {})
            doc_type = result.get("document_type", "unknown")

            # Create standardized result format
            formatted_result = {
                "id": result.get("id"),
                "rank": i + 1,
                "title": self._extract_title(metadata, doc_type),
                "content": result.get("content", ""),
                "document_type": doc_type,
                "category": metadata.get("category", "general"),
                "similarity_score": result.get("similarity_score", 0),
                "business_score": result.get("business_boosted_score", result.get("similarity_score", 0)),
                "boost_factor": result.get("boost_factor", 1.0),
                "retrieval_method": result.get("retrieval_method", "unknown"),
                "metadata": self._filter_metadata(metadata, doc_type),
                "relevance_explanation": self._explain_relevance(result, context_summary),
            }

            formatted.append(formatted_result)

        return formatted

    def _extract_title(self, metadata: Dict[str, Any], doc_type: str) -> str:
        """Extract appropriate title based on document type."""
        if doc_type == "menu_item":
            return metadata.get("name", "Unknown Item")
        elif doc_type == "policy":
            return metadata.get("title", "Policy Document")
        elif doc_type == "faq":
            return metadata.get("question", "FAQ Item")
        else:
            return metadata.get("title", metadata.get("name", "Document"))

    def _filter_metadata(self, metadata: Dict[str, Any], doc_type: str) -> Dict[str, Any]:
        """Filter metadata to include only relevant fields for each document type."""

        if doc_type == "menu_item":
            return {
                "price": metadata.get("price"),
                "dietary_info": metadata.get("dietary_info", []),
                "rating": metadata.get("rating"),
                "available": metadata.get("available", True),
            }
        elif doc_type == "policy":
            return {"type": metadata.get("type"), "last_updated": metadata.get("last_updated")}
        elif doc_type == "faq":
            return {"answer": metadata.get("answer"), "helpful_count": metadata.get("helpful_count", 0)}
        else:
            return {k: v for k, v in metadata.items() if k not in ["embedding", "raw_data"]}

    def _explain_relevance(self, result: Dict[str, Any], context_summary: Optional[Dict[str, Any]]) -> str:
        """Generate explanation for why this result is relevant."""

        similarity = result.get("similarity_score", 0)
        doc_type = result.get("document_type", "")
        boost_factor = result.get("boost_factor", 1.0)

        explanation_parts = []

        # Similarity explanation
        if similarity > 0.8:
            explanation_parts.append("High semantic similarity to your query")
        elif similarity > 0.6:
            explanation_parts.append("Good semantic match")
        else:
            explanation_parts.append("Partial semantic match")

        # Business boost explanation
        if boost_factor > 1.05:
            explanation_parts.append("boosted for business relevance")

        # Document type context
        if doc_type == "menu_item" and result.get("metadata", {}).get("available", True):
            explanation_parts.append("currently available")

        if doc_type == "faq":
            explanation_parts.append("from frequently asked questions")

        if doc_type == "policy":
            explanation_parts.append("from official policies")

        return ", ".join(explanation_parts).capitalize()

    def _analyze_document_distribution(self, results: List[Dict[str, Any]]) -> Dict[str, int]:
        """Analyze distribution of document types in results."""
        distribution = {}
        for result in results:
            doc_type = result.get("document_type", "unknown")
            distribution[doc_type] = distribution.get(doc_type, 0) + 1
        return distribution

    def _analyze_category_distribution(self, results: List[Dict[str, Any]]) -> Dict[str, int]:
        """Analyze distribution of categories in results."""
        distribution = {}
        for result in results:
            category = result.get("category", "general")
            distribution[category] = distribution.get(category, 0) + 1
        return distribution

    async def _fallback_search(self, query: str, limit: int) -> Dict[str, Any]:
        """Minimal fallback when all advanced search methods fail."""

        return {
            "search_method": "fallback_search",
            "query_processed": query,
            "query_original": query,
            "results": [
                {
                    "id": "fallback_1",
                    "rank": 1,
                    "title": "Knowledge Base Search",
                    "content": f"Search for '{query}' - knowledge base temporarily unavailable",
                    "document_type": "system",
                    "category": "general",
                    "similarity_score": 0.3,
                    "business_score": 0.3,
                    "retrieval_method": "fallback",
                    "metadata": {"system_message": True},
                    "relevance_explanation": "Fallback result when knowledge base unavailable",
                }
            ],
            "total_found": 1,
            "returned": 1,
            "context_summary": {
                "summary": "Knowledge base search temporarily unavailable",
                "confidence": 0.1,
                "recommendation": "Please try again later or contact support for assistance",
            },
            "search_metadata": {
                "document_types_searched": ["all"],
                "categories_filtered": [],
                "similarity_threshold": 0.3,
                "query_expanded": False,
                "results_reranked": False,
                "context_included": True,
                "execution_time_ms": 1.0,
                "fallback_reason": "Advanced search components unavailable",
            },
        }
