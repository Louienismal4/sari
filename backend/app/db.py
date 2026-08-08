import os
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker


DEFAULT_DATABASE_URL = "sqlite:///./sari.db"
PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

load_dotenv(PROJECT_ENV_FILE, override=False)


def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def normalize_database_url(database_url: str) -> str:
    """Make Supabase's standard Postgres URL explicit for SQLAlchemy's psycopg driver."""
    value = database_url.strip()
    if value.startswith(("https://", "http://")):
        raise ValueError(
            "DATABASE_URL must be a PostgreSQL connection string from Supabase's Connect panel, "
            "not the project's HTTPS API URL."
        )
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    return value


def build_engine(database_url: str):
    normalized_url = normalize_database_url(database_url)
    url = make_url(normalized_url)
    connect_args = {"check_same_thread": False} if url.drivername.startswith("sqlite") else {}
    engine_options = {"pool_pre_ping": True}

    if url.drivername.startswith("postgresql"):
        host = (url.host or "").lower()
        if (host.endswith(".supabase.co") or host.endswith(".pooler.supabase.com")) and "sslmode" not in url.query:
            url = url.update_query_dict({"sslmode": "require"})
        engine_options.update(
            pool_size=env_int("DB_POOL_SIZE", 5, minimum=1),
            max_overflow=env_int("DB_MAX_OVERFLOW", 5),
            pool_timeout=env_int("DB_POOL_TIMEOUT_SECONDS", 30, minimum=1),
            pool_recycle=env_int("DB_POOL_RECYCLE_SECONDS", 300, minimum=1),
            pool_use_lifo=True,
        )

    # Supabase transaction pooling does not keep prepared statements tied to a
    # client connection. Psycopg's automatic preparation must be disabled for
    # the transaction-pooler port; direct and session-pooler connections keep
    # the normal driver behavior.
    if url.drivername == "postgresql+psycopg" and url.port == 6543:
        connect_args["prepare_threshold"] = None

    return create_engine(url, connect_args=connect_args, **engine_options)


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL) or DEFAULT_DATABASE_URL)

engine = build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
