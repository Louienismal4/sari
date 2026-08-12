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
from app.pdf_receipts import ExtractedPDF, parse_consolidated_receipt_pdf
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


def test_consolidated_pdf_result_contains_reviewable_lines() -> None:
    result = parse_consolidated_receipt_pdf(
        ExtractedPDF(
            page_count=1,
            text="""
CONSOLIDATED RECEIPTS LINE ITEMS
SPJM GEN. MDSE.
Date: 08/11/2026 04:05:13 PM  Cashier: SPJM
# ITEM DESCRIPTION QTY UNIT PRICE TOTAL AMOUNT
1 TATTOOS SC 58GX10 1 P85.00 P85.00
2 ASSORTED BIG SNACK 25 P16.50 P412.50
""",
        ),
        "Consolidated_Receipts_Line_Items.pdf",
    )

    assert result.provider == "pdf_text"
    assert result.merchant_name == "Consolidated receipt report"
    assert result.purchased_at is not None
    assert result.total == Decimal("497.50")
    assert [(line.name, line.quantity, line.unit_cost, line.line_total) for line in result.lines] == [
        ("TATTOOS SC 58GX10", Decimal("1.000"), Decimal("85.00"), Decimal("85.00")),
        ("ASSORTED BIG SNACK", Decimal("25.000"), Decimal("16.50"), Decimal("412.50")),
    ]


def test_receipt_accepts_a_consolidated_pdf(monkeypatch) -> None:
    extracted = ExtractedPDF(
        page_count=1,
        text="1 TATTOOS SC 58GX10 1 P85.00 P85.00",
    )
    monkeypatch.setattr("app.main.extract_pdf_receipt", lambda _: extracted)

    with TestClient(app) as client:
        response = client.post(
            "/v1/ocr/receipts",
            headers={"X-OCR-Service-Token": "test-gateway-token"},
            files={"file": ("Consolidated_Receipts_Line_Items.pdf", b"%PDF-1.7\nmock", "application/pdf")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "pdf_text"
    assert payload["lines"][0]["name"] == "TATTOOS SC 58GX10"


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


def test_paddle_at_sign_receipt_with_wrapped_names_and_implicit_single_items() -> None:
    """A receipt need not have a product code or an ``x`` quantity marker.

    This fixture also includes text from a shorter, secondary receipt on the
    left of the photo. Only the long primary receipt should become draft lines.
    """

    detections = [
        # Secondary receipt visible in the background.
        ("Lucky Me Inst Ndl 9 10.17 91.50", 20, 70, 340),
        ("Spicy Beef 10 10.75 107.50", 20, 100, 340),
        ("Chilimansi 20 15.00 300.00", 20, 130, 340),
        # Primary receipt.
        ("BASTI'S VARIETY STORE", 455, 20, 750),
        ("Item", 430, 50, 520),
        ("Amount", 690, 50, 790),
        ("DM Four Season", 430, 80, 650),
        ("124.00", 700, 80, 790),
        ("4 @ 33.00", 450, 105, 590),
        ("Less 2", 450, 130, 540),
        ("Alaska Evaporada", 430, 165, 650),
        ("108.00", 700, 165, 790),
        ("360ml", 430, 190, 520),
        ("3 @ 36.00", 450, 215, 590),
        ("Alaska Evaporada", 430, 250, 650),
        ("78.00", 710, 250, 790),
        ("140ml", 430, 275, 520),
        ("4 @ 19.50", 450, 300, 590),
        ("Argentina Corned", 430, 335, 650),
        ("240.00", 700, 335, 790),
        ("Beef 260g", 430, 360, 560),
        ("4 @ 60.00", 450, 385, 590),
        ("Ufc Gldn Esta Oil", 430, 420, 650),
        ("275.00", 700, 420, 790),
        ("Cnola Pet 2/1I-P", 430, 445, 630),
        ("Century Tuna", 430, 480, 610),
        ("86.40", 710, 480, 790),
        ("Flakes H&S 95g", 430, 505, 620),
        ("3 @ 28.80", 450, 530, 590),
        ("Argentina Corned", 430, 565, 650),
        ("219.00", 700, 565, 790),
        ("Beef 150g", 430, 590, 560),
        ("6 @ 36.50", 450, 615, 590),
        ("Total", 430, 655, 530),
        ("1050.40", 690, 655, 790),
    ]
    texts = [text for text, *_ in detections]
    boxes = [[x1, y, x2, y + 18] for _, x1, y, x2 in detections]
    result = normalize_paddle_result(
        [{"res": {"rec_texts": texts, "rec_scores": [0.97] * len(texts), "rec_boxes": boxes}}],
        filename="long-supplier-receipt.jpg",
    )

    assert result.merchant_name == "BASTI'S VARIETY STORE"
    assert result.total == Decimal("1050.40")
    assert [(line.name, line.quantity, line.unit_cost, line.line_total) for line in result.lines] == [
        ("DM Four Season", Decimal("4.000"), Decimal("33.00"), Decimal("124.00")),
        ("Alaska Evaporada 360ml", Decimal("3.000"), Decimal("36.00"), Decimal("108.00")),
        ("Alaska Evaporada 140ml", Decimal("4.000"), Decimal("19.50"), Decimal("78.00")),
        ("Argentina Corned Beef 260g", Decimal("4.000"), Decimal("60.00"), Decimal("240.00")),
        ("Ufc Gldn Esta Oil Cnola Pet 2/1I-P", Decimal("1.000"), Decimal("275.00"), Decimal("275.00")),
        ("Century Tuna Flakes H&S 95g", Decimal("3.000"), Decimal("28.80"), Decimal("86.40")),
        ("Argentina Corned Beef 150g", Decimal("6.000"), Decimal("36.50"), Decimal("219.00")),
    ]
    assert all("Lucky Me" not in line.name for line in result.lines)


def test_numeric_product_description_is_not_mistaken_for_quantity_and_cost() -> None:
    result = normalize_paddle_result(
        [
            {
                "res": {
                    "rec_texts": ["Supplier Store", "Knorr 2 in 1 Seasoning 250ml", "104.00", "Total", "104.00"],
                    "rec_scores": [0.98] * 5,
                    "rec_boxes": [
                        [20, 10, 200, 28],
                        [20, 40, 260, 58],
                        [300, 40, 370, 58],
                        [20, 75, 80, 93],
                        [300, 75, 370, 93],
                    ],
                }
            }
        ]
    )

    assert len(result.lines) == 1
    assert result.lines[0].name == "Knorr 2 in 1 Seasoning 250ml"
    assert result.lines[0].quantity == Decimal("1.000")
    assert result.lines[0].unit_cost == Decimal("104.00")
