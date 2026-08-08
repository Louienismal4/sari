from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OCRReceiptLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    raw_text: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, decimal_places=2)
    line_total: Decimal = Field(ge=0, decimal_places=2)
    confidence: Decimal = Field(ge=0, le=1, decimal_places=4)

    def to_wire(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "name": self.name,
            "quantity": f"{self.quantity:.3f}",
            "unit_cost": f"{self.unit_cost:.2f}",
            "line_total": f"{self.line_total:.2f}",
            "confidence": float(self.confidence),
        }


class OCRReceiptResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(min_length=1, max_length=40)
    provider_request_id: str = Field(min_length=1, max_length=120)
    merchant_name: str | None = Field(default=None, max_length=160)
    receipt_number: str | None = Field(default=None, max_length=80)
    purchased_at: datetime | None = None
    currency: str = Field(default="PHP", min_length=3, max_length=8)
    total: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    lines: list[OCRReceiptLine] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    raw_result: dict | None = None

    def to_wire(self) -> dict:
        return {
            "provider": self.provider,
            "provider_request_id": self.provider_request_id,
            "merchant_name": self.merchant_name,
            "receipt_number": self.receipt_number,
            "purchased_at": self.purchased_at.isoformat() if self.purchased_at else None,
            "currency": self.currency,
            "total": f"{self.total:.2f}" if self.total is not None else None,
            "lines": [line.to_wire() for line in self.lines],
            "warnings": self.warnings,
            "raw_result": self.raw_result,
        }
