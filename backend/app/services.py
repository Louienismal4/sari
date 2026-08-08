from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Item, StockMovement


CENT = Decimal("0.01")
THOUSANDTH = Decimal("0.001")


def money(value: Decimal | int | float | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def quantity(value: Decimal | int | float | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(THOUSANDTH, rounding=ROUND_HALF_UP)


def suggested_price(unit_cost: Decimal, markup_percent: Decimal) -> Decimal:
    result = money(unit_cost) * (Decimal("1") + Decimal(str(markup_percent)) / Decimal("100"))
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def selling_unit_cost(purchase_unit_cost: Decimal, units_per_purchase_unit: Decimal) -> Decimal:
    conversion = quantity(units_per_purchase_unit)
    if conversion <= 0:
        raise ValueError("Units per purchase unit must be greater than zero")
    return (money(purchase_unit_cost) / conversion).quantize(CENT, rounding=ROUND_HALF_UP)


def suggested_selling_price(purchase_unit_cost: Decimal, markup_percent: Decimal, units_per_purchase_unit: Decimal) -> Decimal:
    return suggested_price(selling_unit_cost(purchase_unit_cost, units_per_purchase_unit), markup_percent)


def markup_from_selling_price(purchase_unit_cost: Decimal, actual_selling_price: Decimal, units_per_purchase_unit: Decimal) -> Decimal:
    cost = selling_unit_cost(purchase_unit_cost, units_per_purchase_unit)
    if cost <= 0:
        return Decimal("0.00")
    result = ((money(actual_selling_price) - cost) / cost) * Decimal("100")
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def gross_margin_percent(cost: Decimal, selling_price: Decimal) -> Decimal:
    price = money(selling_price)
    if price <= 0:
        return Decimal("0.00")
    result = ((price - money(cost)) / price) * Decimal("100")
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def stock_balance(db: Session, item_id: str) -> Decimal:
    value = db.scalar(select(func.coalesce(func.sum(StockMovement.quantity_delta), 0)).where(StockMovement.item_id == item_id))
    return quantity(value)


def stock_balances(db: Session, item_ids: list[str]) -> dict[str, Decimal]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(StockMovement.item_id, func.coalesce(func.sum(StockMovement.quantity_delta), 0))
        .where(StockMovement.item_id.in_(item_ids))
        .group_by(StockMovement.item_id)
    ).all()
    return {item_id: quantity(balance) for item_id, balance in rows}


def item_payload(db: Session, item: Item, balance: Decimal | None = None) -> dict:
    balance = stock_balance(db, item.id) if balance is None else quantity(balance)
    reorder = quantity(item.reorder_level)
    conversion = quantity(item.units_per_purchase_unit or Decimal("1"))
    selling_unit = item.selling_unit or item.unit
    per_unit_cost = selling_unit_cost(item.unit_cost, conversion)
    per_unit_profit = money(item.actual_selling_price - per_unit_cost)
    selling_units_on_hand = quantity(balance * conversion)
    status = "out_of_stock" if balance <= 0 else "low_stock" if reorder > 0 and balance <= reorder else "healthy"
    return {
        "id": item.id,
        "item_code": item.item_code,
        "name": item.name,
        "category_id": item.category_id,
        "category_name": item.category.name if item.category else None,
        "unit_id": item.unit_id,
        "unit_name": item.unit.name if item.unit else None,
        "unit_abbreviation": item.unit.abbreviation if item.unit else None,
        "selling_unit_id": item.selling_unit_id or item.unit_id,
        "selling_unit_name": selling_unit.name if selling_unit else None,
        "selling_unit_abbreviation": selling_unit.abbreviation if selling_unit else None,
        "units_per_purchase_unit": conversion,
        "cost_per_selling_unit": per_unit_cost,
        "selling_units_on_hand": selling_units_on_hand,
        "profit_per_selling_unit": per_unit_profit,
        "projected_profit": money(per_unit_profit * selling_units_on_hand),
        "gross_margin_percent": gross_margin_percent(per_unit_cost, item.actual_selling_price),
        "primary_supplier_id": item.primary_supplier_id,
        "supplier_name": item.primary_supplier.name if item.primary_supplier else None,
        "unit_cost": money(item.unit_cost),
        "markup_percent": money(item.markup_percent),
        "suggested_price": money(item.suggested_price),
        "actual_selling_price": money(item.actual_selling_price),
        "reorder_level": reorder,
        "stock_on_hand": balance,
        "stock_status": status,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def movement_payload(db: Session, movement: StockMovement) -> dict:
    return {
        "id": movement.id,
        "item_id": movement.item_id,
        "item_name": movement.item.name if movement.item else None,
        "movement_type": movement.movement_type,
        "quantity_delta": quantity(movement.quantity_delta),
        "unit_cost": money(movement.unit_cost) if movement.unit_cost is not None else None,
        "purchase_date": movement.purchase_date,
        "expiry_date": movement.expiry_date,
        "source": movement.source,
        "reference": movement.reference,
        "notes": movement.notes,
        "actor": movement.actor,
        "created_at": movement.created_at,
    }
