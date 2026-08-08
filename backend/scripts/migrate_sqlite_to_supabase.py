"""Copy the Sari-Sari application database from SQLite into Supabase Postgres.

By default, the target must be an empty Postgres database. An explicit replace
mode backs up and atomically replaces only the application tables. The script
never deletes or modifies the SQLite source.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import DateTime, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import Base, build_engine, normalize_database_url
from app.models import Category, Item, PriceHistory, ReceiptLine, ReceiptScan, StockMovement, Supplier, Unit
from app.schema_migrations import prepare_schema


APPLICATION_MODELS = (Category, Unit, Supplier, Item, StockMovement, PriceHistory, ReceiptScan, ReceiptLine)
DEFAULT_SOURCE_URL = f"sqlite:///{(Path(__file__).resolve().parents[1] / 'sari.db').as_posix()}"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_BACKUP_DIR = Path(__file__).resolve().parents[1] / "backups"


def application_tables() -> list[Any]:
    """Return the model tables in dependency-safe insertion order."""
    table_by_name = Base.metadata.tables
    return [table_by_name[model.__tablename__] for model in APPLICATION_MODELS]


def row_values(table: Any, row: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for column in table.columns:
        value = row[column.name]
        if isinstance(column.type, DateTime) and value is not None and column.type.timezone:
            if isinstance(value, datetime) and value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
        values[column.name] = value
    return values


def count_table(session: Session, table: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def validate_source_schema(source_engine: Engine, tables: list[Any]) -> None:
    """Verify the source is current without altering the SQLite database."""
    inspector = inspect(source_engine)
    problems: list[str] = []
    for table in tables:
        if not inspector.has_table(table.name):
            problems.append(f"missing table {table.name}")
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        missing = [column.name for column in table.columns if column.name not in existing]
        if missing:
            problems.append(f"{table.name} missing columns: {', '.join(missing)}")
    if problems:
        raise RuntimeError(
            "The SQLite source schema is older than the application models. "
            "Start the app once against SQLite to apply additive migrations, then retry. "
            + "; ".join(problems)
        )


def ensure_target_empty(target_engine: Engine, tables: list[Any]) -> None:
    with Session(target_engine) as session:
        existing = {table.name: count_table(session, table) for table in tables}
    non_empty = {name: count for name, count in existing.items() if count}
    if non_empty:
        formatted = ", ".join(f"{name}={count}" for name, count in non_empty.items())
        raise RuntimeError(
            f"Refusing to migrate into a non-empty target ({formatted}). "
            "Use a fresh Supabase project or clear only the Sari-Sari application tables first."
        )


def harden_target(session: Session, tables: list[Any]) -> None:
    """Keep public-schema tables private from Supabase Data API roles by default."""
    for table in tables:
        session.execute(text(f'ALTER TABLE public."{table.name}" ENABLE ROW LEVEL SECURITY'))
    available_roles = set(session.scalars(text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")).all())
    for role in sorted(available_roles):
        for table in tables:
            session.execute(text(f'REVOKE ALL ON TABLE public."{table.name}" FROM {role}'))


def copy_rows(
    source_engine: Engine,
    target_engine: Engine,
    tables: list[Any],
    batch_size: int,
    source_counts: dict[str, int],
    enable_rls: bool,
    replace_target: bool = False,
) -> dict[str, int]:
    copied: dict[str, int] = {}
    with Session(source_engine) as source, Session(target_engine) as target:
        with target.begin():
            if replace_target:
                for table in reversed(tables):
                    target.execute(table.delete())
            for table in tables:
                batch: list[dict[str, Any]] = []
                count = 0
                for row in source.execute(select(table)).mappings():
                    batch.append(row_values(table, row))
                    if len(batch) >= batch_size:
                        target.execute(table.insert(), batch)
                        count += len(batch)
                        batch.clear()
                if batch:
                    target.execute(table.insert(), batch)
                    count += len(batch)
                copied[table.name] = count
            target_counts = {table.name: count_table(target, table) for table in tables}
            if target_counts != source_counts:
                raise RuntimeError(
                    f"Target verification failed; transaction rolled back. source={source_counts}, target={target_counts}"
                )
            if enable_rls:
                harden_target(target, tables)
    return copied


def backup_target(target_engine: Engine, tables: list[Any]) -> Path:
    """Create a restorable SQLite snapshot before replacing target rows."""
    DEFAULT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = DEFAULT_BACKUP_DIR / f"supabase-before-migration-{timestamp}.db"
    backup_engine = build_engine(f"sqlite:///{backup_path.as_posix()}")
    try:
        prepare_schema(backup_engine)
        with Session(target_engine) as target:
            target_counts = {table.name: count_table(target, table) for table in tables}
        copy_rows(
            target_engine,
            backup_engine,
            tables,
            batch_size=500,
            source_counts=target_counts,
            enable_rls=False,
        )
    finally:
        backup_engine.dispose()
    return backup_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="SQLite source URL (default: backend/sari.db)")
    parser.add_argument(
        "--target",
        help="Supabase Postgres URL; defaults to SUPABASE_MIGRATION_DATABASE_URL, then DATABASE_URL",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Environment file to load (default: project .env; use an empty value to disable)",
    )
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per insert batch (default: 500)")
    parser.add_argument("--check-only", action="store_true", help="Validate URLs, connectivity, and source rows without writing")
    parser.add_argument(
        "--replace-target",
        action="store_true",
        help="Back up, then atomically replace rows in only the Sari application tables",
    )
    parser.add_argument(
        "--skip-rls-hardening",
        action="store_true",
        help="Do not enable RLS and revoke anon/authenticated access on migrated public tables",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)

    source_url = args.source or os.getenv("SOURCE_DATABASE_URL") or DEFAULT_SOURCE_URL
    target_url = args.target or os.getenv("SUPABASE_MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not target_url:
        raise SystemExit("Set DATABASE_URL to your Supabase Postgres connection string before migrating.")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be greater than zero.")

    normalized_target_url = normalize_database_url(target_url)
    if not normalized_target_url.startswith("postgresql+psycopg://"):
        raise SystemExit("The migration target must be a PostgreSQL/Supabase connection string.")

    source_engine = build_engine(source_url)
    target_engine = build_engine(normalized_target_url)
    tables = application_tables()

    validate_source_schema(source_engine, tables)

    with Session(source_engine) as source:
        source_counts = {table.name: count_table(source, table) for table in tables}
    print("Source rows:")
    for table in tables:
        print(f"  {table.name}: {source_counts[table.name]}")

    with target_engine.connect() as connection:
        connection.execute(select(1))
    if args.check_only:
        print("Source schema and Supabase connectivity checks passed; no target changes were made.")
        return 0

    prepare_schema(target_engine)
    backup_path: Path | None = None
    if args.replace_target:
        backup_path = backup_target(target_engine, tables)
    else:
        ensure_target_empty(target_engine, tables)
    copied = copy_rows(
        source_engine,
        target_engine,
        tables,
        args.batch_size,
        source_counts,
        enable_rls=not args.skip_rls_hardening,
        replace_target=args.replace_target,
    )
    print("Copied rows:")
    for table in tables:
        print(f"  {table.name}: {copied[table.name]}")
    print("Target counts match the source.")
    if backup_path:
        print(f"Previous target rows were backed up to {backup_path}.")
    if not args.skip_rls_hardening:
        print("RLS enabled; anon and authenticated roles have no direct table grants.")
    print("Supabase migration completed without modifying the SQLite source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
