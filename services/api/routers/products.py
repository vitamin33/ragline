from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.cache.redis_cache import RedisCache, get_cache
from packages.db.database import get_db
from packages.db.models import Product
from packages.security.auth import get_current_user_token
from packages.security.jwt import TokenData

router = APIRouter()
logger = structlog.get_logger(__name__)


class ProductBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: int  # Price in cents
    is_active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    id: int
    tenant_id: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("/", response_model=List[ProductResponse])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Search in product name or description"),
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """List products with pagination and filtering."""
    tenant_id = token_data.tenant_id

    # Build cache key for this query
    cache_key = f"list:{skip}:{limit}:{is_active}:{search or 'none'}"

    # Try cache first
    cached_products = await cache.get(tenant_id, "products", cache_key)
    if cached_products is not None:
        logger.info("Product list cache hit", tenant_id=tenant_id, cache_key=cache_key)
        return [ProductResponse(**product) for product in cached_products]

    # Cache miss - fetch from database
    try:
        query = select(Product).where(Product.tenant_id == tenant_id)

        # Apply filters
        if is_active is not None:
            query = query.where(Product.is_active == is_active)
            
        # Apply search filter
        if search:
            search_term = f"%{search}%"
            query = query.where(
                Product.name.ilike(search_term) | Product.description.ilike(search_term)
            )

        # Apply pagination
        query = query.offset(skip).limit(limit).order_by(Product.created_at.desc())

        result = await db.execute(query)
        products = result.scalars().all()

        # Convert to response format and cache
        product_data = [
            {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "price": product.price,
                "is_active": product.is_active,
                "tenant_id": product.tenant_id,
                "created_at": product.created_at.isoformat(),
                "updated_at": product.updated_at.isoformat(),
            }
            for product in products
        ]

        # Cache the result
        await cache.set(tenant_id, "products", cache_key, product_data, ttl=60)  # 1 minute TTL for lists

        logger.info(
            "Product list fetched from database",
            tenant_id=tenant_id,
            count=len(products),
            search=search,
        )
        return [ProductResponse(**product) for product in product_data]

    except Exception as e:
        logger.error("Product list fetch failed", tenant_id=tenant_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve products",
        )


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    product: ProductCreate,
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """Create a new product."""
    tenant_id = token_data.tenant_id

    try:
        # Create new product
        db_product = Product(
            tenant_id=tenant_id,
            name=product.name,
            description=product.description,
            price=product.price,
            is_active=product.is_active,
        )

        db.add(db_product)
        await db.commit()
        await db.refresh(db_product)

        # Invalidate product list cache
        await cache.invalidate_product_cache(tenant_id)

        logger.info(
            "Product created",
            tenant_id=tenant_id,
            product_id=db_product.id,
            name=product.name,
        )

        return ProductResponse(
            id=db_product.id,
            name=db_product.name,
            description=db_product.description,
            price=db_product.price,
            is_active=db_product.is_active,
            tenant_id=db_product.tenant_id,
            created_at=db_product.created_at.isoformat(),
            updated_at=db_product.updated_at.isoformat(),
        )

    except Exception as e:
        await db.rollback()
        logger.error("Product creation failed", tenant_id=tenant_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create product",
        )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """Get a specific product by ID."""
    tenant_id = token_data.tenant_id

    # Define fetch function for cache-aside pattern
    async def fetch_product():
        try:
            result = await db.execute(
                select(Product).where(and_(Product.id == product_id, Product.tenant_id == tenant_id))
            )
            product = result.scalar_one_or_none()

            if not product:
                return None

            return {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "price": product.price,
                "is_active": product.is_active,
                "tenant_id": product.tenant_id,
                "created_at": product.created_at.isoformat(),
                "updated_at": product.updated_at.isoformat(),
            }
        except Exception as e:
            logger.error(
                "Database fetch failed",
                product_id=product_id,
                tenant_id=tenant_id,
                error=str(e),
            )
            return None

    # Use cache-aside pattern with stampede protection
    try:
        product_data = await cache.get_or_set(
            tenant_id=tenant_id,
            cache_type="product",
            identifier=str(product_id),
            fetch_func=fetch_product,
            ttl=300,  # 5 minutes
            use_lock=True,
        )

        if product_data is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

        logger.info("Product retrieved", tenant_id=tenant_id, product_id=product_id)
        return ProductResponse(**product_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Product retrieval failed",
            product_id=product_id,
            tenant_id=tenant_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve product",
        )


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """Update a specific product."""
    tenant_id = token_data.tenant_id

    try:
        # Fetch existing product
        result = await db.execute(select(Product).where(and_(Product.id == product_id, Product.tenant_id == tenant_id)))
        db_product = result.scalar_one_or_none()

        if not db_product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

        # Update fields that were provided
        update_data = product.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_product, field, value)

        await db.commit()
        await db.refresh(db_product)

        # Invalidate cache
        await cache.invalidate_product_cache(tenant_id, product_id)

        logger.info(
            "Product updated",
            tenant_id=tenant_id,
            product_id=product_id,
            fields=list(update_data.keys()),
        )

        return ProductResponse(
            id=db_product.id,
            name=db_product.name,
            description=db_product.description,
            price=db_product.price,
            is_active=db_product.is_active,
            tenant_id=db_product.tenant_id,
            created_at=db_product.created_at.isoformat(),
            updated_at=db_product.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            "Product update failed",
            product_id=product_id,
            tenant_id=tenant_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update product",
        )


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
):
    """Delete a specific product."""
    tenant_id = token_data.tenant_id
    
    try:
        # Fetch existing product
        result = await db.execute(
            select(Product).where(and_(Product.id == product_id, Product.tenant_id == tenant_id))
        )
        db_product = result.scalar_one_or_none()
        
        if not db_product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        
        # Soft delete by marking inactive
        db_product.is_active = False
        await db.commit()
        
        # Invalidate cache
        await cache.invalidate_product_cache(tenant_id, product_id)
        
        logger.info(
            "Product deleted (soft delete)",
            tenant_id=tenant_id,
            product_id=product_id,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            "Product deletion failed",
            product_id=product_id,
            tenant_id=tenant_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete product",
        )
