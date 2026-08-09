import hashlib
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .db import Base, engine, get_db
from .models import Category, Item, PriceHistory, ReceiptLine, ReceiptScan, StockMovement, Supplier, Unit
from .ocr_client import OCRClient, OCRClientError, NormalizedOCRResult
from .schemas import ItemCreate, ItemUpdate, ReceiptConfirmResponse, ReceiptLineUpdate, ReceiptScanUpdate, StockMovementCreate
from .schema_migrations import prepare_schema
from .seed import seed_database
from .services import item_payload, markup_from_selling_price, money, movement_payload, quantity, stock_balance, stock_balances, suggested_selling_price


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_STORAGE = ROOT / "storage" / "receipts"
MAX_RECEIPT_BYTES = 10 * 1024 * 1024
ALLOWED_RECEIPT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ocr_client = OCRClient()


@asynccontextmanager
async def lifespan(_: FastAPI):
    prepare_schema()
    RECEIPT_STORAGE.mkdir(parents=True, exist_ok=True)
    db = next(get_db())
    try:
        if os.getenv("SEED_SAMPLE_DATA", "false").strip().lower() in {"1", "true", "yes", "on"}:
            seed_database(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Sari-Sari Store Inventory API",
    version="0.1.0",
    description="Inventory, receipt review, local PostgreSQL persistence, and private OCR orchestration.",
    lifespan=lifespan,
)

cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api/v1")


def get_record(db: Session, model, record_id: str, label: str):
    record = db.get(model, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return record


def ensure_catalog_refs(db: Session, payload: ItemCreate | ItemUpdate) -> None:
    if payload.category_id is not None and db.get(Category, payload.category_id) is None:
        raise HTTPException(status_code=422, detail="Category not found")
    if payload.unit_id is not None and db.get(Unit, payload.unit_id) is None:
        raise HTTPException(status_code=422, detail="Unit not found")
    if payload.selling_unit_id is not None and db.get(Unit, payload.selling_unit_id) is None:
        raise HTTPException(status_code=422, detail="Selling unit not found")
    if payload.primary_supplier_id is not None and db.get(Supplier, payload.primary_supplier_id) is None:
        raise HTTPException(status_code=422, detail="Supplier not found")


def next_item_code(db: Session) -> str:
    prefix = "ITM-"
    existing = db.scalars(select(Item.item_code).where(Item.item_code.like(f"{prefix}%"))).all()
    numbers = [int(code.removeprefix(prefix)) for code in existing if code.removeprefix(prefix).isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:06d}"


@api.get("/health/live")
def live_health() -> dict:
    return {"status": "ok"}


@api.get("/health/ready")
def ready_health(db: Session = Depends(get_db)) -> dict:
    db.execute(select(1))
    return {"status": "ready"}


@api.get("/catalog")
def catalog(db: Session = Depends(get_db)) -> dict:
    categories = db.scalars(select(Category).where(Category.is_active.is_(True)).order_by(Category.name)).all()
    units = db.scalars(select(Unit).where(Unit.is_active.is_(True)).order_by(Unit.name)).all()
    suppliers = db.scalars(select(Supplier).where(Supplier.is_active.is_(True)).order_by(Supplier.name)).all()
    return {
        "categories": [{"id": row.id, "name": row.name, "description": row.description} for row in categories],
        "units": [{"id": row.id, "name": row.name, "abbreviation": row.abbreviation, "allows_decimal": row.allows_decimal} for row in units],
        "suppliers": [{"id": row.id, "name": row.name} for row in suppliers],
    }


@api.get("/items")
def list_items(
    q: str | None = Query(default=None, max_length=160),
    category_id: str | None = None,
    supplier_id: str | None = None,
    low_stock: bool = False,
    include_archived: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    query = select(Item).options(joinedload(Item.category), joinedload(Item.unit), joinedload(Item.selling_unit), joinedload(Item.primary_supplier)).order_by(Item.name)
    if not include_archived:
        query = query.where(Item.is_active.is_(True))
    if q:
        term = f"%{q.strip()}%"
        query = query.where(or_(Item.name.ilike(term), Item.item_code.ilike(term)))
    if category_id:
        query = query.where(Item.category_id == category_id)
    if supplier_id:
        query = query.where(Item.primary_supplier_id == supplier_id)
    records = db.scalars(query).unique().all()
    balances = stock_balances(db, [item.id for item in records])
    items = [item_payload(db, item, balances.get(item.id, Decimal("0"))) for item in records]
    if low_stock:
        items = [item for item in items if item["stock_status"] in {"low_stock", "out_of_stock"}]
    return {"data": items, "total": len(items)}


@api.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate, db: Session = Depends(get_db)) -> dict:
    ensure_catalog_refs(db, payload)
    code = payload.item_code.strip() if payload.item_code else next_item_code(db)
    if db.scalar(select(Item.id).where(Item.item_code == code)):
        raise HTTPException(status_code=409, detail="Item code already exists")
    conversion = quantity(payload.units_per_purchase_unit)
    markup_percent = money(payload.markup_percent)
    if payload.actual_selling_price is not None and "markup_percent" not in payload.model_fields_set:
        markup_percent = markup_from_selling_price(payload.unit_cost, payload.actual_selling_price, conversion)
    price = suggested_selling_price(payload.unit_cost, markup_percent, conversion)
    item = Item(
        item_code=code,
        name=payload.name.strip(),
        category_id=payload.category_id,
        unit_id=payload.unit_id,
        selling_unit_id=payload.selling_unit_id or payload.unit_id,
        units_per_purchase_unit=conversion,
        primary_supplier_id=payload.primary_supplier_id,
        unit_cost=money(payload.unit_cost),
        markup_percent=markup_percent,
        suggested_price=price,
        actual_selling_price=money(payload.actual_selling_price if payload.actual_selling_price is not None else price),
        reorder_level=quantity(payload.reorder_level),
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Item code already exists") from exc
    db.refresh(item)
    return item_payload(db, item)


@api.get("/items/{item_id}")
def get_item(item_id: str, db: Session = Depends(get_db)) -> dict:
    item = db.scalar(select(Item).options(joinedload(Item.category), joinedload(Item.unit), joinedload(Item.selling_unit), joinedload(Item.primary_supplier)).where(Item.id == item_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item_payload(db, item)


@api.patch("/items/{item_id}")
def update_item(item_id: str, payload: ItemUpdate, db: Session = Depends(get_db)) -> dict:
    item = get_record(db, Item, item_id, "Item")
    ensure_catalog_refs(db, payload)
    before = {
        "unit_cost": money(item.unit_cost),
        "markup_percent": money(item.markup_percent),
        "suggested_price": money(item.suggested_price),
        "actual_selling_price": money(item.actual_selling_price),
    }
    old_unit_id = item.unit_id
    was_one_to_one = item.selling_unit_id == item.unit_id and quantity(item.units_per_purchase_unit) == Decimal("1.000")
    was_using_suggested_price = before["actual_selling_price"] == before["suggested_price"]
    changes = payload.model_dump(exclude_unset=True)
    if "item_code" in changes and changes["item_code"]:
        changes["item_code"] = changes["item_code"].strip()
        duplicate = db.scalar(select(Item.id).where(Item.item_code == changes["item_code"], Item.id != item.id))
        if duplicate:
            raise HTTPException(status_code=409, detail="Item code already exists")
    for field, value in changes.items():
        if field in {"unit_cost", "markup_percent", "actual_selling_price"} and value is not None:
            setattr(item, field, money(value))
        elif field in {"reorder_level", "units_per_purchase_unit"} and value is not None:
            setattr(item, field, quantity(value))
        else:
            setattr(item, field, value)
    if "unit_id" in changes and "selling_unit_id" not in changes and was_one_to_one and item.unit_id != old_unit_id:
        item.selling_unit_id = item.unit_id
    cost_drivers = {"unit_cost", "units_per_purchase_unit"}
    if "actual_selling_price" in changes and "markup_percent" not in changes:
        item.markup_percent = markup_from_selling_price(item.unit_cost, item.actual_selling_price, item.units_per_purchase_unit)
        item.suggested_price = suggested_selling_price(item.unit_cost, item.markup_percent, item.units_per_purchase_unit)
    elif "markup_percent" in changes:
        item.suggested_price = suggested_selling_price(item.unit_cost, item.markup_percent, item.units_per_purchase_unit)
        if "actual_selling_price" not in changes:
            item.actual_selling_price = item.suggested_price
    elif cost_drivers.intersection(changes):
        if was_using_suggested_price:
            item.suggested_price = suggested_selling_price(item.unit_cost, item.markup_percent, item.units_per_purchase_unit)
            item.actual_selling_price = item.suggested_price
        else:
            item.markup_percent = markup_from_selling_price(item.unit_cost, item.actual_selling_price, item.units_per_purchase_unit)
            item.suggested_price = suggested_selling_price(item.unit_cost, item.markup_percent, item.units_per_purchase_unit)
    after = {
        "unit_cost": money(item.unit_cost),
        "markup_percent": money(item.markup_percent),
        "suggested_price": money(item.suggested_price),
        "actual_selling_price": money(item.actual_selling_price),
    }
    if before != after:
        db.add(PriceHistory(item_id=item.id, old_unit_cost=before["unit_cost"], new_unit_cost=after["unit_cost"], old_markup_percent=before["markup_percent"], new_markup_percent=after["markup_percent"], old_suggested_price=before["suggested_price"], new_suggested_price=after["suggested_price"], old_actual_selling_price=before["actual_selling_price"], new_actual_selling_price=after["actual_selling_price"], reason="Item edit", actor="Maria"))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Item code already exists") from exc
    db.refresh(item)
    return item_payload(db, item)


@api.post("/items/{item_id}/archive")
def archive_item(item_id: str, db: Session = Depends(get_db)) -> dict:
    item = get_record(db, Item, item_id, "Item")
    item.is_active = False
    db.commit()
    db.refresh(item)
    return item_payload(db, item)


@api.get("/inventory")
def inventory(db: Session = Depends(get_db)) -> dict:
    records = db.scalars(select(Item).options(joinedload(Item.category), joinedload(Item.unit), joinedload(Item.selling_unit), joinedload(Item.primary_supplier)).where(Item.is_active.is_(True)).order_by(Item.name)).unique().all()
    balances = stock_balances(db, [item.id for item in records])
    return {"data": [item_payload(db, item, balances.get(item.id, Decimal("0"))) for item in records]}


@api.get("/items/{item_id}/movements")
def item_movements(item_id: str, db: Session = Depends(get_db)) -> dict:
    get_record(db, Item, item_id, "Item")
    movements = db.scalars(select(StockMovement).options(joinedload(StockMovement.item)).where(StockMovement.item_id == item_id).order_by(desc(StockMovement.created_at))).unique().all()
    return {"data": [movement_payload(db, movement) for movement in movements]}


@api.post("/stock-movements", status_code=status.HTTP_201_CREATED)
def create_stock_movement(payload: StockMovementCreate, db: Session = Depends(get_db)) -> dict:
    item = get_record(db, Item, payload.item_id, "Item")
    if payload.idempotency_key:
        existing = db.scalar(select(StockMovement).options(joinedload(StockMovement.item)).where(StockMovement.idempotency_key == payload.idempotency_key))
        if existing:
            return movement_payload(db, existing)
    if payload.movement_type in {"RECEIPT_IN", "MANUAL_IN"}:
        delta = quantity(payload.quantity)
    elif payload.movement_type == "MANUAL_OUT":
        delta = -quantity(payload.quantity)
    else:
        delta = quantity(payload.quantity_delta if payload.quantity_delta is not None else payload.quantity)
    balance_after = stock_balance(db, item.id) + delta
    if balance_after < 0:
        raise HTTPException(status_code=409, detail="This movement would make stock negative")
    movement = StockMovement(item_id=item.id, movement_type=payload.movement_type, quantity_delta=delta, unit_cost=money(payload.unit_cost) if payload.unit_cost is not None else None, purchase_date=payload.purchase_date, expiry_date=payload.expiry_date, source=payload.source, reference=payload.reference, notes=payload.notes, actor=payload.actor, idempotency_key=payload.idempotency_key)
    db.add(movement)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if payload.idempotency_key:
            existing = db.scalar(select(StockMovement).options(joinedload(StockMovement.item)).where(StockMovement.idempotency_key == payload.idempotency_key))
            if existing:
                return movement_payload(db, existing)
        raise HTTPException(status_code=409, detail="Movement could not be recorded") from exc
    db.refresh(movement)
    return movement_payload(db, movement)


@api.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    records = db.scalars(select(Item).options(joinedload(Item.category), joinedload(Item.unit), joinedload(Item.selling_unit), joinedload(Item.primary_supplier)).where(Item.is_active.is_(True)).order_by(Item.name)).unique().all()
    balances = stock_balances(db, [item.id for item in records])
    items = [item_payload(db, item, balances.get(item.id, Decimal("0"))) for item in records]
    low_stock_items = [item for item in items if item["stock_status"] in {"low_stock", "out_of_stock"}]
    units_on_hand = sum((item["stock_on_hand"] for item in items), Decimal("0")).quantize(Decimal("0.001"))
    inventory_value = sum((item["stock_on_hand"] * item["unit_cost"] for item in items), Decimal("0")).quantize(Decimal("0.01"))
    recent = db.scalars(select(StockMovement).options(joinedload(StockMovement.item)).order_by(desc(StockMovement.created_at)).limit(8)).unique().all()
    return {
        "metrics": {
            "active_items": len(items),
            "units_on_hand": units_on_hand,
            "inventory_value": inventory_value,
            "low_stock": len(low_stock_items),
        },
        "low_stock_items": low_stock_items,
        "recent_movements": [movement_payload(db, movement) for movement in recent],
        "ocr": {"status": "online" if ocr_client.provider in {"mock", "local"} else "offline", "provider": "mock" if ocr_client.provider in {"mock", "local"} else "gateway", "message": "Ready for receipt review" if ocr_client.provider in {"mock", "local"} else "Check the OCR gateway connection"},
    }


@api.get("/ocr/health")
async def ocr_health() -> dict:
    return await ocr_client.health()


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _match_item(db: Session, name: str, items: list[Item]) -> Item | None:
    normalized = _normalized_text(name)
    if not normalized:
        return None
    for item in items:
        if _normalized_text(item.name) == normalized:
            return item
    candidates = [item for item in items if normalized in _normalized_text(item.name) or _normalized_text(item.name) in normalized]
    return candidates[0] if len(candidates) == 1 else None


def _apply_ocr_result(db: Session, scan: ReceiptScan, result: NormalizedOCRResult) -> None:
    db.query(ReceiptLine).filter(ReceiptLine.receipt_scan_id == scan.id).delete(synchronize_session=False)
    items = db.scalars(select(Item).where(Item.is_active.is_(True)).order_by(Item.name)).all()
    for parsed in result.lines:
        matched_item = _match_item(db, parsed.name, items)
        db.add(ReceiptLine(
            receipt_scan_id=scan.id,
            raw_text=parsed.raw_text,
            name=parsed.name,
            unit_id=matched_item.unit_id if matched_item else None,
            quantity=parsed.quantity,
            unit_cost=parsed.unit_cost,
            line_total=parsed.line_total,
            confidence=parsed.confidence,
            matched_item_id=matched_item.id if matched_item else None,
            review_status="READY" if matched_item else "REVIEW",
        ))
    scan.status = "REVIEW"
    scan.provider = result.provider
    scan.provider_request_id = result.provider_request_id
    scan.merchant_name = result.merchant_name
    scan.receipt_number = result.receipt_number
    scan.purchased_at = result.purchased_at
    scan.currency = result.currency
    scan.total = result.total if result.total is not None else money(sum((line.line_total for line in result.lines), Decimal("0")))
    scan.raw_result = result.raw_payload
    scan.error = None
    scan.gateway_error_code = None
    scan.gateway_http_status = None
    scan.next_retry_at = None


def _record_ocr_error(scan: ReceiptScan, error: OCRClientError) -> None:
    exhausted = scan.attempt_count >= ocr_client.max_attempts
    scan.status = "WAITING_FOR_SERVICE" if error.retryable and not exhausted else "FAILED"
    scan.error = error.message
    scan.gateway_error_code = error.code
    scan.gateway_http_status = error.http_status
    scan.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=min(900, 30 * (2 ** max(scan.attempt_count - 1, 0)))) if error.retryable and not exhausted else None


async def _process_receipt_scan(scan: ReceiptScan, data: bytes | None, db: Session) -> None:
    scan.attempt_count = (scan.attempt_count or 0) + 1
    scan.last_attempt_at = datetime.now(timezone.utc)
    scan.status = "PROCESSING"
    scan.provider = "mock" if ocr_client.provider in {"mock", "local"} else "gateway"
    db.commit()
    try:
        result = await ocr_client.recognize(data, scan.original_filename, _content_type_for_filename(scan.original_filename))
    except OCRClientError as error:
        _record_ocr_error(scan, error)
        db.commit()
        return
    except Exception:
        _record_ocr_error(scan, OCRClientError("provider_unavailable", "OCR processing failed unexpectedly", retryable=True))
        db.commit()
        return
    _apply_ocr_result(db, scan, result)
    db.commit()


def _content_type_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")


def receipt_payload(scan: ReceiptScan) -> dict:
    return {
        "id": scan.id,
        "original_filename": scan.original_filename,
        "status": scan.status,
        "provider": scan.provider,
        "provider_request_id": scan.provider_request_id,
        "merchant_name": scan.merchant_name,
        "receipt_number": scan.receipt_number,
        "purchased_at": scan.purchased_at,
        "currency": scan.currency,
        "total": money(scan.total) if scan.total is not None else None,
        "error": scan.error,
        "attempt_count": scan.attempt_count,
        "last_attempt_at": scan.last_attempt_at,
        "next_retry_at": scan.next_retry_at,
        "gateway_error_code": scan.gateway_error_code,
        "can_retry": scan.status != "CONFIRMED" and scan.attempt_count < ocr_client.max_attempts,
        "warnings": (scan.raw_result or {}).get("warnings", []) if isinstance(scan.raw_result, dict) else [],
        "created_at": scan.created_at,
        "updated_at": scan.updated_at,
        "lines": [
            {
                "id": line.id,
                "raw_text": line.raw_text,
                "name": line.name,
                "unit_id": line.unit_id,
                "unit_name": line.unit.name if line.unit else None,
                "unit_abbreviation": line.unit.abbreviation if line.unit else None,
                "quantity": quantity(line.quantity),
                "unit_cost": money(line.unit_cost),
                "line_total": money(line.line_total),
                "expiry_date": line.expiry_date,
                "confidence": Decimal(str(line.confidence)),
                "matched_item_id": line.matched_item_id,
                "matched_item_name": line.matched_item.name if line.matched_item else None,
                "review_status": line.review_status,
            }
            for line in scan.lines
        ],
    }


@api.get("/receipt-scans")
def list_receipt_scans(db: Session = Depends(get_db)) -> dict:
    scans = db.scalars(select(ReceiptScan).options(joinedload(ReceiptScan.lines).joinedload(ReceiptLine.matched_item), joinedload(ReceiptScan.lines).joinedload(ReceiptLine.unit)).order_by(desc(ReceiptScan.created_at)).limit(20)).unique().all()
    return {"data": [receipt_payload(scan) for scan in scans]}


@api.post("/receipt-scans", status_code=status.HTTP_201_CREATED)
async def create_receipt_scan(file: UploadFile | None = File(default=None), db: Session = Depends(get_db)) -> dict:
    original_filename = file.filename if file and file.filename else "mock-receipt.jpg"
    image_path = None
    data = None
    if file:
        if file.content_type not in ALLOWED_RECEIPT_TYPES:
            raise HTTPException(status_code=415, detail="Receipt must be a JPG, PNG, or WEBP image")
        data = await file.read(MAX_RECEIPT_BYTES + 1)
        if len(data) > MAX_RECEIPT_BYTES:
            raise HTTPException(status_code=413, detail="Receipt image must be 10 MB or smaller")
        suffix = {"image/png": ".png", "image/webp": ".webp"}.get(file.content_type, ".jpg")
        safe_name = f"{uuid.uuid4().hex}{suffix}"
        destination = RECEIPT_STORAGE / safe_name
        destination.write_bytes(data)
        image_path = str(destination.relative_to(ROOT))

    scan = ReceiptScan(
        original_filename=original_filename,
        image_path=image_path,
        status="WAITING_FOR_SERVICE",
        provider="mock" if ocr_client.provider in {"mock", "local"} else "gateway",
        image_sha256=hashlib.sha256(data).hexdigest() if data else None,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    await _process_receipt_scan(scan, data, db)
    db.refresh(scan)
    return receipt_payload(scan)


@api.get("/receipt-scans/{scan_id}")
def get_receipt_scan(scan_id: str, db: Session = Depends(get_db)) -> dict:
    scan = db.scalar(select(ReceiptScan).options(joinedload(ReceiptScan.lines).joinedload(ReceiptLine.matched_item), joinedload(ReceiptScan.lines).joinedload(ReceiptLine.unit)).where(ReceiptScan.id == scan_id))
    if scan is None:
        raise HTTPException(status_code=404, detail="Receipt scan not found")
    return receipt_payload(scan)


@api.patch("/receipt-scans/{scan_id}")
def update_receipt_scan(scan_id: str, payload: ReceiptScanUpdate, db: Session = Depends(get_db)) -> dict:
    scan = get_record(db, ReceiptScan, scan_id, "Receipt scan")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(scan, field, value)
    db.commit()
    db.refresh(scan)
    return receipt_payload(scan)


@api.post("/receipt-scans/{scan_id}/retry")
async def retry_receipt_scan(scan_id: str, db: Session = Depends(get_db)) -> dict:
    scan = db.scalar(select(ReceiptScan).options(joinedload(ReceiptScan.lines).joinedload(ReceiptLine.unit)).where(ReceiptScan.id == scan_id))
    if scan is None:
        raise HTTPException(status_code=404, detail="Receipt scan not found")
    if scan.status == "CONFIRMED":
        raise HTTPException(status_code=409, detail="Confirmed receipts cannot be retried")
    if scan.status == "REVIEW":
        raise HTTPException(status_code=409, detail="Receipt already has a review draft")
    if scan.attempt_count >= ocr_client.max_attempts:
        raise HTTPException(status_code=409, detail="Receipt OCR retry limit reached")
    data = None
    if scan.image_path:
        image_file = ROOT / scan.image_path
        if image_file.is_file():
            data = image_file.read_bytes()
    await _process_receipt_scan(scan, data, db)
    db.refresh(scan)
    return receipt_payload(scan)


@api.patch("/receipt-scans/{scan_id}/lines/{line_id}")
def update_receipt_line(scan_id: str, line_id: str, payload: ReceiptLineUpdate, db: Session = Depends(get_db)) -> dict:
    scan = get_record(db, ReceiptScan, scan_id, "Receipt scan")
    line = db.scalar(select(ReceiptLine).options(joinedload(ReceiptLine.matched_item), joinedload(ReceiptLine.unit)).where(ReceiptLine.id == line_id, ReceiptLine.receipt_scan_id == scan.id))
    if line is None:
        raise HTTPException(status_code=404, detail="Receipt line not found")
    changes = payload.model_dump(exclude_unset=True)
    selected_item = None
    if "matched_item_id" in changes and changes["matched_item_id"] is not None:
        selected_item = get_record(db, Item, changes["matched_item_id"], "Item")
    if "unit_id" in changes and changes["unit_id"] is not None:
        get_record(db, Unit, changes["unit_id"], "Unit")
    for field, value in changes.items():
        setattr(line, field, value)
    if "matched_item_id" in changes and "unit_id" not in changes:
        line.unit_id = selected_item.unit_id if selected_item else None
    if "matched_item_id" in changes and "review_status" not in changes:
        line.review_status = "READY" if selected_item else "REVIEW"
    if "quantity" in changes or "unit_cost" in changes:
        updated_quantity = quantity(changes.get("quantity", line.quantity))
        updated_unit_cost = money(changes.get("unit_cost", line.unit_cost))
        line.line_total = money(updated_quantity * updated_unit_cost)
    db.commit()
    db.refresh(scan)
    return receipt_payload(scan)


def _uncategorized_category(db: Session) -> Category:
    category = db.scalar(select(Category).where(func.lower(Category.name) == "uncategorized"))
    if category is None:
        category = Category(name="Uncategorized", description="Items created while reviewing supplier receipts")
        db.add(category)
        db.flush()
    elif not category.is_active:
        category.is_active = True
    return category


def _create_item_from_receipt_line(db: Session, line: ReceiptLine) -> Item:
    if line.unit_id is None:
        raise HTTPException(
            status_code=422,
            detail=f'Choose a unit for "{line.name}" before posting. Unmatched lines are created as new items.',
        )
    unit_cost = money(line.unit_cost)
    markup_percent = Decimal("20.00")
    selling_price = suggested_selling_price(unit_cost, markup_percent, Decimal("1"))
    item = Item(
        item_code=next_item_code(db),
        name=line.name.strip(),
        category_id=_uncategorized_category(db).id,
        unit_id=line.unit_id,
        selling_unit_id=line.unit_id,
        units_per_purchase_unit=Decimal("1"),
        unit_cost=unit_cost,
        markup_percent=markup_percent,
        suggested_price=selling_price,
        actual_selling_price=selling_price,
        reorder_level=Decimal("0"),
    )
    db.add(item)
    db.flush()
    line.matched_item_id = item.id
    line.review_status = "READY"
    return item


@api.post("/receipt-scans/{scan_id}/confirm", response_model=ReceiptConfirmResponse)
def confirm_receipt_scan(scan_id: str, db: Session = Depends(get_db)) -> ReceiptConfirmResponse:
    scan = db.scalar(select(ReceiptScan).options(joinedload(ReceiptScan.lines).joinedload(ReceiptLine.matched_item)).where(ReceiptScan.id == scan_id))
    if scan is None:
        raise HTTPException(status_code=404, detail="Receipt scan not found")
    if scan.status == "CONFIRMED":
        raise HTTPException(status_code=409, detail="Receipt has already been confirmed")
    if scan.status != "REVIEW":
        raise HTTPException(status_code=409, detail="Receipt is not ready for confirmation")
    lines = list(scan.lines)
    if not lines:
        raise HTTPException(status_code=422, detail="Receipt needs at least one line before confirmation")
    created = 0
    try:
        for line in lines:
            existing = db.scalar(select(StockMovement).where(StockMovement.idempotency_key == f"receipt:{scan.id}:line:{line.id}"))
            if existing:
                continue
            created_item = line.matched_item_id is None
            item = _create_item_from_receipt_line(db, line) if created_item else get_record(db, Item, line.matched_item_id, "Item")
            db.add(StockMovement(item_id=item.id, movement_type="RECEIPT_IN", quantity_delta=quantity(line.quantity), unit_cost=money(line.unit_cost), purchase_date=scan.purchased_at.date() if scan.purchased_at else None, expiry_date=line.expiry_date, source="receipt", reference=scan.receipt_number, notes=f"Confirmed receipt {scan.id}", actor="Maria", idempotency_key=f"receipt:{scan.id}:line:{line.id}"))
            if not created_item:
                old = {"unit_cost": money(item.unit_cost), "markup_percent": money(item.markup_percent), "suggested_price": money(item.suggested_price), "actual_selling_price": money(item.actual_selling_price)}
                item.unit_cost = money(line.unit_cost)
                if old["actual_selling_price"] == old["suggested_price"]:
                    item.suggested_price = suggested_selling_price(item.unit_cost, item.markup_percent, item.units_per_purchase_unit)
                    item.actual_selling_price = item.suggested_price
                else:
                    item.markup_percent = markup_from_selling_price(item.unit_cost, item.actual_selling_price, item.units_per_purchase_unit)
                    item.suggested_price = suggested_selling_price(item.unit_cost, item.markup_percent, item.units_per_purchase_unit)
                if old["unit_cost"] != money(item.unit_cost) or old["suggested_price"] != money(item.suggested_price):
                    db.add(PriceHistory(item_id=item.id, old_unit_cost=old["unit_cost"], new_unit_cost=money(item.unit_cost), old_markup_percent=old["markup_percent"], new_markup_percent=money(item.markup_percent), old_suggested_price=old["suggested_price"], new_suggested_price=money(item.suggested_price), old_actual_selling_price=old["actual_selling_price"], new_actual_selling_price=money(item.actual_selling_price), reason=f"Receipt {scan.receipt_number}", actor="Maria"))
            created += 1
        scan.status = "CONFIRMED"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ReceiptConfirmResponse(scan_id=scan.id, status=scan.status, movements_created=created, total=money(scan.total))


app.include_router(api)
