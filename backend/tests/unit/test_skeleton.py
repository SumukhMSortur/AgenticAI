"""Skeleton unit test for Phase 0 gate verification."""

from backend.app.main import app


def test_app_instantiation() -> None:
    """Verify FastAPI application instance is created with proper metadata."""
    assert app.title == "EcoChain Copilot API"
    assert app.version == "0.1.0"
