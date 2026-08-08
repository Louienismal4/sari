from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ItemCreate(BaseModel):
    item_code: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    category_id: str
    unit_id: str
    selling_unit_id: str | None = None
    units_per_purchase_unit: Decimal = Field(default=Decimal("1"), gt=0, decimal_places=3)
    primary_supplier_id: str | None = None
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    markup_percent: Decimal = Field(default=Decimal("20"), ge=-100, decimal_places=2)
    actual_selling_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    reorder_level: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=3)


class ItemUpdate(BaseModel):
    item_code: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    category_id: str | None = None
    unit_id: str | None = None
    selling_unit_id: str | None = None
    units_per_purchase_unit: Decimal | None = Field(default=None, gt=0, decimal_places=3)
    primary_supplier_id: str | None = None
    unit_cost: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    markup_percent: Decimal | None = Field(default=None, ge=-100, decimal_places=2)
    actual_selling_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    reorder_level: Decimal | None = Field(default=None, ge=0, decimal_places=3)
    is_active: bool | None = None


class StockMovementCreate(BaseModel):
    item_id: str
    movement_type: str = Field(pattern="^(RECEIPT_IN|MANUAL_IN|MANUAL_OUT|ADJUSTMENT)$")
    quantity: Decimal = Field(gt=0, decimal_places=3)
    quantity_delta: Decimal | None = Field(default=None, decimal_places=3)
    unit_cost: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    purchase_date: date | None = None
    expiry_date: date | None = None
    source: str = Field(default="manual", max_length=40)
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)
    actor: str = Field(default="Maria", max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=180)


class ReceiptLineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    unit_id: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0, decimal_places=3)
    unit_cost: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    line_total: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    expiry_date: date | None = None
    matched_item_id: str | None = None
    review_status: str | None = Field(default=None, pattern="^(REVIEW|READY|IGNORE)$")


class ReceiptScanUpdate(BaseModel):
    purchased_at: datetime | None = None


class HealthResponse(BaseModel):
    status: str
    provider: str
    message: str


class ReceiptConfirmResponse(BaseModel):
    scan_id: str
    status: str
    movements_created: int
    total: Decimal
