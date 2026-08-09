import os

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import Base, engine


_RECEIPT_SCAN_COLUMNS = {
    "attempt_count": ("INTEGER NOT NULL DEFAULT 0", "INTEGER NOT NULL DEFAULT 0"),
    "last_attempt_at": ("DATETIME", "TIMESTAMPTZ"),
    "next_retry_at": ("DATETIME", "TIMESTAMPTZ"),
    "gateway_error_code": ("VARCHAR(60)", "VARCHAR(60)"),
    "gateway_http_status": ("INTEGER", "INTEGER"),
    "image_sha256": ("VARCHAR(64)", "VARCHAR(64)"),
}

_ITEM_COLUMNS = {
    "selling_unit_id": ("VARCHAR(36)", "UUID"),
    "units_per_purchase_unit": ("NUMERIC(12, 3) NOT NULL DEFAULT 1", "NUMERIC(12, 3) NOT NULL DEFAULT 1"),
}

_RECEIPT_LINE_COLUMNS = {
    "unit_id": ("VARCHAR(36)", "UUID"),
    "expiry_date": ("DATE", "DATE"),
}

_STOCK_MOVEMENT_COLUMNS = {
    "purchase_date": ("DATE", "DATE"),
    "expiry_date": ("DATE", "DATE"),
}

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_items_category_id ON items (category_id)",
    "CREATE INDEX IF NOT EXISTS ix_items_unit_id ON items (unit_id)",
    "CREATE INDEX IF NOT EXISTS ix_items_selling_unit_id ON items (selling_unit_id)",
    "CREATE INDEX IF NOT EXISTS ix_items_primary_supplier_id ON items (primary_supplier_id)",
    "CREATE INDEX IF NOT EXISTS ix_items_active_name ON items (is_active, name)",
    "CREATE INDEX IF NOT EXISTS ix_stock_movements_item_created_at ON stock_movements (item_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_stock_movements_created_at ON stock_movements (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_receipt_scans_created_at ON receipt_scans (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_receipt_lines_unit_id ON receipt_lines (unit_id)",
    "CREATE INDEX IF NOT EXISTS ix_receipt_lines_matched_item_id ON receipt_lines (matched_item_id)",
)


def add_missing_columns(connection, table_name: str, columns: dict[str, tuple[str, str]]) -> None:
    existing = {column["name"] for column in inspect(connection).get_columns(table_name)}
    definition_index = 0 if connection.dialect.name == "sqlite" else 1
    for name, definitions in columns.items():
        if name in existing:
            continue
        definition = definitions[definition_index]
        if connection.dialect.name == "sqlite":
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))
        else:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {name} {definition}"))


def prepare_schema(database_engine: Engine = engine) -> None:
    """Create the schema, apply additive changes, and optionally harden Supabase Data API roles."""
    Base.metadata.create_all(bind=database_engine)
    with database_engine.begin() as connection:
        add_missing_columns(connection, "items", _ITEM_COLUMNS)
        connection.execute(text("UPDATE items SET selling_unit_id = unit_id WHERE selling_unit_id IS NULL"))
        harden_supabase = os.getenv("HARDEN_SUPABASE_DATA_API", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if connection.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE items ALTER COLUMN selling_unit_id SET NOT NULL"))
            connection.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'items_selling_unit_id_fkey'
                          AND conrelid = 'items'::regclass
                    ) THEN
                        ALTER TABLE items
                        ADD CONSTRAINT items_selling_unit_id_fkey
                        FOREIGN KEY (selling_unit_id) REFERENCES units(id);
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'ck_items_units_per_purchase_unit_positive'
                          AND conrelid = 'items'::regclass
                    ) THEN
                        ALTER TABLE items
                        ADD CONSTRAINT ck_items_units_per_purchase_unit_positive
                        CHECK (units_per_purchase_unit > 0);
                    END IF;
                END $$;
            """))
        add_missing_columns(connection, "receipt_scans", _RECEIPT_SCAN_COLUMNS)
        add_missing_columns(connection, "receipt_lines", _RECEIPT_LINE_COLUMNS)
        add_missing_columns(connection, "stock_movements", _STOCK_MOVEMENT_COLUMNS)
        for statement in _INDEXES:
            connection.execute(text(statement))
        if connection.dialect.name == "postgresql" and harden_supabase:
            table_names = tuple(Base.metadata.tables)
            available_roles = set(
                connection.scalars(
                    text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
                ).all()
            )
            for table_name in table_names:
                connection.execute(text(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'))
                for role in sorted(available_roles):
                    connection.execute(text(f'REVOKE ALL ON TABLE public."{table_name}" FROM {role}'))
