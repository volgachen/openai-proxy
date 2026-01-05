from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from admin import router as admin_router
from config import get_settings
from database import init_db, engine
from proxy import router as proxy_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup, checkpoint WAL on shutdown."""
    await init_db()
    yield
    # Checkpoint WAL to main database on graceful shutdown
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))


app = FastAPI(
    title="LLM API Proxy",
    description="OpenAI-compatible LLM API proxy with user management and usage tracking",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(proxy_router)
app.include_router(admin_router)


@app.get("/")
async def root():
    return {"message": "LLM API Proxy is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
