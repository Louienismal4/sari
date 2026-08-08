from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import relationship

from .db import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    name = Column(String(80), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    items = relationship("Item", back_populates="category")


class Unit(Base):
    __tablename__ = "units"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    name = Column(String(50), nullable=False, unique=True)
    abbreviation = Column(String(12), nullable=False)
    allows_decimal = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    items = relationship("Item", foreign_keys="Item.unit_id", back_populates="unit")
    selling_items = relationship("Item", foreign_keys="Item.selling_unit_id", back_populates="selling_unit")


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    name = Column(String(120), nullable=False, unique=True)
    contact_person = Column(String(120), nullable=True)
    phone = Column(String(40), nullable=True)
    email = Column(String(160), nullable=True)
    address = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    items = relationship("Item", back_populates="primary_supplier")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        Index("ix_items_active_name", "is_active", "name"),
        CheckConstraint("units_per_purchase_unit > 0", name="ck_items_units_per_purchase_unit_positive"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    item_code = Column(String(40), nullable=False, unique=True, index=True)
    name = Column(String(160), nullable=False, index=True)
    category_id = Column(Uuid(as_uuid=False), ForeignKey("categories.id"), nullable=False, index=True)
    unit_id = Column(Uuid(as_uuid=False), ForeignKey("units.id"), nullable=False, index=True)
    selling_unit_id = Column(Uuid(as_uuid=False), ForeignKey("units.id"), nullable=False, index=True)
    units_per_purchase_unit = Column(Numeric(12, 3), nullable=False, default=Decimal("1"))
    primary_supplier_id = Column(Uuid(as_uuid=False), ForeignKey("suppliers.id"), nullable=True, index=True)
    unit_cost = Column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    markup_percent = Column(Numeric(7, 2), nullable=False, default=Decimal("20"))
    suggested_price = Column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    actual_selling_price = Column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    reorder_level = Column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    category = relationship("Category", back_populates="items")
    unit = relationship("Unit", foreign_keys=[unit_id], back_populates="items")
    selling_unit = relationship("Unit", foreign_keys=[selling_unit_id], back_populates="selling_items")
    primary_supplier = relationship("Supplier", back_populates="items")
    movements = relationship("StockMovement", back_populates="item")
    price_history = relationship("PriceHistory", back_populates="item")


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_stock_movement_idempotency"),
        Index("ix_stock_movements_item_created_at", "item_id", "created_at"),
        Index("ix_stock_movements_created_at", "created_at"),
    )

    id = Column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    item_id = Column(Uuid(as_uuid=False), ForeignKey("items.id"), nullable=False, index=True)
    movement_type = Column(String(30), nullable=False)
    quantity_delta = Column(Numeric(12, 3), nullable=False)
    unit_cost = Column(Numeric(12, 2), nullable=True)
    purchase_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    source = Column(String(40), nullable=False, default="manual")
    reference = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)
    actor = Column(String(120), nullable=False, default="Maria")
    idempotency_key = Column(String(180), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    item = relationship("Item", back_populates="movements")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    item_id = Column(Uuid(as_uuid=False), ForeignKey("items.id"), nullable=False, index=True)
    old_unit_cost = Column(Numeric(12, 2), nullable=False)
    new_unit_cost = Column(Numeric(12, 2), nullable=False)
    old_markup_percent = Column(Numeric(7, 2), nullable=False)
    new_markup_percent = Column(Numeric(7, 2), nullable=False)
    old_suggested_price = Column(Numeric(12, 2), nullable=False)
    new_suggested_price = Column(Numeric(12, 2), nullable=False)
    old_actual_selling_price = Column(Numeric(12, 2), nullable=False)
    new_actual_selling_price = Column(Numeric(12, 2), nullable=False)
    reason = Column(String(180), nullable=False)
    actor = Column(String(120), nullable=False, default="Maria")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    item = relationship("Item", back_populates="price_history")


class ReceiptScan(Base):
    __tablename__ = "receipt_scans"
    __table_args__ = (Index("ix_receipt_scans_created_at", "created_at"),)

    id = Column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    original_filename = Column(String(255), nullable=False)
    image_path = Column(String(500), nullable=True)
    status = Column(String(30), nullable=False, default="WAITING_FOR_SERVICE")
    provider = Column(String(40), nullable=False, default="mock")
    provider_request_id = Column(String(120), nullable=True)
    merchant_name = Column(String(160), nullable=True)
    receipt_number = Column(String(80), nullable=True)
    purchased_at = Column(DateTime(timezone=True), nullable=True)
    currency = Column(String(8), nullable=False, default="PHP")
    total = Column(Numeric(12, 2), nullable=True)
    raw_result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    gateway_error_code = Column(String(60), nullable=True)
    gateway_http_status = Column(Integer, nullable=True)
    image_sha256 = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    lines = relationship("ReceiptLine", back_populates="receipt_scan", cascade="all, delete-orphan")


class ReceiptLine(Base):
    __tablename__ = "receipt_lines"

    id = Column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    receipt_scan_id = Column(Uuid(as_uuid=False), ForeignKey("receipt_scans.id"), nullable=False, index=True)
    raw_text = Column(Text, nullable=False)
    name = Column(String(160), nullable=False)
    unit_id = Column(Uuid(as_uuid=False), ForeignKey("units.id"), nullable=True, index=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_cost = Column(Numeric(12, 2), nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)
    expiry_date = Column(Date, nullable=True)
    confidence = Column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    matched_item_id = Column(Uuid(as_uuid=False), ForeignKey("items.id"), nullable=True, index=True)
    review_status = Column(String(20), nullable=False, default="REVIEW")

    receipt_scan = relationship("ReceiptScan", back_populates="lines")
    unit = relationship("Unit")
    matched_item = relationship("Item")
