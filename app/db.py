from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    """One database session per request. Endpoints commit explicitly; anything else is rolled back."""
    with SessionLocal() as session:
        yield session
