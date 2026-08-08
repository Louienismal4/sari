import asyncio
import io
import os
from decimal import Decimal

from fastapi.testclient import TestClient
from PIL import Image

os.environ["OCR_PROVIDER"] = "mock"
os.environ["OCR_GATEWAY_PROVIDER"] = "mock"
os.environ["OCR_SERVICE_TOKEN"] = "test-gateway-token"

from app.main import app
from app.providers import PaddleOCRProvider, normalize_paddle_result


def image_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (240, 160), "white").save(stream, format="JPEG")
    return stream.getvalue()


def test_liveness_and_readiness() -> None:
    with TestClient(app) as client:
        assert client.get("/health/live").json()["status"] == "ok"
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["provider"] == "mock"


def test_paddle_readiness_waits_for_successful_warmup(monkeypatch) -> None:
    provider = PaddleOCRProvider()
    monkeypatch.setattr("app.providers.importlib.util.find_spec", lambda _: object())

    ready, message = provider.readiness()
    assert ready is False
    assert "warming up" in message

    def complete_warmup() -> None:
        provider._warmed = True

    monkeypatch.setattr(provider, "_warmup_sync", complete_warmup)
    asyncio.run(provider.warmup())

    ready, message = provider.readiness()
    assert ready is True
    assert "ready" in message


def test_receipt_requires_service_token() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/ocr/receipts", files={"file": ("receipt.jpg", image_bytes(), "image/jpeg")})
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "unauthorized"


def test_receipt_returns_normalized_mock_result() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/ocr/receipts",
            headers={"X-OCR-Service-Token": "test-gateway-token"},
            files={"file": ("receipt.jpg", image_bytes(), "image/jpeg")},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["provider"] == "mock"
        assert payload["lines"][0]["name"] == "Lucky Me Pancit Canton"
        assert payload["lines"][0]["quantity"] == "10.000"


def test_receipt_rejects_invalid_image_bytes() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/ocr/receipts",
            headers={"X-OCR-Service-Token": "test-gateway-token"},
            files={"file": ("receipt.jpg", b"not-an-image", "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_image"


def test_paddle_result_is_grouped_into_reviewable_draft_lines() -> None:
    result = normalize_paddle_result(
        [
            {
                "res": {
                    "rec_texts": ["LUCKY ME PANCIT CANTON", "10", "8.50", "85.00", "TOTAL", "85.00"],
                    "rec_scores": [0.96, 0.98, 0.95, 0.94, 0.99, 0.98],
                    "rec_boxes": [
                        [10, 10, 140, 28],
                        [150, 10, 170, 28],
                        [180, 10, 215, 28],
                        [225, 10, 260, 28],
                        [10, 40, 60, 58],
                        [70, 40, 105, 58],
                    ],
                }
            }
        ],
        filename="supplier.jpg",
    )

    assert result.provider == "paddleocr_ppocrv4"
    assert result.total == Decimal("85.00")
    assert len(result.lines) == 1
    assert result.lines[0].name == "LUCKY ME PANCIT CANTON"
    assert result.lines[0].quantity == Decimal("10.000")
    assert result.lines[0].unit_cost == Decimal("8.50")
    assert result.lines[0].line_total == Decimal("85.00")
    assert result.raw_result["text_lines"][0]["text"] == "LUCKY ME PANCIT CANTON"


def test_paddle_two_line_receipt_items_are_parsed_without_date_false_positive() -> None:
    texts = [
        "Employee:Owner",
        "POS:POS 33",
        "101 Milky Milk 50",
        "780.00",
        "2x390.00",
        "103 Milky Chocolate 50",
        "780.00",
        "2x390.00",
        "104Choco Berry 50",
        "390.00",
        "1x390.00",
        "105 Watermelon Apple 50 390.00",
        "1x390.00",
        "302 Crunch Choco Malt",
        "680.00",
        "35",
        "1x680.00",
        "Total",
        "P4,900.00",
        "#35-1065",
        "06/08/20262:38 pm",
    ]
    y_positions = [10, 35, 65, 65, 92, 122, 122, 149, 179, 179, 206, 236, 263, 293, 293, 320, 347, 382, 382, 412, 439]
    boxes = [[10, y, 180, y + 18] for y in y_positions]
    boxes[3] = [300, y_positions[3], 380, y_positions[3] + 18]
    boxes[6] = [300, y_positions[6], 380, y_positions[6] + 18]
    boxes[9] = [300, y_positions[9], 380, y_positions[9] + 18]
    boxes[14] = [300, y_positions[14], 380, y_positions[14] + 18]
    boxes[18] = [300, y_positions[18], 410, y_positions[18] + 18]
    result = normalize_paddle_result(
        [{"res": {"rec_texts": texts, "rec_scores": [0.98] * len(texts), "rec_boxes": boxes}}],
        filename="IMG_0106.JPG",
    )

    assert result.total == Decimal("4900.00")
    assert result.receipt_number == "35-1065"
    assert len(result.lines) == 5
    assert [(line.name, line.quantity, line.unit_cost, line.line_total) for line in result.lines] == [
        ("Milky Milk 50", Decimal("2.000"), Decimal("390.00"), Decimal("780.00")),
        ("Milky Chocolate 50", Decimal("2.000"), Decimal("390.00"), Decimal("780.00")),
        ("Choco Berry 50", Decimal("1.000"), Decimal("390.00"), Decimal("390.00")),
        ("Watermelon Apple 50", Decimal("1.000"), Decimal("390.00"), Decimal("390.00")),
        ("Crunch Choco Malt 35", Decimal("1.000"), Decimal("680.00"), Decimal("680.00")),
    ]
