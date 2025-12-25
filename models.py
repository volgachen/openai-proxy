from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel


# Admin API schemas
class GenKeyRequest(BaseModel):
    username: str


class GenKeyResponse(BaseModel):
    username: str
    api_key: str


class UserInfo(BaseModel):
    id: int
    username: str
    api_key: str
    created_at: datetime
    is_active: bool


class ListUsersResponse(BaseModel):
    users: List[UserInfo]


class UserCost(BaseModel):
    username: str
    total_input_tokens: int
    total_output_tokens: int
    total_cached_tokens: int
    total_requests: int


class ListCostsResponse(BaseModel):
    costs: List[UserCost]


class ForbidKeyRequest(BaseModel):
    username: Optional[str] = None
    api_key: Optional[str] = None


class ForbidKeyResponse(BaseModel):
    success: bool
    message: str


# OpenAI compatible schemas
class ChatMessage(BaseModel):
    role: str
    content: Any
    name: Optional[str] = None
    function_call: Optional[dict] = None
    tool_calls: Optional[List[dict]] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    stream: Optional[bool] = False
    stop: Optional[Any] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[dict] = None
    user: Optional[str] = None
    functions: Optional[List[dict]] = None
    function_call: Optional[Any] = None
    tools: Optional[List[dict]] = None
    tool_choice: Optional[Any] = None
    response_format: Optional[dict] = None
    seed: Optional[int] = None

    class Config:
        extra = "allow"


class CompletionRequest(BaseModel):
    model: str
    prompt: Any
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    stream: Optional[bool] = False
    logprobs: Optional[int] = None
    stop: Optional[Any] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    best_of: Optional[int] = None
    logit_bias: Optional[dict] = None
    user: Optional[str] = None

    class Config:
        extra = "allow"
