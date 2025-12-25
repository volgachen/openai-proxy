import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, User, UsageLog
from models import (
    GenKeyRequest,
    GenKeyResponse,
    ListUsersResponse,
    UserInfo,
    ListCostsResponse,
    UserCost,
    ForbidKeyRequest,
    ForbidKeyResponse,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


def generate_api_key() -> str:
    """Generate a random API key."""
    return f"llmp-{secrets.token_hex(32)}"


@router.post("/gen_key", response_model=GenKeyResponse)
async def gen_key(
    request: GenKeyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate a new API key for a username."""
    result = await db.execute(select(User).where(User.username == request.username))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail=f"User '{request.username}' already exists",
        )

    api_key = generate_api_key()
    user = User(username=request.username, api_key=api_key)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return GenKeyResponse(username=user.username, api_key=user.api_key)


@router.get("/list_users", response_model=ListUsersResponse)
async def list_users(
    db: AsyncSession = Depends(get_db),
):
    """List all users."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()

    return ListUsersResponse(
        users=[
            UserInfo(
                id=user.id,
                username=user.username,
                api_key=user.api_key,
                created_at=user.created_at,
                is_active=user.is_active,
            )
            for user in users
        ]
    )


@router.get("/list_costs", response_model=ListCostsResponse)
async def list_costs(
    db: AsyncSession = Depends(get_db),
):
    """List token usage costs per user."""
    query = (
        select(
            User.username,
            func.coalesce(func.sum(UsageLog.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(UsageLog.output_tokens), 0).label("total_output_tokens"),
            func.coalesce(func.sum(UsageLog.cached_tokens), 0).label("total_cached_tokens"),
            func.count(UsageLog.id).label("total_requests"),
        )
        .outerjoin(UsageLog, User.id == UsageLog.user_id)
        .group_by(User.id, User.username)
        .order_by(User.username)
    )

    result = await db.execute(query)
    rows = result.all()

    return ListCostsResponse(
        costs=[
            UserCost(
                username=row.username,
                total_input_tokens=row.total_input_tokens,
                total_output_tokens=row.total_output_tokens,
                total_cached_tokens=row.total_cached_tokens,
                total_requests=row.total_requests,
            )
            for row in rows
        ]
    )


@router.post("/forbid_key", response_model=ForbidKeyResponse)
async def forbid_key(
    request: ForbidKeyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Disable a user's API key by username or api_key."""
    if not request.username and not request.api_key:
        raise HTTPException(
            status_code=400,
            detail="Either username or api_key must be provided",
        )

    conditions = []
    if request.username:
        conditions.append(User.username == request.username)
    if request.api_key:
        conditions.append(User.api_key == request.api_key)

    result = await db.execute(select(User).where(or_(*conditions)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if not user.is_active:
        return ForbidKeyResponse(
            success=True,
            message=f"User '{user.username}' is already disabled",
        )

    user.is_active = False
    await db.commit()

    return ForbidKeyResponse(
        success=True,
        message=f"User '{user.username}' has been disabled",
    )
