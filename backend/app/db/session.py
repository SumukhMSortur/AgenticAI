"""Database session and engine setup."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import settings

# SQLite or PostgreSQL depending on environment / settings
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """Dependency for yielding a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
