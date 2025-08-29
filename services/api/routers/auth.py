from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.database import get_db
from packages.db.models import User
from packages.security.auth import AuthService, get_current_active_user
from packages.security.jwt import jwt_manager

router = APIRouter()
security = HTTPBearer()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: int
    user_id: int
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str | None
    tenant_id: int
    is_active: bool
    is_superuser: bool

    class Config:
        from_attributes = True


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT token."""
    # Authenticate user
    user = await AuthService.authenticate_user(db, request.email, request.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user roles
    roles = AuthService.get_user_roles(user)

    # Create access token
    access_token = jwt_manager.create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email, roles=roles
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        tenant_id=user.tenant_id,
        user_id=user.id,
        expires_in=jwt_manager.access_token_expire_minutes * 60,  # Convert to seconds
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Refresh JWT token."""
    # Verify refresh token
    token_data = jwt_manager.verify_refresh_token(request.refresh_token)

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    # Get user from database
    user = await AuthService.get_user_by_id(
        db, user_id=token_data["user_id"], tenant_id=token_data["tenant_id"]
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Get user roles
    roles = AuthService.get_user_roles(user)

    # Create new access token
    access_token = jwt_manager.create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email, roles=roles
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        tenant_id=user.tenant_id,
        user_id=user.id,
        expires_in=jwt_manager.access_token_expire_minutes * 60,
    )


@router.post("/logout")
async def logout():
    """Logout user (invalidate token)."""
    # Note: JWT tokens are stateless, so we just return success
    # In a production system, you might want to maintain a blacklist
    # or use shorter-lived tokens with a proper session store
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    """Get current authenticated user information."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        tenant_id=current_user.tenant_id,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
    )
