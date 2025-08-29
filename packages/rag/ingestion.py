"""
RAGline Data Ingestion Module

Handles ingesting various data sources into the RAG system.
Processes menu items, policies, and customer data for vector search.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .chunking import chunk_menu_item, chunk_policy_document
from .embeddings import EmbeddingManager

logger = logging.getLogger(__name__)


class DataIngestionManager:
    """Manages data ingestion into the RAG system."""

    def __init__(self, embedding_manager: EmbeddingManager):
        self.embedding_manager = embedding_manager

    async def ingest_menu_items(
        self, menu_items: List[Dict[str, Any]], tenant_id: Optional[str] = None
    ) -> List[str]:
        """Ingest menu items into the RAG system."""

        logger.info(f"Ingesting {len(menu_items)} menu items")

        all_chunks = []
        document_ids = []

        for item in menu_items:
            # Generate document ID
            item_id = (
                item.get("id") or item.get("sku") or str(hash(item.get("name", "")))
            )
            if tenant_id:
                doc_id = f"{tenant_id}_menu_{item_id}"
            else:
                doc_id = f"menu_{item_id}"

            # Add tenant to metadata
            item_metadata = dict(item)
            if tenant_id:
                item_metadata["tenant_id"] = tenant_id
            item_metadata["document_type"] = "menu_item"
            item_metadata["ingested_at"] = datetime.now().isoformat()

            # Chunk the menu item
            chunks = chunk_menu_item(item_metadata, doc_id)

            # Convert chunks to documents
            for chunk in chunks:
                texts = [chunk.content]
                metadatas = [chunk.metadata]
                chunk_ids = [chunk.chunk_id]

                doc_ids = await self.embedding_manager.add_documents(
                    texts=texts, metadatas=metadatas, document_ids=chunk_ids
                )
                document_ids.extend(doc_ids)

        logger.info(f"Successfully ingested {len(document_ids)} menu item chunks")
        return document_ids

    async def ingest_policy_documents(
        self, policies: List[Dict[str, str]], tenant_id: Optional[str] = None
    ) -> List[str]:
        """Ingest policy documents into the RAG system."""

        logger.info(f"Ingesting {len(policies)} policy documents")

        document_ids = []

        for policy in policies:
            policy_id = policy.get("id", str(hash(policy.get("title", ""))))
            if tenant_id:
                doc_id = f"{tenant_id}_policy_{policy_id}"
            else:
                doc_id = f"policy_{policy_id}"

            # Chunk the policy document
            chunks = chunk_policy_document(
                content=policy.get("content", ""),
                document_id=doc_id,
                section=policy.get("section"),
            )

            for chunk in chunks:
                # Add policy metadata to chunk
                chunk_metadata = chunk.metadata.copy()
                chunk_metadata.update(
                    {
                        "title": policy.get("title"),
                        "section": policy.get("section"),
                        "document_type": "policy",
                        "tenant_id": tenant_id,
                        "ingested_at": datetime.now().isoformat(),
                    }
                )

                texts = [chunk.content]
                metadatas = [chunk_metadata]
                chunk_ids = [chunk.chunk_id]

                doc_ids = await self.embedding_manager.add_documents(
                    texts=texts, metadatas=metadatas, document_ids=chunk_ids
                )
                document_ids.extend(doc_ids)

        logger.info(f"Successfully ingested {len(document_ids)} policy chunks")
        return document_ids

    async def ingest_faq_items(
        self, faq_items: List[Dict[str, str]], tenant_id: Optional[str] = None
    ) -> List[str]:
        """Ingest FAQ items into the RAG system."""

        logger.info(f"Ingesting {len(faq_items)} FAQ items")

        texts = []
        metadatas = []
        document_ids = []

        for i, faq in enumerate(faq_items):
            question = faq.get("question", "")
            answer = faq.get("answer", "")

            # Combine question and answer
            content = f"Q: {question}\nA: {answer}"

            # Create document ID
            faq_id = faq.get("id", f"faq_{i}")
            if tenant_id:
                doc_id = f"{tenant_id}_faq_{faq_id}"
            else:
                doc_id = f"faq_{faq_id}"

            # Create metadata
            metadata = {
                "document_type": "faq",
                "question": question,
                "category": faq.get("category", "general"),
                "tenant_id": tenant_id,
                "ingested_at": datetime.now().isoformat(),
            }

            texts.append(content)
            metadatas.append(metadata)
            document_ids.append(doc_id)

        # Add documents in batch
        doc_ids = await self.embedding_manager.add_documents(
            texts=texts, metadatas=metadatas, document_ids=document_ids
        )

        logger.info(f"Successfully ingested {len(doc_ids)} FAQ items")
        return doc_ids

    async def update_menu_item_availability(
        self, item_updates: Dict[str, bool], tenant_id: Optional[str] = None
    ):
        """Update menu item availability in the vector store."""

        logger.info(f"Updating availability for {len(item_updates)} items")

        for item_id, available in item_updates.items():
            if tenant_id:
                doc_id = f"{tenant_id}_menu_{item_id}"
            else:
                doc_id = f"menu_{item_id}"

            # Get existing document
            document = await self.embedding_manager.get_document(doc_id)
            if document:
                # Update metadata
                document.metadata["available"] = available
                document.metadata["updated_at"] = datetime.now().isoformat()

                # Re-ingest with updated metadata
                await self.embedding_manager.add_documents(
                    texts=[document.content],
                    metadatas=[document.metadata],
                    document_ids=[doc_id],
                )

        logger.info("Availability updates completed")

    async def cleanup_old_documents(
        self, tenant_id: Optional[str] = None, days_old: int = 30
    ):
        """Remove old documents from the vector store."""

        logger.info(f"Cleaning up documents older than {days_old} days")

        # This would require additional vector store functionality
        # to query by metadata and delete matching documents
        # Implementation depends on specific vector store capabilities

        logger.warning(
            "Document cleanup not implemented - requires vector store enhancement"
        )


# Sample data for testing
SAMPLE_MENU_ITEMS = [
    {
        "id": "item_1",
        "name": "Margherita Pizza",
        "description": "Classic pizza with fresh mozzarella, tomatoes, and basil on thin crust",
        "ingredients": ["mozzarella", "tomatoes", "basil", "olive oil", "pizza dough"],
        "category": "mains",
        "price": 16.99,
        "dietary_info": ["vegetarian"],
        "available": True,
        "rating": 4.5,
        "order_count": 145,
    },
    {
        "id": "item_2",
        "name": "Grilled Chicken Caesar Salad",
        "description": "Crisp romaine lettuce with grilled chicken breast, parmesan, and croutons",
        "ingredients": [
            "romaine lettuce",
            "grilled chicken",
            "parmesan",
            "croutons",
            "caesar dressing",
        ],
        "category": "mains",
        "price": 14.99,
        "dietary_info": ["gluten-free"],
        "available": True,
        "rating": 4.2,
        "order_count": 89,
    },
    {
        "id": "item_3",
        "name": "Vegan Buddha Bowl",
        "description": "Nutritious bowl with quinoa, roasted vegetables, and tahini dressing",
        "ingredients": [
            "quinoa",
            "roasted vegetables",
            "chickpeas",
            "avocado",
            "tahini",
        ],
        "category": "mains",
        "price": 13.99,
        "dietary_info": ["vegan", "vegetarian", "gluten-free"],
        "available": True,
        "rating": 4.7,
        "order_count": 67,
    },
    {
        "id": "item_4",
        "name": "Chocolate Lava Cake",
        "description": "Warm chocolate cake with molten center, served with vanilla ice cream",
        "ingredients": [
            "dark chocolate",
            "butter",
            "eggs",
            "sugar",
            "flour",
            "vanilla ice cream",
        ],
        "category": "desserts",
        "price": 8.99,
        "dietary_info": ["vegetarian"],
        "available": True,
        "rating": 4.8,
        "order_count": 156,
    },
    {
        "id": "item_5",
        "name": "Garlic Bread",
        "description": "Crispy bread with garlic butter and fresh herbs",
        "ingredients": ["bread", "garlic", "butter", "herbs", "parmesan"],
        "category": "appetizers",
        "price": 6.99,
        "dietary_info": ["vegetarian"],
        "available": True,
        "rating": 4.1,
        "order_count": 203,
    },
    {
        "id": "item_6",
        "name": "Spicy Buffalo Wings",
        "description": "Traditional buffalo wings with celery sticks and blue cheese dressing",
        "ingredients": ["chicken wings", "buffalo sauce", "celery", "blue cheese"],
        "category": "appetizers",
        "price": 12.99,
        "dietary_info": [],
        "available": True,
        "rating": 4.3,
        "order_count": 98,
    },
]

SAMPLE_POLICY_DOCUMENTS = [
    {
        "id": "delivery_policy",
        "title": "Delivery Policy",
        "section": "delivery",
        "content": """
        Delivery Information:

        We deliver within a 5-mile radius of our restaurant location. Delivery fee is $3.99 for orders under $25, free delivery for orders over $25.

        Delivery times are typically 30-45 minutes during regular hours and may extend to 60 minutes during peak times (Friday-Sunday 6-8 PM).

        Our delivery area includes downtown, midtown, and surrounding residential areas. We do not deliver to locations outside our designated delivery zone.

        For large orders (over $100), please call ahead to ensure availability and faster preparation.
        """,
    },
    {
        "id": "hours_policy",
        "title": "Business Hours",
        "section": "hours",
        "content": """
        Restaurant Hours:

        Monday - Thursday: 11:00 AM - 10:00 PM
        Friday - Saturday: 11:00 AM - 11:00 PM
        Sunday: 12:00 PM - 9:00 PM

        Kitchen closes 30 minutes before closing time.

        Holiday Hours:
        We are closed on Christmas Day and New Year's Day. On other major holidays, we may have modified hours - please call ahead to confirm.

        Last orders are taken 30 minutes before closing time for dine-in and 45 minutes before closing for delivery orders.
        """,
    },
    {
        "id": "allergen_policy",
        "title": "Allergen Information",
        "section": "dietary",
        "content": """
        Allergen and Dietary Information:

        We take food allergies seriously. Please inform our staff of any allergies when ordering.

        Common allergens present in our kitchen include: wheat/gluten, dairy, eggs, nuts, soy, and shellfish.

        While we make every effort to prevent cross-contamination, we cannot guarantee that any menu item is completely free from allergens due to shared cooking equipment and preparation areas.

        Gluten-free options are prepared with care but may come into contact with gluten-containing ingredients.

        Vegan and vegetarian items are clearly marked on our menu. Please ask your server for recommendations based on your dietary needs.
        """,
    },
]

SAMPLE_FAQ_ITEMS = [
    {
        "id": "faq_1",
        "question": "Do you offer vegan options?",
        "answer": "Yes! We have several vegan options including our popular Vegan Buddha Bowl, vegan pizzas with plant-based cheese, and vegan desserts. All vegan items are clearly marked on our menu.",
        "category": "dietary",
    },
    {
        "id": "faq_2",
        "question": "How long does delivery take?",
        "answer": "Typical delivery time is 30-45 minutes during regular hours. During peak times (Friday-Sunday 6-8 PM), it may take up to 60 minutes. We'll provide an estimated delivery time when you place your order.",
        "category": "delivery",
    },
    {
        "id": "faq_3",
        "question": "Can I modify my order after placing it?",
        "answer": "You can modify your order within 5 minutes of placing it by calling our restaurant directly. After 5 minutes, the kitchen begins preparation and modifications may not be possible.",
        "category": "orders",
    },
    {
        "id": "faq_4",
        "question": "Do you accept special dietary requests?",
        "answer": "Yes, we accommodate dietary restrictions whenever possible. Please specify your needs when ordering and our kitchen will do their best to modify dishes accordingly. Note that we cannot guarantee complete allergen-free preparation due to shared equipment.",
        "category": "dietary",
    },
]


# Convenience functions
async def ingest_sample_data(
    embedding_manager: EmbeddingManager, tenant_id: str = "demo_restaurant"
):
    """Ingest sample data for testing and demonstration."""

    ingestion_manager = DataIngestionManager(embedding_manager)

    logger.info("Ingesting sample restaurant data...")

    # Ingest menu items
    menu_doc_ids = await ingestion_manager.ingest_menu_items(
        SAMPLE_MENU_ITEMS, tenant_id=tenant_id
    )

    # Ingest policies
    policy_doc_ids = await ingestion_manager.ingest_policy_documents(
        SAMPLE_POLICY_DOCUMENTS, tenant_id=tenant_id
    )

    # Ingest FAQs
    faq_doc_ids = await ingestion_manager.ingest_faq_items(
        SAMPLE_FAQ_ITEMS, tenant_id=tenant_id
    )

    total_docs = len(menu_doc_ids) + len(policy_doc_ids) + len(faq_doc_ids)
    logger.info(f"Successfully ingested {total_docs} total documents")

    return {
        "menu_items": menu_doc_ids,
        "policies": policy_doc_ids,
        "faqs": faq_doc_ids,
        "total": total_docs,
    }
