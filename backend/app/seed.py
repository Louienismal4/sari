from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, Item, StockMovement, Supplier, Unit
from .services import suggested_price


def seed_database(db: Session) -> None:
    unit_definitions = [
        ("Piece", "pc", False),
        ("Pack", "pack", False),
        ("Bottle", "btl", False),
        ("Can", "can", False),
        ("Box", "box", False),
        ("Sachet", "sachet", False),
        ("Kilogram", "kg", True),
    ]
    existing_units = {record.name: record for record in db.scalars(select(Unit)).all()}
    units = []
    for name, abbreviation, allows_decimal in unit_definitions:
        unit = existing_units.get(name)
        if unit is None:
            unit = Unit(name=name, abbreviation=abbreviation, allows_decimal=allows_decimal)
            db.add(unit)
        units.append(unit)
    db.flush()

    if db.scalar(select(Item.id).limit(1)):
        db.commit()
        return

    categories = [
        Category(name="Grocery", description="Everyday pantry and snack items"),
        Category(name="Beverages", description="Drinks and powdered mixes"),
        Category(name="Household", description="Cleaning and home essentials"),
    ]
    suppliers = [
        Supplier(name="Prime Goods Wholesale", contact_person="Ramon Cruz", phone="0917 555 0142"),
        Supplier(name="M&J Distributors", contact_person="Mila Santos", phone="0918 555 0188"),
    ]
    db.add_all(categories + units + suppliers)
    db.flush()

    category_by_name = {record.name: record for record in categories}
    unit_by_name = {record.name: record for record in units}
    supplier_by_name = {record.name: record for record in suppliers}

    seed_items = [
        ("Lucky Me Pancit Canton", "Grocery", "Pack", "Prime Goods Wholesale", Decimal("8.50"), Decimal("20"), Decimal("12"), Decimal("20")),
        ("Alaska Milk", "Grocery", "Piece", "Prime Goods Wholesale", Decimal("45.00"), Decimal("20"), Decimal("8"), Decimal("15")),
        ("Kopiko Brown", "Beverages", "Pack", "M&J Distributors", Decimal("12.00"), Decimal("25"), Decimal("5"), Decimal("10")),
    ]
    for index, (name, category, unit, supplier, cost, markup, opening_stock, reorder) in enumerate(seed_items, start=1):
        item = Item(
            item_code=f"ITM-{index:06d}",
            name=name,
            category_id=category_by_name[category].id,
            unit_id=unit_by_name[unit].id,
            selling_unit_id=unit_by_name[unit].id,
            units_per_purchase_unit=Decimal("1"),
            primary_supplier_id=supplier_by_name[supplier].id,
            unit_cost=cost,
            markup_percent=markup,
            suggested_price=suggested_price(cost, markup),
            actual_selling_price=suggested_price(cost, markup),
            reorder_level=reorder,
        )
        db.add(item)
        db.flush()
        db.add(
            StockMovement(
                item_id=item.id,
                movement_type="RECEIPT_IN",
                quantity_delta=opening_stock,
                unit_cost=cost,
                source="seed",
                reference="Opening balance",
                actor="Maria",
                notes="Initial Phase 1 sample data",
            )
        )

    db.commit()
