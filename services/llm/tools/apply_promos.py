"""
Apply Promos Tool

Tool for applying promotional codes and discounts to orders.
Handles validation, eligibility checks, and discount calculations.
"""

from typing import Any, Dict, Optional
from .base import BaseTool, ToolError


class ApplyPromosTool(BaseTool):
    """Tool for applying promotional codes to orders."""
    
    @property
    def name(self) -> str:
        return "apply_promos"
    
    @property
    def description(self) -> str:
        return "Apply promotional codes or discounts to orders"
    
    def get_schema(self) -> Dict[str, Any]:
        """Return OpenAI function schema."""
        return {
            "type": "object",
            "required": ["promo_code"],
            "properties": {
                "promo_code": {
                    "type": "string",
                    "description": "Promotional code to apply (e.g., 'SAVE20', 'WELCOME10')",
                    "minLength": 3,
                    "maxLength": 20
                },
                "order_id": {
                    "type": "string",
                    "description": "Order ID to apply promotion to (if not provided, applies to current cart)"
                },
                "order_total": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Current order total for discount calculation"
                }
            }
        }
    
    def validate_args(self, **kwargs) -> Dict[str, Any]:
        """Validate promo application arguments."""
        promo_code = kwargs.get("promo_code", "").strip().upper()
        
        if not promo_code:
            raise ToolError("Promo code is required")
        
        if len(promo_code) < 3 or len(promo_code) > 20:
            raise ToolError("Promo code must be between 3 and 20 characters")
        
        # Update with normalized promo code
        args = {**kwargs, "promo_code": promo_code}
        
        # Validate order total if provided
        if "order_total" in args and args["order_total"] < 0:
            raise ToolError("Order total must be non-negative")
        
        return args
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute promo code application.
        
        Args:
            promo_code: Promotional code to apply
            order_id: Optional order ID
            order_total: Optional order total for calculation
            
        Returns:
            Dict with promo application result and discount details
        """
        promo_code = kwargs["promo_code"]
        order_id = kwargs.get("order_id")
        order_total = kwargs.get("order_total", 25.00)  # Mock default total
        
        # Mock promo database - in production this would query a database
        mock_promos = {
            "SAVE20": {
                "id": "promo_1",
                "code": "SAVE20",
                "type": "percentage",
                "value": 20.0,
                "min_order": 15.00,
                "max_discount": 50.00,
                "active": True,
                "description": "20% off orders over $15"
            },
            "WELCOME10": {
                "id": "promo_2", 
                "code": "WELCOME10",
                "type": "fixed",
                "value": 10.00,
                "min_order": 20.00,
                "max_discount": 10.00,
                "active": True,
                "description": "$10 off orders over $20"
            },
            "FREESHIP": {
                "id": "promo_3",
                "code": "FREESHIP", 
                "type": "shipping",
                "value": 0.00,
                "min_order": 10.00,
                "max_discount": 9.99,
                "active": True,
                "description": "Free shipping on orders over $10"
            },
            "EXPIRED": {
                "id": "promo_4",
                "code": "EXPIRED",
                "type": "percentage",
                "value": 30.0,
                "min_order": 0.00,
                "max_discount": 100.00,
                "active": False,
                "description": "30% off (expired)"
            }
        }
        
        # Check if promo code exists
        if promo_code not in mock_promos:
            raise ToolError(f"Promo code '{promo_code}' is not valid")
        
        promo = mock_promos[promo_code]
        
        # Check if promo is active
        if not promo["active"]:
            raise ToolError(f"Promo code '{promo_code}' has expired or is no longer active")
        
        # Check minimum order requirement
        if order_total < promo["min_order"]:
            raise ToolError(
                f"Order total ${order_total:.2f} does not meet minimum requirement of ${promo['min_order']:.2f} for promo '{promo_code}'"
            )
        
        # Calculate discount
        discount_amount = 0.0
        
        if promo["type"] == "percentage":
            discount_amount = min(
                order_total * (promo["value"] / 100),
                promo["max_discount"]
            )
        elif promo["type"] == "fixed":
            discount_amount = min(promo["value"], order_total)
        elif promo["type"] == "shipping":
            # Mock shipping cost
            discount_amount = min(5.99, promo["max_discount"])
        
        # Calculate final totals
        discounted_total = max(0, order_total - discount_amount)
        
        result = {
            "success": True,
            "promo_applied": {
                "code": promo_code,
                "description": promo["description"],
                "type": promo["type"],
                "discount_amount": round(discount_amount, 2)
            },
            "order_summary": {
                "order_id": order_id,
                "original_total": round(order_total, 2),
                "discount_amount": round(discount_amount, 2),
                "final_total": round(discounted_total, 2),
                "savings_percentage": round((discount_amount / order_total) * 100, 1) if order_total > 0 else 0
            },
            "message": f"Successfully applied promo code '{promo_code}' for ${discount_amount:.2f} off!"
        }
        
        return result