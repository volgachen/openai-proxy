import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, User, UsageLog
from models import (
    GenKeyRequest,
    GenKeyResponse,
    ListUsersResponse,
    UserInfo,
    ListCostsResponse,
    UserCost,
    ModelCost,
    ForbidKeyRequest,
    ForbidKeyResponse,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


def generate_api_key() -> str:
    """Generate a random API key."""
    return f"llmp-{secrets.token_hex(32)}"


def normalize_timestamp(timestamp: Optional[datetime]) -> Optional[datetime]:
    """Normalize timestamps to naive UTC for database filtering."""
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp
    return timestamp.astimezone(timezone.utc).replace(tzinfo=None)


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
    start_time: Optional[datetime] = Query(
        None,
        description="Filter usage logs from this time (inclusive, ISO 8601).",
    ),
    end_time: Optional[datetime] = Query(
        None,
        description="Filter usage logs up to this time (inclusive, ISO 8601).",
    ),
    last_hours: Optional[int] = Query(
        None,
        ge=1,
        description="Convenience window in hours; cannot be combined with start_time/end_time.",
    ),
    by_model: bool = Query(
        False,
        description="Include per-model breakdown for each user.",
    ),
):
    """List token usage costs per user."""
    start_time = normalize_timestamp(start_time)
    end_time = normalize_timestamp(end_time)

    if last_hours is not None:
        if start_time or end_time:
            raise HTTPException(
                status_code=400,
                detail="last_hours cannot be combined with start_time/end_time",
            )
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=last_hours)

    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=400,
            detail="start_time must be earlier than end_time",
        )

    join_conditions = [User.id == UsageLog.user_id]
    if start_time:
        join_conditions.append(UsageLog.timestamp >= start_time)
    if end_time:
        join_conditions.append(UsageLog.timestamp <= end_time)

    query = (
        select(
            User.username,
            func.coalesce(func.sum(UsageLog.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(UsageLog.output_tokens), 0).label("total_output_tokens"),
            func.coalesce(func.sum(UsageLog.cached_tokens), 0).label("total_cached_tokens"),
            func.count(UsageLog.id).label("total_requests"),
        )
        .outerjoin(UsageLog, and_(*join_conditions))
        .group_by(User.id, User.username)
        .order_by(User.username)
    )

    result = await db.execute(query)
    rows = result.all()

    model_costs_by_user: Dict[str, List[ModelCost]] = {}
    if by_model:
        model_query = (
            select(
                User.username,
                UsageLog.model,
                func.coalesce(func.sum(UsageLog.input_tokens), 0).label("total_input_tokens"),
                func.coalesce(func.sum(UsageLog.output_tokens), 0).label("total_output_tokens"),
                func.coalesce(func.sum(UsageLog.cached_tokens), 0).label("total_cached_tokens"),
                func.count(UsageLog.id).label("total_requests"),
            )
            .join(UsageLog, and_(*join_conditions))
            .group_by(User.id, User.username, UsageLog.model)
            .order_by(User.username, UsageLog.model)
        )
        model_result = await db.execute(model_query)
        model_rows = model_result.all()
        for row in model_rows:
            model_costs_by_user.setdefault(row.username, []).append(
                ModelCost(
                    model=row.model,
                    total_input_tokens=row.total_input_tokens,
                    total_output_tokens=row.total_output_tokens,
                    total_cached_tokens=row.total_cached_tokens,
                    total_requests=row.total_requests,
                )
            )

    return ListCostsResponse(
        costs=[
            UserCost(
                username=row.username,
                total_input_tokens=row.total_input_tokens,
                total_output_tokens=row.total_output_tokens,
                total_cached_tokens=row.total_cached_tokens,
                total_requests=row.total_requests,
                model_costs=model_costs_by_user.get(row.username, []) if by_model else None,
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
