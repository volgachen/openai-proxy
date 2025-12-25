import json
from typing import Any, AsyncGenerator

import httpx
import tiktoken
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import get_settings
from database import get_db, User, UsageLog
from models import ChatCompletionRequest, CompletionRequest

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible"])
settings = get_settings()


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Count tokens in text using tiktoken."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def count_message_tokens(messages: list, model: str = "gpt-4") -> int:
    """Count tokens in chat messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        if isinstance(content, str):
            total += count_tokens(content, model)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += count_tokens(part.get("text", ""), model)
    return total


async def log_usage(
    db: AsyncSession,
    user: User,
    model: str,
    input_tokens: int,
    output_tokens: int,
):
    """Log token usage to database."""
    usage_log = UsageLog(
        user_id=user.id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(usage_log)
    await db.commit()


async def proxy_request(
    method: str,
    path: str,
    body: dict,
    stream: bool = False,
) -> httpx.Response:
    """Proxy request to OpenAI backend."""
    url = f"{settings.openai_backend_url.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        if stream:
            return await client.stream(method, url, json=body, headers=headers)
        return await client.request(method, url, json=body, headers=headers)


async def stream_response(
    response: httpx.Response,
    db: AsyncSession,
    user: User,
    model: str,
    input_tokens: int,
) -> AsyncGenerator[bytes, None]:
    """Stream response and count output tokens."""
    output_text = ""

    async with response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data.strip() == "[DONE]":
                    yield line.encode() + b"\n\n"
                    break
                try:
                    chunk = json.loads(data)
                    choices = chunk.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            output_text += content
                except json.JSONDecodeError:
                    pass
                yield line.encode() + b"\n\n"
            elif line:
                yield line.encode() + b"\n"

    output_tokens = count_tokens(output_text, model)
    await log_usage(db, user, model, input_tokens, output_tokens)


@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Proxy chat completions to OpenAI."""
    model = request.model
    messages = [m.model_dump(exclude_none=True) for m in request.messages]
    input_tokens = count_message_tokens(messages, model)

    body = request.model_dump(exclude_none=True)
    body["messages"] = messages

    if request.stream:
        async with httpx.AsyncClient(timeout=120.0) as client:
            url = f"{settings.openai_backend_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            }
            response = await client.send(
                client.build_request("POST", url, json=body, headers=headers),
                stream=True,
            )
            return StreamingResponse(
                stream_response(response, db, user, model, input_tokens),
                media_type="text/event-stream",
            )
    else:
        response = await proxy_request("POST", "/v1/chat/completions", body)
        result = response.json()

        output_tokens = 0
        if "usage" in result:
            output_tokens = result["usage"].get("completion_tokens", 0)
            input_tokens = result["usage"].get("prompt_tokens", input_tokens)
        else:
            choices = result.get("choices", [])
            for choice in choices:
                content = choice.get("message", {}).get("content", "")
                if content:
                    output_tokens += count_tokens(content, model)

        await log_usage(db, user, model, input_tokens, output_tokens)
        return JSONResponse(content=result, status_code=response.status_code)


@router.post("/completions")
async def completions(
    request: CompletionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Proxy legacy completions to OpenAI."""
    model = request.model
    prompt = request.prompt

    if isinstance(prompt, str):
        input_tokens = count_tokens(prompt, model)
    elif isinstance(prompt, list):
        input_tokens = sum(count_tokens(p, model) if isinstance(p, str) else 0 for p in prompt)
    else:
        input_tokens = 0

    body = request.model_dump(exclude_none=True)

    if request.stream:
        async with httpx.AsyncClient(timeout=120.0) as client:
            url = f"{settings.openai_backend_url.rstrip('/')}/v1/completions"
            headers = {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            }
            response = await client.send(
                client.build_request("POST", url, json=body, headers=headers),
                stream=True,
            )
            return StreamingResponse(
                stream_response(response, db, user, model, input_tokens),
                media_type="text/event-stream",
            )
    else:
        response = await proxy_request("POST", "/v1/completions", body)
        result = response.json()

        output_tokens = 0
        if "usage" in result:
            output_tokens = result["usage"].get("completion_tokens", 0)
            input_tokens = result["usage"].get("prompt_tokens", input_tokens)
        else:
            choices = result.get("choices", [])
            for choice in choices:
                text = choice.get("text", "")
                if text:
                    output_tokens += count_tokens(text, model)

        await log_usage(db, user, model, input_tokens, output_tokens)
        return JSONResponse(content=result, status_code=response.status_code)


@router.get("/models")
async def list_models(
    user: User = Depends(get_current_user),
):
    """Proxy models list to OpenAI."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{settings.openai_backend_url.rstrip('/')}/v1/models"
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        response = await client.get(url, headers=headers)
        return JSONResponse(content=response.json(), status_code=response.status_code)
