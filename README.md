# LLM API Proxy

An OpenAI-compatible API proxy with user management and token usage tracking.

## Features

- **OpenAI-compatible endpoints** - Drop-in replacement for OpenAI API
- **User management** - Generate API keys for users, disable keys
- **Usage tracking** - Track input/output/cached tokens per user
- **Concurrency control** - Limit concurrent requests to protect backend

## Quick Start

### 1. Install dependencies

```bash
cd llm_proxy
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
OPENAI_BACKEND_URL=https://api.openai.com
OPENAI_API_KEY=sk-your-actual-api-key

# Optional
HOST=0.0.0.0
PORT=8000
MAX_CONCURRENT_REQUESTS=500
```

### 3. Run the server

```bash
python main.py
```

Server starts at `http://localhost:8000`

---

## Admin API Reference

Admin endpoints have no authentication (intended for internal use).

### Generate API Key

Create a new user and generate an API key.

```bash
curl -X POST http://localhost:8000/admin/gen_key \
  -H "Content-Type: application/json" \
  -d '{"username": "alice"}'
```

Response:
```json
{
  "username": "alice",
  "api_key": "llmp-a1b2c3d4..."
}
```

### List Users

```bash
curl http://localhost:8000/admin/list_users
```

Response:
```json
{
  "users": [
    {
      "id": 1,
      "username": "alice",
      "api_key": "llmp-a1b2c3d4...",
      "created_at": "2024-01-15T10:30:00",
      "is_active": true
    }
  ]
}
```

### List Costs

Get token usage statistics per user.

```bash
curl http://localhost:8000/admin/list_costs
```

Optional query parameters:
- `last_hours` - Convenience window in hours (cannot be combined with `start_time`/`end_time`)
- `start_time` - ISO 8601 timestamp (inclusive)
- `end_time` - ISO 8601 timestamp (inclusive)
- `by_model` - Include per-model breakdown in each user entry

You should better run it with `... | python -m json.tool`

Examples:
```bash
# Last 24 hours with per-model breakdown
curl "http://localhost:8000/admin/list_costs?last_hours=24&by_model=true" | python -m json.tool

# Explicit time range
curl "http://localhost:8000/admin/list_costs?start_time=2026-02-08T00:00:00Z&end_time=2026-02-09T00:00:00Z"
```

Response:
```json
{
  "costs": [
    {
      "username": "alice",
      "total_input_tokens": 15000,
      "total_output_tokens": 5000,
      "total_cached_tokens": 12000,
      "total_requests": 100,
      "model_costs": [
        {
          "model": "gpt-4.1-mini",
          "total_input_tokens": 12000,
          "total_output_tokens": 4000,
          "total_cached_tokens": 9000,
          "total_requests": 80
        }
      ]
    }
  ]
}
```

**Cost calculation tip**: Cached tokens are 50% cheaper. Actual billable input tokens = `total_input_tokens - (total_cached_tokens * 0.5)`

### Forbid Key

Disable a user's API key.

```bash
# By username
curl -X POST http://localhost:8000/admin/forbid_key \
  -H "Content-Type: application/json" \
  -d '{"username": "alice"}'

# Or by API key
curl -X POST http://localhost:8000/admin/forbid_key \
  -H "Content-Type: application/json" \
  -d '{"api_key": "llmp-a1b2c3d4..."}'
```

---

## OpenAI-Compatible API Reference

These endpoints require authentication via Bearer token (the user's API key).

### Chat Completions

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer llmp-a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4.1-mini",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### Legacy Completions

```bash
curl http://localhost:8000/v1/completions \
  -H "Authorization: Bearer llmp-a1b2c3d4..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo-instruct",
    "prompt": "Say hello"
  }'
```

### List Models

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer llmp-a1b2c3d4..."
```

---

## Using with OpenAI SDK

### Python

```python
from openai import OpenAI

client = OpenAI(
    api_key="llmp-a1b2c3d4...",  # Your proxy API key
    base_url="http://localhost:8000/v1"
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
```

### Node.js

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  apiKey: 'llmp-a1b2c3d4...',
  baseURL: 'http://localhost:8000/v1'
});

const response = await client.chat.completions.create({
  model: 'gpt-4',
  messages: [{ role: 'user', content: 'Hello!' }]
});

console.log(response.choices[0].message.content);
```

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_BACKEND_URL` | `https://api.openai.com` | Backend API URL |
| `OPENAI_API_KEY` | (required) | Your OpenAI API key |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `DATABASE_URL` | `sqlite+aiosqlite:///./llm_proxy.db` | Database connection |
| `MAX_CONCURRENT_REQUESTS` | `500` | Max concurrent requests (0=unlimited) |

---

## Project Structure

```
llm_proxy/
├── main.py           # FastAPI entry point
├── config.py         # Environment configuration
├── database.py       # SQLite models
├── models.py         # Pydantic schemas
├── auth.py           # API key validation
├── proxy.py          # OpenAI proxy endpoints
├── admin.py          # Admin API endpoints
├── requirements.txt  # Dependencies
└── .env              # Configuration (create from .env.example)
```

---

## Database

SQLite database is created automatically at `llm_proxy.db`.

**Tables:**
- `users` - User accounts and API keys
- `usage_logs` - Per-request token usage records

To reset the database, simply delete `llm_proxy.db` and restart the server.
