import os

os.environ["DATABASE_URL"] = "sqlite:///./test_sari.db"
os.environ["OCR_PROVIDER"] = "mock"
os.environ["SEED_SAMPLE_DATA"] = "true"

from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app, ocr_client


def setup_module() -> None:
    Base.metadata.drop_all(bind=engine)


def test_dashboard_and_seeded_catalog() -> None:
    with TestClient(app) as client:
        dashboard = client.get("/api/v1/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["metrics"]["active_items"] == 3
        assert dashboard.json()["metrics"]["low_stock"] == 3

        items = client.get("/api/v1/items")
        assert items.status_code == 200
        assert items.json()["total"] == 3
        assert items.json()["data"][0]["suggested_price"]


def test_item_create_and_price_history() -> None:
    with TestClient(app) as client:
        catalog = client.get("/api/v1/catalog").json()
        grocery = next(row for row in catalog["categories"] if row["name"] == "Grocery")
        piece = next(row for row in catalog["units"] if row["name"] == "Piece")
        created = client.post(
            "/api/v1/items",
            json={
                "name": "Test Sardines",
                "category_id": grocery["id"],
                "unit_id": piece["id"],
                "unit_cost": "25.00",
                "markup_percent": "20.00",
                "actual_selling_price": "35.00",
                "reorder_level": "4",
            },
        )
        assert created.status_code == 201
        item = created.json()
        assert item["item_code"] == "ITM-000004"
        assert item["suggested_price"] == "30.00"
        updated = client.patch(f"/api/v1/items/{item['id']}", json={"markup_percent": "30.00"})
        assert updated.status_code == 200
        assert updated.json()["suggested_price"] == "32.50"
        assert updated.json()["actual_selling_price"] == "32.50"


def test_boxed_item_calculates_cost_and_markup_per_piece() -> None:
    with TestClient(app) as client:
        catalog = client.get("/api/v1/catalog").json()
        grocery = next(row for row in catalog["categories"] if row["name"] == "Grocery")
        box = next(row for row in catalog["units"] if row["name"] == "Box")
        piece = next(row for row in catalog["units"] if row["name"] == "Piece")
        created = client.post(
            "/api/v1/items",
            json={
                "name": "Choco Berry Ice Cream Test",
                "category_id": grocery["id"],
                "unit_id": box["id"],
                "selling_unit_id": piece["id"],
                "units_per_purchase_unit": "40",
                "unit_cost": "470.00",
                "markup_percent": "20.00",
                "reorder_level": "2",
            },
        )
        assert created.status_code == 201
        item = created.json()
        assert item["units_per_purchase_unit"] == "40.000"
        assert item["cost_per_selling_unit"] == "11.75"
        assert item["suggested_price"] == "14.10"
        assert item["actual_selling_price"] == "14.10"
        assert item["profit_per_selling_unit"] == "2.35"
        assert item["gross_margin_percent"] == "16.67"
        assert item["projected_profit"] == "0.00"

        received = client.post(
            "/api/v1/stock-movements",
            json={"item_id": item["id"], "movement_type": "MANUAL_IN", "quantity": "1"},
        )
        assert received.status_code == 201
        refreshed = client.get(f"/api/v1/items/{item['id']}").json()
        assert refreshed["stock_on_hand"] == "1.000"
        assert refreshed["selling_units_on_hand"] == "40.000"
        assert refreshed["projected_profit"] == "94.00"

        resized = client.patch(f"/api/v1/items/{item['id']}", json={"units_per_purchase_unit": "50"})
        assert resized.status_code == 200
        assert resized.json()["cost_per_selling_unit"] == "9.40"
        assert resized.json()["suggested_price"] == "11.28"
        assert resized.json()["actual_selling_price"] == "11.28"

        actual_changed = client.patch(f"/api/v1/items/{item['id']}", json={"actual_selling_price": "10.00"})
        assert actual_changed.status_code == 200
        assert actual_changed.json()["markup_percent"] == "6.38"
        assert actual_changed.json()["suggested_price"] == "10.00"

        markup_changed = client.patch(f"/api/v1/items/{item['id']}", json={"markup_percent": "10.00"})
        assert markup_changed.status_code == 200
        assert markup_changed.json()["actual_selling_price"] == "10.34"
        assert markup_changed.json()["profit_per_selling_unit"] == "0.94"
        assert markup_changed.json()["projected_profit"] == "47.00"


def test_stock_ledger_rejects_negative_and_is_idempotent() -> None:
    with TestClient(app) as client:
        item = client.get("/api/v1/items").json()["data"][0]
        too_much = client.post(
            "/api/v1/stock-movements",
            json={"item_id": item["id"], "movement_type": "MANUAL_OUT", "quantity": "999"},
        )
        assert too_much.status_code == 409

        movement_payload = {"item_id": item["id"], "movement_type": "MANUAL_IN", "quantity": "2", "idempotency_key": "test-stock-in-1"}
        first = client.post("/api/v1/stock-movements", json=movement_payload)
        second = client.post("/api/v1/stock-movements", json=movement_payload)
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]


def test_receipt_review_then_confirm_once() -> None:
    with TestClient(app) as client:
        scan_response = client.post("/api/v1/receipt-scans", files={"file": ("supplier.jpg", b"fake-image", "image/jpeg")})
        assert scan_response.status_code == 201
        scan = scan_response.json()
        assert scan["status"] == "REVIEW"
        assert len(scan["lines"]) >= 1
        catalog = client.get("/api/v1/catalog").json()
        can = next(row for row in catalog["units"] if row["abbreviation"] == "can")
        line = scan["lines"][0]
        assert line["unit_abbreviation"] == "pack"
        purchase_updated = client.patch(f"/api/v1/receipt-scans/{scan['id']}", json={"purchased_at": "2026-08-06T00:00:00"})
        assert purchase_updated.status_code == 200
        assert purchase_updated.json()["purchased_at"].startswith("2026-08-06")
        updated = client.patch(f"/api/v1/receipt-scans/{scan['id']}/lines/{line['id']}", json={"unit_id": can["id"], "expiry_date": "2027-08-06"})
        assert updated.status_code == 200
        assert updated.json()["lines"][0]["unit_abbreviation"] == "can"
        assert updated.json()["lines"][0]["expiry_date"] == "2027-08-06"

        confirmed = client.post(f"/api/v1/receipt-scans/{scan['id']}/confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "CONFIRMED"
        movements = client.get(f"/api/v1/items/{line['matched_item_id']}/movements").json()["data"]
        receipt_movement = next(row for row in movements if row["source"] == "receipt")
        assert receipt_movement["purchase_date"] == "2026-08-06"
        assert receipt_movement["expiry_date"] == "2027-08-06"
        duplicate = client.post(f"/api/v1/receipt-scans/{scan['id']}/confirm")
        assert duplicate.status_code == 409


def test_receipt_confirm_creates_an_unmatched_inventory_item() -> None:
    with TestClient(app) as client:
        scan = client.post("/api/v1/receipt-scans", files={"file": ("new-item.jpg", b"fake-image", "image/jpeg")}).json()
        catalog = client.get("/api/v1/catalog").json()
        piece = next(row for row in catalog["units"] if row["name"] == "Piece")
        source_line = scan["lines"][0]
        updated = client.patch(
            f"/api/v1/receipt-scans/{scan['id']}/lines/{source_line['id']}",
            json={"name": "Receipt-only Test Item", "matched_item_id": None, "unit_id": piece["id"]},
        )
        assert updated.status_code == 200
        updated_line = next(row for row in updated.json()["lines"] if row["id"] == source_line["id"])
        assert updated_line["matched_item_id"] is None
        assert updated_line["review_status"] == "REVIEW"

        confirmed = client.post(f"/api/v1/receipt-scans/{scan['id']}/confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["movements_created"] == len(scan["lines"])

        matches = client.get("/api/v1/items", params={"q": "Receipt-only Test Item"}).json()["data"]
        created_item = next(row for row in matches if row["name"] == "Receipt-only Test Item")
        assert created_item["category_name"] == "Uncategorized"
        assert created_item["unit_id"] == piece["id"]
        assert created_item["stock_on_hand"] == source_line["quantity"]
        movements = client.get(f"/api/v1/items/{created_item['id']}/movements").json()["data"]
        assert any(row["source"] == "receipt" for row in movements)


def test_receipt_confirm_explains_missing_unit_for_new_item() -> None:
    with TestClient(app) as client:
        scan = client.post("/api/v1/receipt-scans", files={"file": ("missing-unit.jpg", b"fake-image", "image/jpeg")}).json()
        line = scan["lines"][0]
        updated = client.patch(
            f"/api/v1/receipt-scans/{scan['id']}/lines/{line['id']}",
            json={"name": "Needs Unit Test Item", "matched_item_id": None, "unit_id": None},
        )
        assert updated.status_code == 200

        confirmed = client.post(f"/api/v1/receipt-scans/{scan['id']}/confirm")
        assert confirmed.status_code == 422
        assert confirmed.json()["detail"] == 'Choose a unit for "Needs Unit Test Item" before posting. Unmatched lines are created as new items.'


def test_receipt_gateway_offline_state_is_saved_and_retry_is_bounded(monkeypatch) -> None:
    original_provider = ocr_client.provider
    original_gateway_url = ocr_client.gateway_url
    original_service_token = ocr_client.service_token
    monkeypatch.setenv("OCR_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("OCR_SERVICE_TOKEN", "test-token")
    ocr_client.provider = "gateway"
    ocr_client.gateway_url = "http://127.0.0.1:1"
    ocr_client.service_token = "test-token"
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/receipt-scans", files={"file": ("supplier.jpg", b"fake-image", "image/jpeg")})
            assert first.status_code == 201
            first_scan = first.json()
            assert first_scan["status"] == "WAITING_FOR_SERVICE"
            assert first_scan["attempt_count"] == 1
            assert first_scan["gateway_error_code"] == "provider_unavailable"
            assert first_scan["can_retry"] is True

            second = client.post(f"/api/v1/receipt-scans/{first_scan['id']}/retry")
            assert second.status_code == 200
            assert second.json()["status"] == "FAILED"
            assert second.json()["attempt_count"] == 2
            assert second.json()["can_retry"] is False
    finally:
        ocr_client.provider = original_provider
        ocr_client.gateway_url = original_gateway_url
        ocr_client.service_token = original_service_token
