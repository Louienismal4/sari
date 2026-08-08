from hashlib import sha256

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db import Base, build_engine, normalize_database_url
from app.models import Category, Item, StockMovement, Unit
from app.schema_migrations import prepare_schema
from scripts.migrate_sqlite_to_supabase import (
    application_tables,
    copy_rows,
    count_table,
    ensure_target_empty,
    validate_source_schema,
)


def test_supabase_urls_are_normalized_and_api_urls_are_rejected() -> None:
    assert normalize_database_url("postgres://user:pass@example.com:5432/postgres") == (
        "postgresql+psycopg://user:pass@example.com:5432/postgres"
    )
    assert normalize_database_url("postgresql://user:pass@example.com:5432/postgres") == (
        "postgresql+psycopg://user:pass@example.com:5432/postgres"
    )
    with pytest.raises(ValueError, match="HTTPS API URL"):
        normalize_database_url("https://project-ref.supabase.co")


def test_direct_supabase_url_can_use_an_ipv4_session_pooler_without_changing_credentials() -> None:
    normalized = normalize_database_url(
        "postgresql://postgres:secret@db.projectref.supabase.co:5432/postgres",
        "aws-0-ap-northeast-1.pooler.supabase.com",
    )
    database_engine = build_engine(normalized)
    try:
        assert database_engine.url.host == "aws-0-ap-northeast-1.pooler.supabase.com"
        assert database_engine.url.username == "postgres.projectref"
        assert database_engine.url.password == "secret"
    finally:
        database_engine.dispose()
    with pytest.raises(ValueError, match="Supabase pooler hostname"):
        normalize_database_url(
            "postgresql://postgres:secret@db.projectref.supabase.co:5432/postgres",
            "example.com",
        )


def test_supabase_engine_requires_ssl_without_connecting() -> None:
    database_engine = build_engine(
        "postgresql://postgres.project:password@aws-0-region.pooler.supabase.com:5432/postgres"
    )
    try:
        assert database_engine.url.drivername == "postgresql+psycopg"
        assert database_engine.url.query["sslmode"] == "require"
    finally:
        database_engine.dispose()


def test_sqlite_copy_is_verified_and_source_remains_unchanged(tmp_path) -> None:
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source_engine = build_engine(f"sqlite:///{source_path}")
    target_engine = build_engine(f"sqlite:///{target_path}")
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)

    with Session(source_engine) as source:
        category = Category(name="Grocery")
        unit = Unit(name="Piece", abbreviation="pc")
        source.add_all([category, unit])
        source.flush()
        item = Item(
            item_code="ITM-000001",
            name="Test Item",
            category_id=category.id,
            unit_id=unit.id,
            selling_unit_id=unit.id,
            units_per_purchase_unit="1",
            unit_cost="10.00",
            markup_percent="20.00",
            suggested_price="12.00",
            actual_selling_price="12.00",
            reorder_level="2",
        )
        source.add(item)
        source.flush()
        source.add(
            StockMovement(
                item_id=item.id,
                movement_type="RECEIPT_IN",
                quantity_delta="5",
                source="test",
            )
        )
        source.commit()

    tables = application_tables()
    validate_source_schema(source_engine, tables)
    source_digest = sha256(source_path.read_bytes()).hexdigest()
    with Session(source_engine) as source:
        source_counts = {table.name: count_table(source, table) for table in tables}

    ensure_target_empty(target_engine, tables)
    copied = copy_rows(
        source_engine,
        target_engine,
        tables,
        batch_size=2,
        source_counts=source_counts,
        enable_rls=False,
    )

    assert copied == source_counts
    assert sha256(source_path.read_bytes()).hexdigest() == source_digest
    with pytest.raises(RuntimeError, match="non-empty target"):
        ensure_target_empty(target_engine, tables)

    with Session(target_engine) as target:
        target.add(Category(name="Target-only category"))
        target.commit()
    replaced = copy_rows(
        source_engine,
        target_engine,
        tables,
        batch_size=2,
        source_counts=source_counts,
        enable_rls=False,
        replace_target=True,
    )
    assert replaced == source_counts
    with Session(target_engine) as target:
        assert count_table(target, Category.__table__) == source_counts["categories"]


def test_prepare_schema_adds_query_and_foreign_key_indexes(tmp_path) -> None:
    database_engine = build_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    prepare_schema(database_engine)
    item_indexes = {index["name"] for index in inspect(database_engine).get_indexes("items")}
    item_columns = {column["name"] for column in inspect(database_engine).get_columns("items")}
    movement_indexes = {index["name"] for index in inspect(database_engine).get_indexes("stock_movements")}

    assert "ix_items_category_id" in item_indexes
    assert "ix_items_active_name" in item_indexes
    assert "ix_items_selling_unit_id" in item_indexes
    assert {"selling_unit_id", "units_per_purchase_unit"}.issubset(item_columns)
    assert "ix_stock_movements_item_created_at" in movement_indexes
