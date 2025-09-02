import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import structlog
from fastapi import HTTPException, Request, status

logger = structlog.get_logger(__name__)


class PIIDetector:
    """PII detection using regex patterns."""

    def __init__(self):
        self.patterns = {
            "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
            "phone_us": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
            "ssn": re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b"),
            "credit_card": re.compile(
                r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3[0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"
            ),
            "ip_address": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
            "date_birth": re.compile(r"\b(?:0[1-9]|1[012])[- /.](0[1-9]|[12][0-9]|3[01])[- /.](19|20)\d\d\b"),
        }

    def detect_pii(self, text: str) -> Dict[str, List[str]]:
        """Detect PII in text and return findings."""
        findings = {}

        for pii_type, pattern in self.patterns.items():
            matches = pattern.findall(text)
            if matches:
                findings[pii_type] = matches

        return findings

    def mask_pii(self, text: str) -> str:
        """Mask PII in text with asterisks."""
        masked_text = text

        for pii_type, pattern in self.patterns.items():
            if pii_type == "email":
                masked_text = pattern.sub(
                    lambda m: m.group(0)[:2] + "*" * (len(m.group(0)) - 4) + m.group(0)[-2:], masked_text
                )
            elif pii_type == "phone_us":
                masked_text = pattern.sub("***-***-****", masked_text)
            elif pii_type == "ssn":
                masked_text = pattern.sub("***-**-****", masked_text)
            elif pii_type == "credit_card":
                masked_text = pattern.sub(lambda m: "*" * 12 + m.group(0)[-4:], masked_text)
            else:
                masked_text = pattern.sub("***", masked_text)

        return masked_text


class ContentModerator:
    """Content moderation using keyword filtering."""

    def __init__(self):
        # Basic profanity and harmful content keywords
        self.blocked_keywords = {
            "hate_speech": [
                "hate",
                "nazi",
                "terrorist",
                "kill",
                "murder",
                "bomb",
                # Add more as needed - this is a basic set
            ],
            "spam": [
                "viagra",
                "casino",
                "lottery",
                "winner",
                "congratulations",
                "click here",
                "free money",
                "earn fast",
            ],
            "inappropriate": [
                "explicit",
                "adult content",
                "nsfw",
                # Add more categories as needed
            ],
        }

    def check_content(self, text: str) -> Dict[str, List[str]]:
        """Check content for policy violations."""
        violations = {}
        text_lower = text.lower()

        for category, keywords in self.blocked_keywords.items():
            found_keywords = []
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    found_keywords.append(keyword)

            if found_keywords:
                violations[category] = found_keywords

        return violations

    def is_safe_content(self, text: str) -> bool:
        """Check if content is safe (no violations)."""
        violations = self.check_content(text)
        return len(violations) == 0


class RateLimiter:
    """Simple in-memory rate limiter for tool execution."""

    def __init__(self):
        self.requests: Dict[str, List[datetime]] = {}
        self.limits = {
            "default": {"requests": 100, "window": 3600},  # 100 requests per hour
            "premium": {"requests": 500, "window": 3600},  # 500 requests per hour
            "enterprise": {"requests": 1000, "window": 3600},  # 1000 requests per hour
        }

    def check_rate_limit(self, tenant_id: str, user_id: str, tier: str = "default") -> bool:
        """Check if request is within rate limits."""
        key = f"{tenant_id}:{user_id}"
        now = datetime.now(timezone.utc)

        # Get rate limit configuration
        limit_config = self.limits.get(tier, self.limits["default"])
        max_requests = limit_config["requests"]
        window_seconds = limit_config["window"]

        # Clean old requests
        if key in self.requests:
            cutoff_time = now.timestamp() - window_seconds
            self.requests[key] = [req_time for req_time in self.requests[key] if req_time.timestamp() > cutoff_time]
        else:
            self.requests[key] = []

        # Check if under limit
        if len(self.requests[key]) >= max_requests:
            return False

        # Add current request
        self.requests[key].append(now)
        return True

    def get_remaining_requests(self, tenant_id: str, user_id: str, tier: str = "default") -> int:
        """Get remaining requests in current window."""
        key = f"{tenant_id}:{user_id}"
        limit_config = self.limits.get(tier, self.limits["default"])
        max_requests = limit_config["requests"]

        current_requests = len(self.requests.get(key, []))
        return max(0, max_requests - current_requests)


class ContentValidator:
    """Main content validation coordinator."""

    def __init__(self):
        self.pii_detector = PIIDetector()
        self.content_moderator = ContentModerator()
        self.rate_limiter = RateLimiter()

        # Validation configuration
        self.config = {
            "strict_pii_blocking": False,  # If True, block any PII
            "log_pii_findings": True,
            "block_unsafe_content": True,
            "enable_rate_limiting": True,
        }

    def validate_content(
        self, text: str, tenant_id: str, user_id: str, operation: str = "general", tier: str = "default"
    ) -> Dict[str, any]:
        """Comprehensive content validation."""
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "pii_detected": {},
            "content_violations": {},
            "rate_limit_ok": True,
            "masked_text": text,
        }

        try:
            # Rate limiting check
            if self.config["enable_rate_limiting"]:
                if not self.rate_limiter.check_rate_limit(tenant_id, user_id, tier):
                    validation_result["valid"] = False
                    validation_result["rate_limit_ok"] = False
                    validation_result["errors"].append("Rate limit exceeded")
                    remaining = self.rate_limiter.get_remaining_requests(tenant_id, user_id, tier)
                    validation_result["warnings"].append(f"Rate limit: {remaining} requests remaining")

            # PII detection
            pii_findings = self.pii_detector.detect_pii(text)
            if pii_findings:
                validation_result["pii_detected"] = pii_findings

                if self.config["log_pii_findings"]:
                    logger.warning(
                        "PII detected in content",
                        tenant_id=tenant_id,
                        operation=operation,
                        pii_types=list(pii_findings.keys()),
                    )

                if self.config["strict_pii_blocking"]:
                    validation_result["valid"] = False
                    validation_result["errors"].append("PII detected in content")
                else:
                    validation_result["warnings"].append("PII detected and masked")
                    validation_result["masked_text"] = self.pii_detector.mask_pii(text)

            # Content moderation
            content_violations = self.content_moderator.check_content(text)
            if content_violations:
                validation_result["content_violations"] = content_violations

                if self.config["block_unsafe_content"]:
                    validation_result["valid"] = False
                    validation_result["errors"].append("Content policy violation")

                    logger.warning(
                        "Content policy violation",
                        tenant_id=tenant_id,
                        operation=operation,
                        violation_types=list(content_violations.keys()),
                    )
                else:
                    validation_result["warnings"].append("Content policy concerns detected")

            return validation_result

        except Exception as e:
            logger.error("Content validation error", tenant_id=tenant_id, operation=operation, error=str(e))

            validation_result["valid"] = False
            validation_result["errors"].append("Content validation failed")
            return validation_result


# Global validator instance
content_validator = ContentValidator()


async def validate_tool_content(request: Request, call_next):
    """Middleware to validate content in tool requests."""

    # Only apply to tool execution endpoints
    if not request.url.path.startswith("/v1/tools/"):
        response = await call_next(request)
        return response

    # Skip non-POST requests (GET for schemas, etc.)
    if request.method != "POST":
        response = await call_next(request)
        return response

    try:
        # Get request body
        body = await request.body()
        if not body:
            response = await call_next(request)
            return response

        import json

        try:
            request_data = json.loads(body)
        except json.JSONDecodeError:
            response = await call_next(request)
            return response

        # Extract text content from parameters
        text_content = ""
        if "parameters" in request_data:
            for key, value in request_data["parameters"].items():
                if isinstance(value, str):
                    text_content += f" {value}"

        if not text_content.strip():
            response = await call_next(request)
            return response

        # Get user context (would normally come from auth middleware)
        tenant_id = "unknown"
        user_id = "unknown"

        # Try to extract from request state if available
        if hasattr(request.state, "token_data"):
            tenant_id = str(request.state.token_data.tenant_id)
            user_id = str(request.state.token_data.user_id)

        # Validate content
        validation = content_validator.validate_content(
            text_content.strip(), tenant_id, user_id, operation="tool_execution"
        )

        if not validation["valid"]:
            logger.warning(
                "Tool content validation failed",
                tenant_id=tenant_id,
                path=request.url.path,
                errors=validation["errors"],
            )

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "content_validation_failed",
                    "message": "Content validation failed",
                    "details": validation["errors"],
                    "warnings": validation["warnings"],
                },
            )

        # Log warnings if any
        if validation["warnings"]:
            logger.info(
                "Tool content validation warnings",
                tenant_id=tenant_id,
                path=request.url.path,
                warnings=validation["warnings"],
            )

        # Continue with request
        response = await call_next(request)
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Content validation middleware error", path=request.url.path, error=str(e))

        # Continue with request on validation errors to avoid blocking
        response = await call_next(request)
        return response
