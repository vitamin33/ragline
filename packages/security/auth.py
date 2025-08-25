import os
from typing import Optional, List

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from packages.db.database import get_db
from packages.db.models import User, Tenant
from .jwt import jwt_manager, TokenData


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token security
security = HTTPBearer()


class AuthService:
    """Authentication service for user login and verification."""
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a plain password against a hashed password."""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def get_password_hash(password: str) -> str:
        """Hash a password."""
        return pwd_context.hash(password)
    
    @staticmethod
    async def authenticate_user(
        db: AsyncSession, 
        email: str, 
        password: str
    ) -> Optional[User]:
        """Authenticate a user by email and password."""
        try:
            # Query user by email with tenant information
            result = await db.execute(
                select(User)
                .options(selectinload(User.tenant))
                .where(User.email == email, User.is_active == True)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                return None
            
            # Verify password
            if not AuthService.verify_password(password, user.hashed_password):
                return None
            
            # Check if tenant is active
            if not user.tenant.is_active:
                return None
            
            return user
            
        except Exception:
            return None
    
    @staticmethod
    async def get_user_by_id(
        db: AsyncSession, 
        user_id: int, 
        tenant_id: Optional[int] = None
    ) -> Optional[User]:
        """Get a user by ID, optionally filtered by tenant."""
        try:
            query = select(User).options(selectinload(User.tenant)).where(
                User.id == user_id,
                User.is_active == True
            )
            
            if tenant_id:
                query = query.where(User.tenant_id == tenant_id)
            
            result = await db.execute(query)
            user = result.scalar_one_or_none()
            
            if user and not user.tenant.is_active:
                return None
                
            return user
            
        except Exception:
            return None
    
    @staticmethod
    def get_user_roles(user: User) -> List[str]:
        """Get user roles. Can be extended based on your role system."""
        roles = []
        
        if user.is_superuser:
            roles.append("superuser")
        
        # Add more role logic here based on your requirements
        # For example, you might have a separate roles table
        roles.append("user")  # Default role
        
        return roles


# Dependency functions for FastAPI

async def get_current_user_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> TokenData:
    """Dependency to get current user from JWT token."""
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        token_data = jwt_manager.verify_token(token)
        
        if token_data is None:
            raise credentials_exception
            
        return token_data
        
    except HTTPException:
        raise credentials_exception
    except Exception:
        raise credentials_exception


async def get_current_user(
    token_data: TokenData = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency to get current user from database."""
    
    user = await AuthService.get_user_by_id(
        db, 
        user_id=token_data.user_id, 
        tenant_id=token_data.tenant_id
    )
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency to get current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Inactive user"
        )
    return current_user


def require_roles(*required_roles: str):
    """Dependency factory to require specific roles."""
    
    def role_checker(token_data: TokenData = Depends(get_current_user_token)) -> TokenData:
        user_roles = set(token_data.roles)
        required_roles_set = set(required_roles)
        
        # Superuser has access to everything
        if "superuser" in user_roles:
            return token_data
        
        # Check if user has any of the required roles
        if not user_roles.intersection(required_roles_set):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of the following roles: {', '.join(required_roles)}"
            )
        
        return token_data
    
    return role_checker


def require_tenant(token_data: TokenData = Depends(get_current_user_token)) -> int:
    """Dependency to get current user's tenant ID."""
    return token_data.tenant_id


class TenantChecker:
    """Helper class to check tenant access."""
    
    @staticmethod
    def check_tenant_access(user_tenant_id: int, resource_tenant_id: int) -> bool:
        """Check if user has access to a tenant's resources."""
        return user_tenant_id == resource_tenant_id
    
    @staticmethod
    def ensure_tenant_access(user_tenant_id: int, resource_tenant_id: int):
        """Ensure user has access to tenant resources or raise exception."""
        if not TenantChecker.check_tenant_access(user_tenant_id, resource_tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: insufficient tenant permissions"
            )


