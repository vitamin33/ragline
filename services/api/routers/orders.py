from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.db.database import get_db
from packages.db.models import Order, OrderItem, Outbox, Product
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
    status: Optional[str] = None,
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """List orders with pagination and filtering."""
    tenant_id = token_data.tenant_id

    # Build query with tenant isolation
    query = select(Order).where(Order.tenant_id == tenant_id).options(selectinload(Order.items))

    # Add status filtering if provided
    if status:
        query = query.where(Order.status == status)

    # Apply pagination
    query = query.offset(skip).limit(min(limit, 1000))  # Cap at 1000 for safety
    query = query.order_by(Order.created_at.desc())  # Most recent first

    try:
        result = await db.execute(query)
        orders = result.scalars().all()

        # Convert to response format
        response_orders = []
        for order in orders:
            order_data = {
                "id": order.id,
                "tenant_id": order.tenant_id,
                "user_id": order.user_id,
                "status": order.status,
                "currency": order.currency,
                "total_amount": order.total_amount,
                "items": [
                    {
                        "id": item.id,
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                    }
                    for item in order.items
                ],
                "created_at": order.created_at.isoformat(),
                "updated_at": order.updated_at.isoformat(),
            }
            response_orders.append(OrderResponse(**order_data))

        logger.info(
            "Orders listed",
            tenant_id=tenant_id,
            count=len(response_orders),
            skip=skip,
            limit=limit,
            status_filter=status,
        )

        return response_orders

    except Exception as e:
        logger.error("Order listing failed", tenant_id=tenant_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list orders",
        )


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order: OrderCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """Create a new order with idempotency support."""
    tenant_id = token_data.tenant_id
    user_id = token_data.user_id

    # Check for existing order with same idempotency key
    if idempotency_key:
        try:
            existing_order_result = await db.execute(
                select(Order)
                .where(
                    and_(
                        Order.idempotency_key == idempotency_key,
                        Order.tenant_id == tenant_id,
                    )
                )
                .options(selectinload(Order.items))
            )
            existing_order = existing_order_result.scalar_one_or_none()

            if existing_order and existing_order.response_json:
                logger.info(
                    "Idempotent request - returning cached response",
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    order_id=existing_order.id,
                )
                return OrderResponse(**existing_order.response_json)

        except Exception as e:
            logger.error("Idempotency check failed", error=str(e))

    # Validate and calculate order
    try:
        total_amount = 0
        order_items_data = []

        # Fetch products and calculate total
        for item in order.items:
            try:
                product_id = int(item.sku.split("-")[-1])  # Extract ID from SKU like "PROD-123"
            except (ValueError, IndexError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid SKU format: {item.sku}. Expected format: PROD-{{id}}",
                )

            # Fetch product to get current price
            product_result = await db.execute(
                select(Product).where(
                    and_(
                        Product.id == product_id,
                        Product.tenant_id == tenant_id,
                        Product.is_active,
                    )
                )
            )
            product = product_result.scalar_one_or_none()

            if not product:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Product not found or inactive: {item.sku}",
                )

            line_total = product.price * item.quantity
            total_amount += line_total

            order_items_data.append(
                {
                    "product_id": product.id,
                    "quantity": item.quantity,
                    "unit_price": product.price,
                }
            )

        # Create order and order items in transaction
        db_order = Order(
            tenant_id=tenant_id,
            user_id=user_id,
            total_amount=total_amount,
            idempotency_key=idempotency_key,
        )

        db.add(db_order)
        await db.flush()  # Get order ID

        # Create order items
        db_order_items = []
        for item_data in order_items_data:
            order_item = OrderItem(order_id=db_order.id, **item_data)
            db.add(order_item)
            db_order_items.append(order_item)

        # CRITICAL: Add outbox event for Agent B integration
        outbox_event = Outbox(
            aggregate_id=str(db_order.id),
            aggregate_type="order",
            event_type="order_status",
            payload={
                "event": "order_status",
                "version": "1.0",
                "tenant_id": str(tenant_id),
                "order_id": str(db_order.id),
                "status": "created",
                "ts": datetime.now(timezone.utc).isoformat(),
                "meta": {
                    "reason": "Order created successfully",
                    "total_amount": total_amount,
                    "item_count": len(order_items_data),
                    "user_id": str(user_id),
                },
            },
        )

        db.add(outbox_event)

        # Commit transaction (order + items + outbox atomically)
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
                    "unit_price": item.unit_price,
                }
                for item in db_order_items
            ],
            "created_at": db_order.created_at.isoformat(),
            "updated_at": db_order.updated_at.isoformat(),
        }

        # Store response for idempotency if key was provided
        if idempotency_key:
            db_order.response_json = response_data
            await db.commit()

        logger.info(
            "Order created with outbox event",
            tenant_id=tenant_id,
            order_id=db_order.id,
            total_amount=total_amount,
            idempotency_key=idempotency_key,
        )

        return OrderResponse(**response_data)

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        if "uq_orders_idempotency_key" in str(e):
            # Handle idempotency key conflict
            try:
                existing_order_result = await db.execute(
                    select(Order).where(
                        and_(
                            Order.idempotency_key == idempotency_key,
                            Order.tenant_id == tenant_id,
                        )
                    )
                )
                existing_order = existing_order_result.scalar_one_or_none()

                if existing_order and existing_order.response_json:
                    logger.info(
                        "Idempotency conflict resolved with cached response",
                        tenant_id=tenant_id,
                        idempotency_key=idempotency_key,
                    )
                    return OrderResponse(**existing_order.response_json)
            except Exception:
                pass

        logger.error(
            "Order creation failed - integrity constraint",
            tenant_id=tenant_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order creation conflict - please retry",
        )
    except Exception as e:
        await db.rollback()
        logger.error("Order creation failed", tenant_id=tenant_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create order",
        )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific order by ID."""
    tenant_id = token_data.tenant_id

    try:
        result = await db.execute(
            select(Order)
            .where(and_(Order.id == order_id, Order.tenant_id == tenant_id))
            .options(selectinload(Order.items))
        )
        order = result.scalar_one_or_none()

        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

        response_data = {
            "id": order.id,
            "tenant_id": order.tenant_id,
            "user_id": order.user_id,
            "status": order.status,
            "currency": order.currency,
            "total_amount": order.total_amount,
            "items": [
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                }
                for item in order.items
            ],
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
        }

        logger.info("Order retrieved", tenant_id=tenant_id, order_id=order_id)
        return OrderResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Order retrieval failed", tenant_id=tenant_id, order_id=order_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve order",
        )


@router.put("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: int,
    order: OrderUpdate,
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """Update a specific order."""
    tenant_id = token_data.tenant_id

    try:
        # Fetch existing order
        result = await db.execute(
            select(Order)
            .where(and_(Order.id == order_id, Order.tenant_id == tenant_id))
            .options(selectinload(Order.items))
        )
        db_order = result.scalar_one_or_none()

        if not db_order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

        old_status = db_order.status

        # Update fields that were provided
        update_data = order.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_order, field, value)

        # Create outbox event for status change
        if "status" in update_data and old_status != db_order.status:
            outbox_event = Outbox(
                aggregate_id=str(db_order.id),
                aggregate_type="order",
                event_type="order_status",
                payload={
                    "event": "order_status",
                    "version": "1.0",
                    "tenant_id": str(tenant_id),
                    "order_id": str(db_order.id),
                    "status": db_order.status,
                    "previous_status": old_status,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "meta": {
                        "reason": "Order status updated",
                        "total_amount": db_order.total_amount,
                        "user_id": str(db_order.user_id),
                    },
                },
            )
            db.add(outbox_event)

        await db.commit()
        await db.refresh(db_order)

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
                    "unit_price": item.unit_price,
                }
                for item in db_order.items
            ],
            "created_at": db_order.created_at.isoformat(),
            "updated_at": db_order.updated_at.isoformat(),
        }

        logger.info(
            "Order updated with outbox event",
            tenant_id=tenant_id,
            order_id=order_id,
            old_status=old_status,
            new_status=db_order.status,
        )

        return OrderResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Order update failed", tenant_id=tenant_id, order_id=order_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update order",
        )


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_order(
    order_id: int,
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a specific order."""
    tenant_id = token_data.tenant_id

    try:
        # Fetch existing order
        result = await db.execute(select(Order).where(and_(Order.id == order_id, Order.tenant_id == tenant_id)))
        db_order = result.scalar_one_or_none()

        if not db_order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

        if db_order.status == "cancelled":
            logger.info("Order already cancelled", tenant_id=tenant_id, order_id=order_id)
            return

        old_status = db_order.status
        db_order.status = "cancelled"

        # Create outbox event for cancellation
        outbox_event = Outbox(
            aggregate_id=str(db_order.id),
            aggregate_type="order",
            event_type="order_status",
            payload={
                "event": "order_status",
                "version": "1.0",
                "tenant_id": str(tenant_id),
                "order_id": str(db_order.id),
                "status": "cancelled",
                "previous_status": old_status,
                "ts": datetime.now(timezone.utc).isoformat(),
                "meta": {
                    "reason": "Order cancelled by user",
                    "total_amount": db_order.total_amount,
                    "user_id": str(db_order.user_id),
                },
            },
        )
        db.add(outbox_event)

        await db.commit()

        logger.info(
            "Order cancelled with outbox event",
            tenant_id=tenant_id,
            order_id=order_id,
            previous_status=old_status,
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Order cancellation failed", tenant_id=tenant_id, order_id=order_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel order",
        )
