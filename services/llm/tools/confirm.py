"""
Confirm Tool

Tool for confirming user actions and orders.
Handles order confirmation, cancellation, and modification approvals.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List

from .base import BaseTool, ToolError


class ConfirmTool(BaseTool):
    """Tool for confirming user actions and orders."""

    @property
    def name(self) -> str:
        return "confirm"

    @property
    def description(self) -> str:
        return "Confirm user actions such as placing, canceling, or modifying orders"

    def get_schema(self) -> Dict[str, Any]:
        """Return OpenAI function schema."""
        return {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "place_order",
                        "cancel_order",
                        "modify_order",
                        "apply_discount",
                        "remove_item",
                        "add_item",
                    ],
                    "description": "Action to confirm with the user",
                },
                "details": {
                    "type": "object",
                    "description": "Action-specific details",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "Order identifier",
                        },
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "quantity": {"type": "integer", "minimum": 1},
                                    "price": {"type": "number", "minimum": 0},
                                },
                            },
                            "description": "Order items",
                        },
                        "total": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Order total amount",
                        },
                        "delivery_address": {
                            "type": "string",
                            "description": "Delivery address",
                        },
                        "estimated_delivery": {
                            "type": "string",
                            "description": "Estimated delivery time",
                        },
                        "payment_method": {
                            "type": "string",
                            "description": "Payment method",
                        },
                    },
                },
                "require_confirmation": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to require explicit user confirmation",
                },
            },
        }

    def validate_args(self, **kwargs) -> Dict[str, Any]:
        """Validate confirmation arguments."""
        action = kwargs.get("action")
        details = kwargs.get("details", {})

        if not action:
            raise ToolError("Action is required for confirmation")

        # Validate action-specific requirements
        if action in ["cancel_order", "modify_order"] and not details.get("order_id"):
            raise ToolError(f"Order ID is required for {action}")

        if action == "place_order":
            if not details.get("items") or len(details["items"]) == 0:
                raise ToolError("Items are required for placing an order")
            if not details.get("total") or details["total"] <= 0:
                raise ToolError("Valid total amount is required for placing an order")

        return kwargs

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute confirmation process.

        Args:
            action: Action to confirm
            details: Action-specific details
            require_confirmation: Whether explicit confirmation is needed

        Returns:
            Dict with confirmation details and next steps
        """
        action = kwargs["action"]
        details = kwargs.get("details", {})
        require_confirmation = kwargs.get("require_confirmation", True)

        # Generate confirmation based on action type
        confirmation_data = self._generate_confirmation(action, details)

        # Add timestamp and tracking
        confirmation_data.update(
            {
                "confirmation_id": f"confirm_{int(datetime.now().timestamp())}",
                "timestamp": datetime.now().isoformat(),
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "requires_user_approval": require_confirmation,
                "context": {
                    "tool_execution": {
                        "tool_name": "confirm",
                        "action_type": action,
                        "tenant_context": self.tenant_id,
                        "user_context": self.user_id,
                        "timestamp": datetime.now().isoformat(),
                    },
                    "business_context": {
                        "confirmation_workflow": f"{action} confirmation initiated",
                        "approval_required": require_confirmation,
                        "processing_steps": self._get_processing_steps(action, details),
                    },
                    "customer_guidance": self._get_customer_guidance(action, details),
                },
            }
        )

        return confirmation_data

    def _generate_confirmation(self, action: str, details: Dict[str, Any]) -> Dict[str, Any]:
        """Generate action-specific confirmation data."""

        if action == "place_order":
            return self._confirm_place_order(details)
        elif action == "cancel_order":
            return self._confirm_cancel_order(details)
        elif action == "modify_order":
            return self._confirm_modify_order(details)
        elif action == "apply_discount":
            return self._confirm_apply_discount(details)
        elif action == "remove_item":
            return self._confirm_remove_item(details)
        elif action == "add_item":
            return self._confirm_add_item(details)
        else:
            raise ToolError(f"Unsupported confirmation action: {action}")

    def _confirm_place_order(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Generate order placement confirmation."""
        items = details.get("items", [])
        total = details.get("total", 0)
        delivery_address = details.get("delivery_address", "Current address")
        payment_method = details.get("payment_method", "Default payment method")

        # Calculate estimated delivery time (mock)
        estimated_delivery = (datetime.now() + timedelta(minutes=30)).strftime("%I:%M %p")

        return {
            "action": "place_order",
            "message": f"Ready to place your order of {len(items)} items for ${total:.2f}",
            "order_summary": {
                "items": items,
                "item_count": len(items),
                "total": total,
                "delivery_address": delivery_address,
                "estimated_delivery": estimated_delivery,
                "payment_method": payment_method,
            },
            "confirmation_message": (
                f"Please confirm: Place order for ${total:.2f} "
                f"with delivery to {delivery_address} by {estimated_delivery}?"
            ),
            "next_steps": [
                "User confirms or declines the order",
                "If confirmed, process payment",
                "Send order to kitchen",
                "Provide order tracking details",
            ],
        }

    def _confirm_cancel_order(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Generate order cancellation confirmation."""
        order_id = details.get("order_id")

        # Mock order lookup
        mock_order = {
            "id": order_id,
            "status": "confirmed",
            "total": 28.50,
            "estimated_delivery": "7:30 PM",
        }

        return {
            "action": "cancel_order",
            "message": f"Request to cancel order {order_id}",
            "order_details": mock_order,
            "cancellation_policy": {
                "refund_eligible": True,
                "refund_amount": mock_order["total"],
                "processing_time": "3-5 business days",
            },
            "confirmation_message": (
                f"Are you sure you want to cancel order {order_id} for ${mock_order['total']:.2f}? "
                f"You will receive a full refund in 3-5 business days."
            ),
            "next_steps": [
                "User confirms cancellation",
                "Process refund",
                "Notify kitchen to stop preparation",
                "Send cancellation confirmation email",
            ],
        }

    def _confirm_modify_order(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Generate order modification confirmation."""
        order_id = details.get("order_id")

        return {
            "action": "modify_order",
            "message": f"Request to modify order {order_id}",
            "modification_options": [
                "Add items to existing order",
                "Remove items from order",
                "Change delivery address",
                "Update delivery time",
                "Modify special instructions",
            ],
            "confirmation_message": f"What would you like to modify about order {order_id}?",
            "next_steps": [
                "Specify modification details",
                "Calculate price difference",
                "Confirm changes with user",
                "Update order in system",
            ],
        }

    def _confirm_apply_discount(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Generate discount application confirmation."""
        return {
            "action": "apply_discount",
            "message": "Ready to apply discount to your order",
            "confirmation_message": "Confirm applying this discount to your current order?",
            "next_steps": [
                "User confirms discount application",
                "Update order total",
                "Apply discount code to order",
            ],
        }

    def _confirm_remove_item(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Generate item removal confirmation."""
        return {
            "action": "remove_item",
            "message": "Request to remove item from order",
            "confirmation_message": "Confirm removing this item from your order?",
            "next_steps": [
                "User confirms item removal",
                "Update order total",
                "Remove item from order",
            ],
        }

    def _confirm_add_item(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Generate item addition confirmation."""
        return {
            "action": "add_item",
            "message": "Request to add item to order",
            "confirmation_message": "Confirm adding this item to your order?",
            "next_steps": [
                "User confirms item addition",
                "Update order total",
                "Add item to order",
            ],
        }

    def _get_processing_steps(self, action: str, details: Dict[str, Any]) -> List[str]:
        """Get processing steps for the action."""

        steps_map = {
            "place_order": [
                "Validate order details and availability",
                "Process payment authorization",
                "Send order to kitchen for preparation",
                "Generate order confirmation and tracking",
            ],
            "cancel_order": [
                "Verify order is cancellable",
                "Process refund authorization",
                "Notify kitchen to stop preparation",
                "Send cancellation confirmation",
            ],
            "modify_order": [
                "Check modification feasibility",
                "Calculate price adjustments",
                "Update order in system",
                "Confirm changes with customer",
            ],
        }

        return steps_map.get(
            action,
            [
                "Process customer request",
                "Validate business rules",
                "Execute action",
                "Provide confirmation",
            ],
        )

    def _get_customer_guidance(self, action: str, details: Dict[str, Any]) -> List[str]:
        """Get customer guidance for the action."""

        guidance_map = {
            "place_order": [
                "Please review your order details carefully",
                "Ensure delivery address is correct",
                "Payment will be processed upon confirmation",
                "You'll receive order tracking information",
            ],
            "cancel_order": [
                "Cancellation may not be possible if preparation has started",
                "Refunds typically process within 3-5 business days",
                "You'll receive cancellation confirmation via email",
                "Contact support for urgent cancellation requests",
            ],
            "modify_order": [
                "Order modifications have a 5-minute window",
                "Price changes will be calculated automatically",
                "Complex changes may require order cancellation and re-placing",
                "Kitchen will be notified of any modifications",
            ],
        }

        return guidance_map.get(
            action,
            [
                "Please confirm your request",
                "Review all details before proceeding",
                "Contact support if you need assistance",
            ],
        )
