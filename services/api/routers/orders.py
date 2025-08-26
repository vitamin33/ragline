from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
import structlog
import json

from packages.db.database import get_db
from packages.db.models import Order, OrderItem, Product
from packages.security.auth import get_current_user_token
from packages.security.jwt import TokenData

router = APIRouter()
logger = structlog.get_logger(__name__)


class OrderItemBase(BaseModel):
    product_id: int
    quantity: int
    unit_price: int  # Price in cents


class OrderItemCreate(BaseModel):
    sku: str
    quantity: int


class OrderItemResponse(OrderItemBase):
    id: int


class OrderBase(BaseModel):
    status: str = "pending"
    currency: str = "USD"


class OrderCreate(BaseModel):
    items: List[OrderItemCreate]


class OrderUpdate(BaseModel):
    status: Optional[str] = None


class OrderResponse(OrderBase):
    id: int
    tenant_id: int
    user_id: int
    total_amount: int
    items: List[OrderItemResponse]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("/", response_model=List[OrderResponse])
async def list_orders(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None
):
    """List orders with pagination and filtering."""
    # TODO: Implement order listing
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Order listing not yet implemented"
    )


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order: OrderCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db)
):
    """Create a new order with idempotency support."""
    tenant_id = token_data.tenant_id
    user_id = token_data.user_id
    
    # Validate idempotency key if provided
    if idempotency_key:
        # Check if order with this idempotency key already exists
        try:
            existing_order_result = await db.execute(
                select(Order).where(
                    and_(
                        Order.idempotency_key == idempotency_key,
                        Order.tenant_id == tenant_id
                    )
                ).options(selectinload(Order.items))
            )
            existing_order = existing_order_result.scalar_one_or_none()
            
            if existing_order and existing_order.response_json:
                # Return cached response for idempotent request
                logger.info("Idempotent request - returning cached response", 
                          tenant_id=tenant_id, idempotency_key=idempotency_key, 
                          order_id=existing_order.id)
                return OrderResponse(**existing_order.response_json)
                
        except Exception as e:
            logger.error("Idempotency check failed", error=str(e))
            # Continue with normal order creation if idempotency check fails
    
    # Validate and calculate order
    try:
        total_amount = 0
        order_items_data = []
        
        # Fetch products and calculate total
        for item in order.items:
            # For this implementation, we'll assume SKU maps to product ID
            # In a real system, you'd have a SKU lookup
            try:
                product_id = int(item.sku.split('-')[-1])  # Extract ID from SKU like "PROD-123"
            except (ValueError, IndexError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid SKU format: {item.sku}. Expected format: PROD-{id}"
                )
            
            # Fetch product to get current price
            product_result = await db.execute(
                select(Product).where(
                    and_(
                        Product.id == product_id,
                        Product.tenant_id == tenant_id,
                        Product.is_active == True
                    )
                )
            )
            product = product_result.scalar_one_or_none()
            
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Product not found or inactive: {item.sku}"
                )
            
            # Calculate line total
            line_total = product.price * item.quantity
            total_amount += line_total
            
            order_items_data.append({
                "product_id": product.id,
                "quantity": item.quantity,
                "unit_price": product.price
            })
        
        # Create order
        db_order = Order(
            tenant_id=tenant_id,
            user_id=user_id,
            total_amount=total_amount,
            idempotency_key=idempotency_key
        )
        
        db.add(db_order)
        await db.flush()  # Get order ID without committing
        
        # Create order items
        db_order_items = []
        for item_data in order_items_data:
            order_item = OrderItem(
                order_id=db_order.id,
                **item_data
            )
            db.add(order_item)
            db_order_items.append(order_item)
        
        await db.commit()
        await db.refresh(db_order)
        
        # Refresh order items
        for item in db_order_items:
            await db.refresh(item)
        
        # Create response object
        response_data = {
            "id": db_order.id,
            "tenant_id": db_order.tenant_id,
            "user_id": db_order.user_id,
            "status": db_order.status,
            "currency": db_order.currency,
            "total_amount": db_order.total_amount,
            "items": [
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price
                }
                for item in db_order_items
            ],
            "created_at": db_order.created_at.isoformat(),
            "updated_at": db_order.updated_at.isoformat()
        }
        
        # Store response for idempotency if key was provided
        if idempotency_key:
            db_order.response_json = response_data
            await db.commit()
        
        logger.info("Order created successfully", 
                   tenant_id=tenant_id, order_id=db_order.id, 
                   total_amount=total_amount, idempotency_key=idempotency_key)
        
        return OrderResponse(**response_data)
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        if "uq_orders_idempotency_key" in str(e):
            # Idempotency key conflict - try to return existing order
            try:
                existing_order_result = await db.execute(
                    select(Order).where(
                        and_(
                            Order.idempotency_key == idempotency_key,
                            Order.tenant_id == tenant_id
                        )
                    )
                )
                existing_order = existing_order_result.scalar_one_or_none()
                
                if existing_order and existing_order.response_json:
                    logger.info("Idempotency conflict resolved with cached response",
                              tenant_id=tenant_id, idempotency_key=idempotency_key)
                    return OrderResponse(**existing_order.response_json)
            except Exception:
                pass
            
        logger.error("Order creation failed - integrity constraint", 
                    tenant_id=tenant_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order creation conflict - please retry"
        )
    except Exception as e:
        await db.rollback()
        logger.error("Order creation failed", tenant_id=tenant_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create order"
        )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int):
    """Get a specific order by ID."""
    # TODO: Implement order retrieval
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Order retrieval not yet implemented"
    )


@router.put("/{order_id}", response_model=OrderResponse)
async def update_order(order_id: int, order: OrderUpdate):
    """Update a specific order."""
    # TODO: Implement order update with outbox pattern
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Order update not yet implemented"
    )


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_order(order_id: int):
    """Cancel a specific order."""
    # TODO: Implement order cancellation with outbox pattern
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Order cancellation not yet implemented"
    )