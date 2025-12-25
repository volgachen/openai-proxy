import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import get_settings
from database import get_db, User, UsageLog
from models import ChatCompletionRequest, CompletionRequest

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible"])
settings = get_settings()

# Global semaphore for concurrency limiting
_semaphore: Optional[asyncio.Semaphore] = None


def get_semaphore() -> Optional[asyncio.Semaphore]:
    """Get or create the global semaphore."""
    global _semaphore
    if _semaphore is None and settings.max_concurrent_requests > 0:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
    return _semaphore


async def log_usage(
    db: AsyncSession,
    user: User,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
):
    """Log token usage to database."""
    usage_log = UsageLog(
        user_id=user.id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )
    db.add(usage_log)
    await db.commit()


async def proxy_request(url: str, headers: dict, body: dict) -> httpx.Response:
    """Send request to backend."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        return await client.post(url, json=body, headers=headers)


@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Proxy chat completions to OpenAI."""
    semaphore = get_semaphore()

    body = request.model_dump(exclude_none=True)
    body["messages"] = [m.model_dump(exclude_none=True) for m in request.messages]
    body["stream"] = False

    url = f"{settings.openai_backend_url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    async def do_request():
        response = await proxy_request(url, headers, body)
        result = response.json()

        usage = result.get("usage", {})
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        await log_usage(
            db, user, request.model,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            cached_tokens,
        )
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={"Content-Type": response.headers.get("Content-Type", "application/json")},
        )

    if semaphore:
        async with semaphore:
            return await do_request()
    return await do_request()


@router.post("/completions")
async def completions(
    request: CompletionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Proxy legacy completions to OpenAI."""
    semaphore = get_semaphore()

    body = request.model_dump(exclude_none=True)
    body["stream"] = False

    url = f"{settings.openai_backend_url.rstrip('/')}/v1/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    async def do_request():
        response = await proxy_request(url, headers, body)
        result = response.json()

        usage = result.get("usage", {})
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        await log_usage(
            db, user, request.model,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            cached_tokens,
        )
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={"Content-Type": response.headers.get("Content-Type", "application/json")},
        )

    if semaphore:
        async with semaphore:
            return await do_request()
    return await do_request()


@router.get("/models")
async def list_models(user: User = Depends(get_current_user)):
    """Proxy models list to OpenAI."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{settings.openai_backend_url.rstrip('/')}/v1/models"
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        response = await client.get(url, headers=headers)
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={"Content-Type": response.headers.get("Content-Type", "application/json")},
        )
