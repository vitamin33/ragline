import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from jose import JWTError, jwt
from pydantic import BaseModel


class TokenData(BaseModel):
    """Token payload data structure."""

    user_id: int
    tenant_id: int
    email: str
    roles: List[str] = []
    exp: Optional[datetime] = None
    iat: Optional[datetime] = None


class JWTManager:
    """JWT token manager for authentication."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
    ):
        self.secret_key = secret_key or os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days

        if self.secret_key == "your-secret-key-change-in-production":
            import warnings

            warnings.warn(
                "Using default JWT secret key! Set JWT_SECRET_KEY environment variable in production.",
                UserWarning,
            )

    def create_access_token(
        self,
        user_id: int,
        tenant_id: int,
        email: str,
        roles: List[str] = None,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a new access token."""
        if roles is None:
            roles = []

        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=self.access_token_expire_minutes)

        now = datetime.now(timezone.utc)

        payload = {
            "sub": str(user_id),  # Subject - user identifier
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "roles": roles,
            "exp": expire,
            "iat": now,  # Issued at
            "type": "access",
        }

        encoded_jwt = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def create_refresh_token(self, user_id: int, tenant_id: int, expires_delta: Optional[timedelta] = None) -> str:
        """Create a new refresh token."""
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(days=self.refresh_token_expire_days)

        now = datetime.now(timezone.utc)

        payload = {
            "sub": str(user_id),
            "user_id": user_id,
            "tenant_id": tenant_id,
            "exp": expire,
            "iat": now,
            "type": "refresh",
        }

        encoded_jwt = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> Optional[TokenData]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Check if token type is access
            token_type = payload.get("type")
            if token_type != "access":
                return None

            # Extract token data
            user_id = payload.get("user_id")
            tenant_id = payload.get("tenant_id")
            email = payload.get("email")
            roles = payload.get("roles", [])
            exp = payload.get("exp")
            iat = payload.get("iat")

            if user_id is None or tenant_id is None:
                return None

            # Convert timestamps
            exp_dt = datetime.fromtimestamp(exp, timezone.utc) if exp else None
            iat_dt = datetime.fromtimestamp(iat, timezone.utc) if iat else None

            return TokenData(
                user_id=user_id,
                tenant_id=tenant_id,
                email=email or "",
                roles=roles,
                exp=exp_dt,
                iat=iat_dt,
            )

        except JWTError:
            return None

    def verify_refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Verify a refresh token and return basic user info."""
        try:
            payload = jwt.decode(refresh_token, self.secret_key, algorithms=[self.algorithm])

            # Check if token type is refresh
            token_type = payload.get("type")
            if token_type != "refresh":
                return None

            user_id = payload.get("user_id")
            tenant_id = payload.get("tenant_id")

            if user_id is None or tenant_id is None:
                return None

            return {"user_id": user_id, "tenant_id": tenant_id}

        except JWTError:
            return None

    def get_token_expiry(self, token: str) -> Optional[datetime]:
        """Get the expiry time of a token without full verification."""
        try:
            # Decode without verification to get expiry
            payload = jwt.get_unverified_claims(token)
            exp = payload.get("exp")
            if exp:
                return datetime.fromtimestamp(exp, timezone.utc)
            return None
        except Exception:
            return None

    def is_token_expired(self, token: str) -> bool:
        """Check if a token is expired."""
        expiry = self.get_token_expiry(token)
        if expiry is None:
            return True
        return datetime.now(timezone.utc) >= expiry


# Global JWT manager instance
jwt_manager = JWTManager()
