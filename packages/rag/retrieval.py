"""
RAGline Retrieval Module

Implements Retrieval-Augmented Generation (RAG) system for contextual information retrieval.
Combines vector similarity search with business rule filtering and re-ranking.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .embeddings import Document, EmbeddingManager, SimilarityResult

logger = logging.getLogger(__name__)


class RetrievalConfig(BaseModel):
    """Configuration for RAG retrieval system."""

    # Search parameters
    max_results: int = Field(
        default=10, description="Maximum number of results to retrieve"
    )
    similarity_threshold: float = Field(
        default=0.5, description="Minimum similarity score"
    )

    # Re-ranking parameters
    enable_reranking: bool = Field(
        default=True, description="Enable business rule re-ranking"
    )
    boost_recent: bool = Field(
        default=True, description="Boost recently updated content"
    )
    boost_popular: bool = Field(default=True, description="Boost popular items")

    # Context parameters
    context_window_tokens: int = Field(
        default=2000, description="Maximum context tokens for LLM"
    )
    include_metadata: bool = Field(
        default=True, description="Include metadata in context"
    )

    # Filtering parameters
    respect_availability: bool = Field(
        default=True, description="Filter out unavailable items"
    )
    respect_business_hours: bool = Field(
        default=True, description="Consider business hours"
    )


@dataclass
class RetrievalContext:
    """Context for retrieval operations."""

    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    user_preferences: Optional[Dict[str, Any]] = None
    order_history: Optional[List[Dict[str, Any]]] = None
    current_time: Optional[datetime] = None


class RetrievedDocument(BaseModel):
    """Enhanced document with retrieval metadata."""

    document: Document
    relevance_score: float = Field(..., description="Combined relevance score")
    similarity_score: float = Field(..., description="Vector similarity score")
    business_score: float = Field(default=0.0, description="Business rule score boost")
    rank: int = Field(..., description="Final ranking position")
    retrieval_reason: str = Field(..., description="Why this document was retrieved")


class RAGRetriever:
    """Main RAG retrieval system."""

    def __init__(
        self,
        embedding_manager: EmbeddingManager,
        config: Optional[RetrievalConfig] = None,
    ):
        self.embedding_manager = embedding_manager
        self.config = config or RetrievalConfig()

    async def retrieve(
        self,
        query: str,
        context: Optional[RetrievalContext] = None,
        filters: Optional[Dict[str, Any]] = None,
        document_types: Optional[List[str]] = None,
    ) -> List[RetrievedDocument]:
        """
        Retrieve relevant documents for a query using RAG.

        Args:
            query: User query or question
            context: User and session context
            filters: Additional metadata filters
            document_types: Limit to specific document types

        Returns:
            List of retrieved documents with relevance scores
        """

        logger.info(f"RAG retrieval for query: '{query[:50]}...'")

        # Prepare filters
        combined_filters = self._build_filters(filters, document_types, context)

        # Perform vector similarity search
        similarity_results = await self.embedding_manager.search(
            query=query,
            limit=self.config.max_results * 2,  # Get more for re-ranking
            threshold=self.config.similarity_threshold,
            filters=combined_filters,
        )

        if not similarity_results:
            logger.info("No documents found matching query")
            return []

        # Apply business rule filtering
        filtered_results = self._apply_business_filters(similarity_results, context)

        # Re-rank results
        if self.config.enable_reranking:
            reranked_results = self._rerank_results(filtered_results, query, context)
        else:
            reranked_results = filtered_results

        # Limit to max results
        final_results = reranked_results[: self.config.max_results]

        # Convert to RetrievedDocument objects
        retrieved_docs = []
        for i, result in enumerate(final_results):
            retrieved_doc = RetrievedDocument(
                document=result.document,
                relevance_score=result.score,
                similarity_score=result.score,
                business_score=0.0,  # Will be updated in re-ranking
                rank=i + 1,
                retrieval_reason=self._get_retrieval_reason(result, query, context),
            )
            retrieved_docs.append(retrieved_doc)

        logger.info(f"Retrieved {len(retrieved_docs)} relevant documents")
        return retrieved_docs

    def _build_filters(
        self,
        base_filters: Optional[Dict[str, Any]],
        document_types: Optional[List[str]],
        context: Optional[RetrievalContext],
    ) -> Dict[str, Any]:
        """Build comprehensive filters for search."""

        filters = base_filters.copy() if base_filters else {}

        # Add document type filter
        if document_types:
            filters["document_type"] = (
                document_types[0] if len(document_types) == 1 else document_types
            )

        # Add tenant filter
        if context and context.tenant_id:
            filters["tenant_id"] = context.tenant_id

        return filters

    def _apply_business_filters(
        self, results: List[SimilarityResult], context: Optional[RetrievalContext]
    ) -> List[SimilarityResult]:
        """Apply business-specific filtering rules."""

        filtered_results = []
        current_time = context.current_time if context else datetime.now()

        for result in results:
            doc = result.document
            metadata = doc.metadata

            # Filter unavailable items
            if self.config.respect_availability:
                if metadata.get("available") is False:
                    continue

                # Check if item is in stock
                if metadata.get("stock", 1) <= 0:
                    continue

            # Business hours filter (for restaurant-specific content)
            if self.config.respect_business_hours:
                if not self._is_within_business_hours(metadata, current_time):
                    continue

            # Dietary restriction filter
            if context and context.user_preferences:
                user_dietary = context.user_preferences.get("dietary_restrictions", [])
                item_dietary = metadata.get("dietary_info", [])

                # If user has dietary restrictions, ensure item meets them
                if user_dietary:
                    if not any(
                        restriction in item_dietary for restriction in user_dietary
                    ):
                        # Only filter if it's a menu item and conflicts with dietary needs
                        if metadata.get("document_type") == "menu_item":
                            continue

            filtered_results.append(result)

        return filtered_results

    def _is_within_business_hours(
        self, metadata: Dict[str, Any], current_time: datetime
    ) -> bool:
        """Check if current time is within business hours."""

        # If no business hours specified, assume always available
        business_hours = metadata.get("business_hours")
        if not business_hours:
            return True

        current_hour = current_time.hour
        current_day = current_time.strftime("%A").lower()

        day_hours = business_hours.get(current_day)
        if not day_hours:
            return False

        # Parse hours (e.g., "9:00-22:00")
        if "-" in day_hours:
            open_hour, close_hour = day_hours.split("-")
            open_hour = int(open_hour.split(":")[0])
            close_hour = int(close_hour.split(":")[0])

            return open_hour <= current_hour < close_hour

        return True

    def _rerank_results(
        self,
        results: List[SimilarityResult],
        query: str,
        context: Optional[RetrievalContext],
    ) -> List[SimilarityResult]:
        """Re-rank results using business rules and user context."""

        scored_results = []

        for result in results:
            doc = result.document
            metadata = doc.metadata

            # Start with similarity score
            total_score = result.score

            # Boost recent content
            if self.config.boost_recent:
                total_score += self._calculate_recency_boost(metadata)

            # Boost popular items
            if self.config.boost_popular:
                total_score += self._calculate_popularity_boost(metadata)

            # Boost user preference matches
            if context:
                total_score += self._calculate_preference_boost(metadata, context)

            # Boost exact keyword matches
            total_score += self._calculate_keyword_boost(doc.content, query)

            # Create new result with updated score
            enhanced_result = SimilarityResult(
                document=doc,
                score=min(1.0, total_score),  # Cap at 1.0
                distance=result.distance,
            )

            scored_results.append(enhanced_result)

        # Sort by enhanced score
        scored_results.sort(key=lambda x: x.score, reverse=True)

        return scored_results

    def _calculate_recency_boost(self, metadata: Dict[str, Any]) -> float:
        """Calculate boost based on content recency."""

        updated_at = metadata.get("updated_at")
        if not updated_at:
            return 0.0

        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at)
            except:
                return 0.0

        # Boost content updated in last 7 days
        days_old = (datetime.now() - updated_at).days
        if days_old <= 7:
            return 0.1 * (7 - days_old) / 7

        return 0.0

    def _calculate_popularity_boost(self, metadata: Dict[str, Any]) -> float:
        """Calculate boost based on item popularity."""

        # Order count boost
        order_count = metadata.get("order_count", 0)
        if order_count > 0:
            # Logarithmic scaling for popularity
            import math

            return min(0.2, 0.05 * math.log10(order_count + 1))

        # Rating boost
        rating = metadata.get("rating", 0.0)
        if rating >= 4.0:
            return 0.1
        elif rating >= 3.5:
            return 0.05

        return 0.0

    def _calculate_preference_boost(
        self, metadata: Dict[str, Any], context: RetrievalContext
    ) -> float:
        """Calculate boost based on user preferences and history."""

        boost = 0.0

        # User preference matching
        if context.user_preferences:
            user_dietary = context.user_preferences.get("dietary_restrictions", [])
            item_dietary = metadata.get("dietary_info", [])

            # Boost items matching dietary preferences
            if user_dietary and any(pref in item_dietary for pref in user_dietary):
                boost += 0.15

            # Favorite category boost
            favorite_category = context.user_preferences.get("favorite_category")
            if favorite_category and metadata.get("category") == favorite_category:
                boost += 0.1

        # Order history boost
        if context.order_history:
            item_name = metadata.get("name", "").lower()

            # Check if user has ordered this item before
            for order in context.order_history:
                order_items = order.get("items", [])
                for order_item in order_items:
                    if order_item.get("name", "").lower() == item_name:
                        boost += 0.2
                        break  # Only boost once per unique item

        return min(0.3, boost)  # Cap preference boost

    def _calculate_keyword_boost(self, content: str, query: str) -> float:
        """Calculate boost for exact keyword matches."""

        content_lower = content.lower()
        query_lower = query.lower()
        query_words = query_lower.split()

        boost = 0.0

        # Boost for each exact word match
        for word in query_words:
            if len(word) > 2 and word in content_lower:
                boost += 0.02

        # Extra boost for phrase matches
        if query_lower in content_lower:
            boost += 0.05

        return min(0.15, boost)  # Cap keyword boost

    def _get_retrieval_reason(
        self, result: SimilarityResult, query: str, context: Optional[RetrievalContext]
    ) -> str:
        """Generate explanation for why document was retrieved."""

        reasons = []
        metadata = result.document.metadata

        # Similarity reason
        if result.score > 0.8:
            reasons.append("high semantic similarity")
        elif result.score > 0.6:
            reasons.append("good semantic match")
        else:
            reasons.append("semantic relevance")

        # Keyword matching
        content_lower = result.document.content.lower()
        query_lower = query.lower()

        if query_lower in content_lower:
            reasons.append("exact phrase match")

        query_words = [w for w in query_lower.split() if len(w) > 2]
        matched_words = [w for w in query_words if w in content_lower]

        if len(matched_words) > len(query_words) * 0.5:
            reasons.append("keyword match")

        # Business relevance
        if metadata.get("document_type") == "menu_item":
            if metadata.get("available", True):
                reasons.append("available menu item")

            if metadata.get("rating", 0) >= 4.0:
                reasons.append("highly rated")

        # User context
        if context and context.user_preferences:
            user_dietary = context.user_preferences.get("dietary_restrictions", [])
            item_dietary = metadata.get("dietary_info", [])

            if user_dietary and any(pref in item_dietary for pref in user_dietary):
                reasons.append("matches dietary preferences")

        return ", ".join(reasons) if reasons else "general relevance"

    def format_context_for_llm(
        self, retrieved_docs: List[RetrievedDocument], query: str
    ) -> str:
        """Format retrieved documents as context for LLM."""

        if not retrieved_docs:
            return ""

        context_parts = [f"Relevant information for query: '{query}'\n"]

        for i, retrieved_doc in enumerate(retrieved_docs, 1):
            doc = retrieved_doc.document

            # Format document content
            doc_content = f"[{i}] {doc.content}"

            # Add metadata if configured
            if self.config.include_metadata and doc.metadata:
                metadata_str = self._format_metadata_for_context(doc.metadata)
                if metadata_str:
                    doc_content += f"\nMetadata: {metadata_str}"

            # Add relevance info
            doc_content += f"\n(Relevance: {retrieved_doc.similarity_score:.2f}, Reason: {retrieved_doc.retrieval_reason})"

            context_parts.append(doc_content)

        full_context = "\n\n".join(context_parts)

        # Truncate if too long
        if self._estimate_tokens(full_context) > self.config.context_window_tokens:
            full_context = self._truncate_context(
                full_context, self.config.context_window_tokens
            )

        return full_context

    def _format_metadata_for_context(self, metadata: Dict[str, Any]) -> str:
        """Format metadata for LLM context."""

        # Only include relevant metadata fields
        relevant_fields = [
            "category",
            "price",
            "dietary_info",
            "rating",
            "available",
            "document_type",
            "section",
        ]

        formatted_items = []
        for field in relevant_fields:
            if field in metadata and metadata[field] is not None:
                value = metadata[field]
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                formatted_items.append(f"{field}: {value}")

        return "; ".join(formatted_items)

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation."""
        return len(text.split()) * 1.3  # Approximate tokens

    def _truncate_context(self, context: str, max_tokens: int) -> str:
        """Truncate context to fit within token limit."""

        estimated_tokens = self._estimate_tokens(context)
        if estimated_tokens <= max_tokens:
            return context

        # Calculate truncation ratio
        truncation_ratio = max_tokens / estimated_tokens
        target_length = int(len(context) * truncation_ratio * 0.9)  # 90% to be safe

        # Truncate and add ellipsis
        truncated = context[:target_length]

        # Try to end at a sentence boundary
        last_period = truncated.rfind(".")
        if last_period > target_length * 0.8:  # If we can find a good break point
            truncated = truncated[: last_period + 1]

        return truncated + "\n\n[Context truncated due to length limits]"


# Convenience functions for common RAG operations
async def retrieve_menu_items(
    embedding_manager: EmbeddingManager,
    query: str,
    user_preferences: Optional[Dict[str, Any]] = None,
    max_results: int = 5,
) -> List[RetrievedDocument]:
    """Retrieve relevant menu items for a query."""

    config = RetrievalConfig(max_results=max_results)
    retriever = RAGRetriever(embedding_manager, config)

    context = RetrievalContext(user_preferences=user_preferences)

    return await retriever.retrieve(
        query=query, context=context, document_types=["menu_item"]
    )


async def retrieve_policies(
    embedding_manager: EmbeddingManager,
    query: str,
    section: Optional[str] = None,
    max_results: int = 3,
) -> List[RetrievedDocument]:
    """Retrieve relevant policy information."""

    config = RetrievalConfig(max_results=max_results)
    retriever = RAGRetriever(embedding_manager, config)

    filters = {"section": section} if section else None

    return await retriever.retrieve(
        query=query, filters=filters, document_types=["policy"]
    )
