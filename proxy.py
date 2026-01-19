import asyncio
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from auth import get_current_user
from config import get_settings, get_model_mapping
from database import async_session, User, UsageLog, ErrorLog
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
    user_id: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
):
    """Log token usage to database with short-lived session."""
    async with async_session() as db:
        usage_log = UsageLog(
            user_id=user_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )
        db.add(usage_log)
        await db.commit()


async def log_error(
    user_id: int,
    error_type: str,
    model: str = None,
    error_message: str = None,
    status_code: int = None,
):
    """Log error to database with short-lived session."""
    async with async_session() as db:
        error_log = ErrorLog(
            user_id=user_id,
            model=model,
            error_type=error_type,
            error_message=error_message,
            status_code=status_code,
        )
        db.add(error_log)
        await db.commit()


def map_model_name(model: str) -> str:
    """Map model name using config, return original if no mapping exists."""
    mapping = get_model_mapping()
    return mapping.get(model, model)


async def proxy_request(url: str, headers: dict, body: dict) -> httpx.Response:
    """Send request to backend."""
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        return await client.post(url, json=body, headers=headers)


@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    user: User = Depends(get_current_user),
):
    """Proxy chat completions to OpenAI."""
    semaphore = get_semaphore()
    user_id = user.id  # Capture before session closes
    original_model = request.model
    backend_model = map_model_name(original_model)

    body = request.model_dump(exclude_none=True)
    body["model"] = backend_model
    body["messages"] = [m.model_dump(exclude_none=True) for m in request.messages]
    body["stream"] = False

    url = f"{settings.openai_backend_url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    async def do_request():
        try:
            response = await proxy_request(url, headers, body)
        except httpx.TimeoutException as e:
            await log_error(user_id, "timeout", backend_model, str(e))
            raise
        except httpx.RequestError as e:
            await log_error(user_id, "request_error", backend_model, str(e))
            raise

        # Log error if backend returned error status
        if response.status_code >= 400:
            await log_error(
                user_id, "backend_error", backend_model,
                response.text[:500], response.status_code
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={"Content-Type": response.headers.get("Content-Type", "application/json")},
            )

        try:
            result = response.json()
        except Exception as e:
            await log_error(user_id, "parse_error", backend_model, str(e), response.status_code)
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={"Content-Type": response.headers.get("Content-Type", "application/json")},
            )

        usage = result.get("usage", {})
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        await log_usage(
            user_id, backend_model,  # Log with mapped model name
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
):
    """Proxy legacy completions to OpenAI."""
    semaphore = get_semaphore()
    user_id = user.id  # Capture before session closes
    original_model = request.model
    backend_model = map_model_name(original_model)

    body = request.model_dump(exclude_none=True)
    body["model"] = backend_model
    body["stream"] = False

    url = f"{settings.openai_backend_url.rstrip('/')}/v1/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    async def do_request():
        try:
            response = await proxy_request(url, headers, body)
        except httpx.TimeoutException as e:
            await log_error(user_id, "timeout", backend_model, str(e))
            raise
        except httpx.RequestError as e:
            await log_error(user_id, "request_error", backend_model, str(e))
            raise

        # Log error if backend returned error status
        if response.status_code >= 400:
            await log_error(
                user_id, "backend_error", backend_model,
                response.text[:500], response.status_code
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={"Content-Type": response.headers.get("Content-Type", "application/json")},
            )

        try:
            result = response.json()
        except Exception as e:
            await log_error(user_id, "parse_error", backend_model, str(e), response.status_code)
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={"Content-Type": response.headers.get("Content-Type", "application/json")},
            )

        usage = result.get("usage", {})
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        await log_usage(
            user_id, backend_model,  # Log with mapped model name
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
async def list_models(_: User = Depends(get_current_user)):
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
