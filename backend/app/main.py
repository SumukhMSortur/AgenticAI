"""EcoChain Copilot backend application entrypoint."""

from fastapi import FastAPI

app = FastAPI(
    title="EcoChain Copilot API",
    version="0.1.0",
    description="Enterprise multi-agent supply-chain compliance system",
)


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Basic health check endpoint."""
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz() -> dict[str, str]:
    """Readiness check endpoint."""
    return {"status": "ready"}
