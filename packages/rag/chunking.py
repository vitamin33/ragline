"""
RAGline Document Chunking Module

Implements various chunking strategies for different document types.
Optimized for restaurant menu items, policies, and customer data.
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import tiktoken
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Represents a document chunk with metadata."""

    content: str
    chunk_id: str
    document_id: str
    metadata: Dict[str, Any]
    start_index: int = 0
    end_index: int = 0
    token_count: Optional[int] = None


class ChunkingConfig(BaseModel):
    """Configuration for chunking strategies."""

    # General settings
    chunk_size: int = Field(default=512, description="Maximum tokens per chunk")
    overlap_size: int = Field(default=50, description="Overlap tokens between chunks")
    min_chunk_size: int = Field(default=50, description="Minimum tokens per chunk")

    # Text processing
    preserve_sentences: bool = Field(default=True, description="Try to keep sentences intact")
    preserve_paragraphs: bool = Field(default=True, description="Try to keep paragraphs intact")

    # Tokenizer settings
    tokenizer_model: str = Field(default="cl100k_base", description="Tokenizer model name")

    # Metadata settings
    include_document_metadata: bool = Field(default=True, description="Include document metadata in chunks")
    include_position_metadata: bool = Field(default=True, description="Include position metadata")


class DocumentChunker(ABC):
    """Abstract base class for document chunkers."""

    def __init__(self, config: ChunkingConfig):
        self.config = config
        try:
            self.tokenizer = tiktoken.get_encoding(config.tokenizer_model)
        except Exception as e:
            logger.warning(f"Failed to load tokenizer {config.tokenizer_model}: {e}")
            self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        try:
            return len(self.tokenizer.encode(text))
        except Exception as e:
            logger.warning(f"Token counting failed: {e}")
            # Fallback to approximate word-based counting
            return len(text.split()) * 1.3

    @abstractmethod
    def chunk_document(
        self,
        content: str,
        document_id: str,
        document_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Chunk]:
        """Chunk a document into smaller pieces."""
        pass

    def create_chunk_metadata(
        self,
        document_metadata: Optional[Dict[str, Any]],
        chunk_index: int,
        total_chunks: int,
        start_index: int,
        end_index: int,
    ) -> Dict[str, Any]:
        """Create metadata for a chunk."""
        metadata = {}

        # Include document metadata
        if self.config.include_document_metadata and document_metadata:
            metadata.update(document_metadata)

        # Add position metadata
        if self.config.include_position_metadata:
            metadata.update(
                {
                    "chunk_index": chunk_index,
                    "total_chunks": total_chunks,
                    "start_index": start_index,
                    "end_index": end_index,
                    "chunk_created_at": datetime.now().isoformat(),
                }
            )

        return metadata


class StructuredDataChunker(DocumentChunker):
    """Chunker for structured data like menu items."""

    def chunk_document(
        self,
        content: str,
        document_id: str,
        document_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Chunk]:
        """
        For structured data, each item is typically one chunk.
        Used for menu items, customer orders, etc.
        """

        # For menu items, the content is already well-structured
        token_count = self.count_tokens(content)

        # If content is too large, split by sentences
        if token_count > self.config.chunk_size:
            return self._split_large_structured_content(content, document_id, document_metadata)

        # Single chunk for normal-sized structured content
        chunk_id = f"{document_id}_chunk_0"

        metadata = self.create_chunk_metadata(document_metadata, 0, 1, 0, len(content))

        chunk = Chunk(
            content=content,
            chunk_id=chunk_id,
            document_id=document_id,
            metadata=metadata,
            start_index=0,
            end_index=len(content),
            token_count=token_count,
        )

        return [chunk]

    def _split_large_structured_content(
        self,
        content: str,
        document_id: str,
        document_metadata: Optional[Dict[str, Any]],
    ) -> List[Chunk]:
        """Split large structured content by sentences."""

        sentences = re.split(r"(?<=[.!?])\s+", content)
        chunks = []
        current_chunk = ""
        current_tokens = 0
        start_index = 0

        for sentence in sentences:
            sentence_tokens = self.count_tokens(sentence)

            # If adding this sentence would exceed chunk size
            if current_tokens + sentence_tokens > self.config.chunk_size and current_chunk:
                # Create chunk
                chunk_id = f"{document_id}_chunk_{len(chunks)}"
                end_index = start_index + len(current_chunk)

                metadata = self.create_chunk_metadata(document_metadata, len(chunks), -1, start_index, end_index)

                chunk = Chunk(
                    content=current_chunk.strip(),
                    chunk_id=chunk_id,
                    document_id=document_id,
                    metadata=metadata,
                    start_index=start_index,
                    end_index=end_index,
                    token_count=current_tokens,
                )
                chunks.append(chunk)

                # Start new chunk with overlap
                overlap_text = (
                    current_chunk[-self.config.overlap_size :] if len(current_chunk) > self.config.overlap_size else ""
                )
                current_chunk = overlap_text + " " + sentence
                current_tokens = self.count_tokens(current_chunk)
                start_index = end_index - len(overlap_text)
            else:
                # Add sentence to current chunk
                current_chunk += " " + sentence if current_chunk else sentence
                current_tokens += sentence_tokens

        # Add final chunk
        if current_chunk and current_tokens >= self.config.min_chunk_size:
            chunk_id = f"{document_id}_chunk_{len(chunks)}"
            end_index = start_index + len(current_chunk)

            metadata = self.create_chunk_metadata(
                document_metadata, len(chunks), len(chunks) + 1, start_index, end_index
            )

            chunk = Chunk(
                content=current_chunk.strip(),
                chunk_id=chunk_id,
                document_id=document_id,
                metadata=metadata,
                start_index=start_index,
                end_index=end_index,
                token_count=current_tokens,
            )
            chunks.append(chunk)

        # Update total_chunks in metadata
        for chunk in chunks:
            chunk.metadata["total_chunks"] = len(chunks)

        return chunks


class UnstructuredTextChunker(DocumentChunker):
    """Chunker for unstructured text documents like policies and FAQs."""

    def chunk_document(
        self,
        content: str,
        document_id: str,
        document_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Chunk]:
        """
        Chunk unstructured text using sentence-aware splitting.
        Preserves sentence boundaries while respecting token limits.
        """

        # Clean and normalize content
        content = self._clean_text(content)

        # Split into paragraphs first
        if self.config.preserve_paragraphs:
            return self._chunk_by_paragraphs(content, document_id, document_metadata)
        else:
            return self._chunk_by_sentences(content, document_id, document_metadata)

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text content."""
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)

        # Remove empty lines
        text = re.sub(r"\n\s*\n", "\n\n", text)

        return text.strip()

    def _chunk_by_paragraphs(
        self,
        content: str,
        document_id: str,
        document_metadata: Optional[Dict[str, Any]],
    ) -> List[Chunk]:
        """Chunk text by paragraphs, splitting large paragraphs as needed."""

        paragraphs = content.split("\n\n")
        chunks = []
        current_chunk = ""
        current_tokens = 0
        char_offset = 0

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            paragraph_tokens = self.count_tokens(paragraph)

            # If paragraph is too large, split it by sentences
            if paragraph_tokens > self.config.chunk_size:
                # First, add current chunk if it exists
                if current_chunk and current_tokens >= self.config.min_chunk_size:
                    chunks.append(
                        self._create_chunk(
                            current_chunk,
                            document_id,
                            document_metadata,
                            len(chunks),
                            char_offset - len(current_chunk),
                            char_offset,
                        )
                    )
                    current_chunk = ""
                    current_tokens = 0

                # Split large paragraph
                paragraph_chunks = self._chunk_by_sentences(
                    paragraph, f"{document_id}_para_{len(chunks)}", document_metadata
                )
                chunks.extend(paragraph_chunks)

                char_offset += len(paragraph) + 2  # +2 for \n\n
                continue

            # Check if adding paragraph exceeds chunk size
            if current_tokens + paragraph_tokens > self.config.chunk_size and current_chunk:
                # Create current chunk
                chunks.append(
                    self._create_chunk(
                        current_chunk,
                        document_id,
                        document_metadata,
                        len(chunks),
                        char_offset - len(current_chunk),
                        char_offset,
                    )
                )

                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_chunk)
                current_chunk = overlap_text + "\n\n" + paragraph if overlap_text else paragraph
                current_tokens = self.count_tokens(current_chunk)
            else:
                # Add paragraph to current chunk
                current_chunk += "\n\n" + paragraph if current_chunk else paragraph
                current_tokens += paragraph_tokens

            char_offset += len(paragraph) + 2

        # Add final chunk
        if current_chunk and current_tokens >= self.config.min_chunk_size:
            chunks.append(
                self._create_chunk(
                    current_chunk,
                    document_id,
                    document_metadata,
                    len(chunks),
                    char_offset - len(current_chunk),
                    char_offset,
                )
            )

        return self._finalize_chunks(chunks)

    def _chunk_by_sentences(
        self,
        content: str,
        document_id: str,
        document_metadata: Optional[Dict[str, Any]],
    ) -> List[Chunk]:
        """Chunk text by sentences."""

        sentences = self._split_sentences(content)
        chunks = []
        current_chunk = ""
        current_tokens = 0
        char_offset = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_tokens = self.count_tokens(sentence)

            # If single sentence is too large, split by words (last resort)
            if sentence_tokens > self.config.chunk_size:
                if current_chunk:
                    chunks.append(
                        self._create_chunk(
                            current_chunk,
                            document_id,
                            document_metadata,
                            len(chunks),
                            char_offset - len(current_chunk),
                            char_offset,
                        )
                    )
                    current_chunk = ""
                    current_tokens = 0

                # Split large sentence by words
                word_chunks = self._chunk_by_words(sentence, document_id, document_metadata)
                chunks.extend(word_chunks)
                char_offset += len(sentence) + 1
                continue

            # Check if adding sentence exceeds chunk size
            if current_tokens + sentence_tokens > self.config.chunk_size and current_chunk:
                # Create current chunk
                chunks.append(
                    self._create_chunk(
                        current_chunk,
                        document_id,
                        document_metadata,
                        len(chunks),
                        char_offset - len(current_chunk),
                        char_offset,
                    )
                )

                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_chunk)
                current_chunk = overlap_text + " " + sentence if overlap_text else sentence
                current_tokens = self.count_tokens(current_chunk)
            else:
                # Add sentence to current chunk
                current_chunk += " " + sentence if current_chunk else sentence
                current_tokens += sentence_tokens

            char_offset += len(sentence) + 1

        # Add final chunk
        if current_chunk and current_tokens >= self.config.min_chunk_size:
            chunks.append(
                self._create_chunk(
                    current_chunk,
                    document_id,
                    document_metadata,
                    len(chunks),
                    char_offset - len(current_chunk),
                    char_offset,
                )
            )

        return self._finalize_chunks(chunks)

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences using regex."""
        # Improved sentence splitting that handles common abbreviations
        sentence_pattern = r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\!|\?)\s+"
        sentences = re.split(sentence_pattern, text)
        return [s.strip() for s in sentences if s.strip()]

    def _chunk_by_words(self, text: str, document_id: str, document_metadata: Optional[Dict[str, Any]]) -> List[Chunk]:
        """Last resort: chunk by words when sentences are too large."""

        words = text.split()
        chunks = []
        current_chunk = ""
        current_tokens = 0
        char_offset = 0

        for word in words:
            word_tokens = self.count_tokens(word)

            if current_tokens + word_tokens > self.config.chunk_size and current_chunk:
                chunks.append(
                    self._create_chunk(
                        current_chunk,
                        document_id,
                        document_metadata,
                        len(chunks),
                        char_offset - len(current_chunk),
                        char_offset,
                    )
                )

                current_chunk = word
                current_tokens = word_tokens
            else:
                current_chunk += " " + word if current_chunk else word
                current_tokens += word_tokens

            char_offset += len(word) + 1

        if current_chunk:
            chunks.append(
                self._create_chunk(
                    current_chunk,
                    document_id,
                    document_metadata,
                    len(chunks),
                    char_offset - len(current_chunk),
                    char_offset,
                )
            )

        return chunks

    def _get_overlap_text(self, text: str) -> str:
        """Extract overlap text from the end of current chunk."""
        if not text or self.config.overlap_size <= 0:
            return ""

        # Try to get overlap by sentences first
        sentences = self._split_sentences(text)
        overlap_text = ""
        overlap_tokens = 0

        for sentence in reversed(sentences):
            sentence_tokens = self.count_tokens(sentence)
            if overlap_tokens + sentence_tokens <= self.config.overlap_size:
                overlap_text = sentence + " " + overlap_text if overlap_text else sentence
                overlap_tokens += sentence_tokens
            else:
                break

        # If no complete sentences fit, use word-based overlap
        if not overlap_text:
            words = text.split()
            for word in reversed(words):
                word_tokens = self.count_tokens(word)
                if overlap_tokens + word_tokens <= self.config.overlap_size:
                    overlap_text = word + " " + overlap_text if overlap_text else word
                    overlap_tokens += word_tokens
                else:
                    break

        return overlap_text.strip()

    def _create_chunk(
        self,
        content: str,
        document_id: str,
        document_metadata: Optional[Dict[str, Any]],
        chunk_index: int,
        start_index: int,
        end_index: int,
    ) -> Chunk:
        """Create a chunk object."""
        chunk_id = f"{document_id}_chunk_{chunk_index}"

        metadata = self.create_chunk_metadata(document_metadata, chunk_index, -1, start_index, end_index)

        token_count = self.count_tokens(content)

        return Chunk(
            content=content.strip(),
            chunk_id=chunk_id,
            document_id=document_id,
            metadata=metadata,
            start_index=start_index,
            end_index=end_index,
            token_count=token_count,
        )

    def _finalize_chunks(self, chunks: List[Chunk]) -> List[Chunk]:
        """Finalize chunks by updating total_chunks metadata."""
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk.metadata["total_chunks"] = total_chunks

        return chunks


class ChunkingStrategy:
    """Factory for creating appropriate chunkers based on document type."""

    @staticmethod
    def create_chunker(document_type: str, config: Optional[ChunkingConfig] = None) -> DocumentChunker:
        """Create appropriate chunker based on document type."""

        if config is None:
            config = ChunkingConfig()

        if document_type in ["menu_item", "order", "customer_data", "structured"]:
            return StructuredDataChunker(config)
        elif document_type in ["policy", "faq", "documentation", "unstructured"]:
            return UnstructuredTextChunker(config)
        else:
            # Default to unstructured text chunker
            logger.warning(f"Unknown document type '{document_type}', using unstructured chunker")
            return UnstructuredTextChunker(config)


# Convenience functions
def chunk_menu_item(item_data: Dict[str, Any], item_id: str, config: Optional[ChunkingConfig] = None) -> List[Chunk]:
    """Chunk a menu item into searchable content."""

    # Format menu item content
    content_parts = []

    if "name" in item_data:
        content_parts.append(f"Name: {item_data['name']}")

    if "description" in item_data:
        content_parts.append(f"Description: {item_data['description']}")

    if "ingredients" in item_data:
        ingredients = ", ".join(item_data["ingredients"])
        content_parts.append(f"Ingredients: {ingredients}")

    if "category" in item_data:
        content_parts.append(f"Category: {item_data['category']}")

    if "price" in item_data:
        content_parts.append(f"Price: ${item_data['price']}")

    if "dietary_info" in item_data:
        dietary = ", ".join(item_data["dietary_info"])
        content_parts.append(f"Dietary: {dietary}")

    content = "\n".join(content_parts)

    # Create chunker
    chunker = ChunkingStrategy.create_chunker("menu_item", config)

    # Add document type to metadata
    metadata = dict(item_data)
    metadata["document_type"] = "menu_item"

    return chunker.chunk_document(content, item_id, metadata)


def chunk_policy_document(
    content: str,
    document_id: str,
    section: Optional[str] = None,
    config: Optional[ChunkingConfig] = None,
) -> List[Chunk]:
    """Chunk a policy document."""

    chunker = ChunkingStrategy.create_chunker("policy", config)

    metadata = {"document_type": "policy", "section": section}

    return chunker.chunk_document(content, document_id, metadata)
