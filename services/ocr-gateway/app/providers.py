import asyncio
import importlib.util
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from .contracts import OCRReceiptLine, OCRReceiptResult
from .errors import ProviderError


class OCRProvider(Protocol):
    name: str

    async def warmup(self) -> None:
        ...

    async def recognize(self, image: bytes, content_type: str, filename: str) -> OCRReceiptResult:
        ...

    def readiness(self) -> tuple[bool, str]:
        ...


class MockOCRProvider:
    name = "mock"

    async def warmup(self) -> None:
        return None

    async def recognize(self, image: bytes, content_type: str, filename: str) -> OCRReceiptResult:
        del image, content_type
        lines = [
            OCRReceiptLine(
                raw_text="LUCKY ME PANCIT CANTON 10 8.50 85.00",
                name="Lucky Me Pancit Canton",
                quantity=Decimal("10"),
                unit_cost=Decimal("8.50"),
                line_total=Decimal("85.00"),
                confidence=Decimal("0.94"),
            ),
            OCRReceiptLine(
                raw_text="KOPIKO BROWN 6 12.00 72.00",
                name="Kopiko Brown",
                quantity=Decimal("6"),
                unit_cost=Decimal("12.00"),
                line_total=Decimal("72.00"),
                confidence=Decimal("0.89"),
            ),
        ]
        return OCRReceiptResult(
            provider=self.name,
            provider_request_id=f"mock-{uuid4().hex[:10]}",
            merchant_name="Prime Goods Wholesale",
            receipt_number="MOCK-2026-001",
            purchased_at=datetime.now(timezone.utc),
            currency="PHP",
            total=Decimal("157.00"),
            lines=lines,
            warnings=["Mock OCR result; review every line before confirmation.", f"Source: {filename}"],
        )

    def readiness(self) -> tuple[bool, str]:
        return True, "Mock OCR adapter is ready"


class PaddleOCRProvider:
    """Local CPU PaddleOCR adapter using the PP-OCRv4 mobile models.

    PaddleOCR is imported only for this provider, then warmed during gateway
    startup. Mock mode and the application test suite do not need the large
    inference runtime installed. The pipeline is cached for the process lifetime.
    """

    name = "paddleocr_ppocrv4"

    def __init__(self) -> None:
        self.ocr_version = os.getenv("PADDLEOCR_VERSION", "PP-OCRv4").strip() or "PP-OCRv4"
        self.lang = os.getenv("PADDLEOCR_LANG", "en").strip() or "en"
        self.device = os.getenv("PADDLEOCR_DEVICE", "cpu").strip() or "cpu"
        self.engine = os.getenv("PADDLEOCR_ENGINE", "paddle_static").strip() or None
        self.det_model_name = os.getenv("PADDLEOCR_DET_MODEL_NAME", "PP-OCRv4_mobile_det").strip() or None
        self.rec_model_name = os.getenv("PADDLEOCR_REC_MODEL_NAME", "en_PP-OCRv4_mobile_rec").strip() or None
        self.det_model_dir = os.getenv("PADDLEOCR_DET_MODEL_DIR", "").strip() or None
        self.rec_model_dir = os.getenv("PADDLEOCR_REC_MODEL_DIR", "").strip() or None
        self.model_base_dir = (
            os.getenv("PADDLE_OCR_BASE_DIR", "").strip()
            or os.getenv("PADDLEOCR_MODEL_BASE_DIR", "").strip()
            or None
        )
        self.enable_mkldnn = _env_bool("PADDLEOCR_ENABLE_MKLDNN", False)
        self.cpu_threads = _env_int("PADDLEOCR_CPU_THREADS", 2, minimum=1, maximum=32)
        self.mkldnn_cache_capacity = _env_int("PADDLEOCR_MKLDNN_CACHE_CAPACITY", 10, minimum=1, maximum=128)
        self.text_det_limit_side_len = _env_int("PADDLEOCR_TEXT_DET_LIMIT_SIDE_LEN", 1600, minimum=64, maximum=4096)
        self.timeout = _env_float("PADDLEOCR_TIMEOUT_SECONDS", 90.0, minimum=1.0, maximum=900.0)
        self.warmup_timeout = _env_float("PADDLEOCR_WARMUP_TIMEOUT_SECONDS", 300.0, minimum=1.0, maximum=1800.0)
        self._ocr: Any | None = None
        self._ocr_lock = Lock()
        self._inference_lock = Lock()
        self._warmed = False
        self._warmup_error: str | None = None

    def readiness(self) -> tuple[bool, str]:
        if importlib.util.find_spec("paddleocr") is None:
            return False, "PaddleOCR is not installed in the gateway runtime"
        if importlib.util.find_spec("paddle") is None:
            return False, "PaddlePaddle is not installed in the gateway runtime"
        if self._warmup_error:
            return False, self._warmup_error
        if not self._warmed:
            return False, "PaddleOCR models are warming up"
        return (
            True,
            f"PaddleOCR {self.ocr_version} is ready on {self.device} with mobile CPU models",
        )

    async def warmup(self) -> None:
        """Load the models and execute one tiny inference before accepting traffic."""
        try:
            await asyncio.wait_for(asyncio.to_thread(self._warmup_sync), timeout=self.warmup_timeout)
        except asyncio.TimeoutError:
            self._warmup_error = "PaddleOCR model warmup timed out; restart the gateway after checking CPU and model storage"
        except ProviderError as error:
            self._warmup_error = error.message
        except Exception:
            self._warmup_error = "PaddleOCR model warmup failed; check the gateway logs"

    def _warmup_sync(self) -> None:
        try:
            import numpy as np
        except ImportError as exc:
            raise ProviderError("provider_not_configured", "PaddleOCR CPU dependencies are not installed", 503) from exc

        probe = np.full((64, 256, 3), 255, dtype=np.uint8)
        with self._inference_lock:
            pipeline = self._get_pipeline()
            list(pipeline.predict(probe))
        self._warmed = True
        self._warmup_error = None

    async def recognize(self, image: bytes, content_type: str, filename: str) -> OCRReceiptResult:
        del content_type
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._recognize_sync, image, filename), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise ProviderError("provider_timeout", "PaddleOCR receipt recognition timed out", 504, retryable=True) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("provider_error", "PaddleOCR could not process the receipt image", 502) from exc

    def _recognize_sync(self, image: bytes, filename: str) -> OCRReceiptResult:
        try:
            import numpy as np
            from PIL import Image
            from io import BytesIO
        except ImportError as exc:
            raise ProviderError("provider_not_configured", "PaddleOCR CPU dependencies are not installed", 503) from exc

        with Image.open(BytesIO(image)) as decoded:
            image_array = np.array(decoded.convert("RGB"))

        with self._inference_lock:
            pipeline = self._get_pipeline()
            results = list(pipeline.predict(image_array))
        self._warmed = True
        self._warmup_error = None
        return normalize_paddle_result(
            results,
            filename=filename,
            model_version=self.ocr_version,
            detection_model=self.det_model_name,
            recognition_model=self.rec_model_name,
        )

    def _get_pipeline(self) -> Any:
        if self._ocr is not None:
            return self._ocr
        with self._ocr_lock:
            if self._ocr is not None:
                return self._ocr
            if self.model_base_dir:
                os.environ.setdefault("PADDLE_OCR_BASE_DIR", self.model_base_dir)
            if _env_bool("PADDLEOCR_DISABLE_MODEL_SOURCE_CHECK", True):
                os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise ProviderError("provider_not_configured", "PaddleOCR is not installed in the gateway runtime", 503) from exc

            options: dict[str, Any] = {
                "ocr_version": self.ocr_version,
                "lang": self.lang,
                "device": self.device,
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "enable_mkldnn": self.enable_mkldnn,
                "mkldnn_cache_capacity": self.mkldnn_cache_capacity,
                "cpu_threads": self.cpu_threads,
                "text_det_limit_side_len": self.text_det_limit_side_len,
                "text_det_limit_type": "max",
            }
            if self.engine:
                options["engine"] = self.engine
            if self.det_model_name:
                options["text_detection_model_name"] = self.det_model_name
            if self.rec_model_name:
                options["text_recognition_model_name"] = self.rec_model_name
            if self.det_model_dir:
                options["text_detection_model_dir"] = self.det_model_dir
            if self.rec_model_dir:
                options["text_recognition_model_dir"] = self.rec_model_dir

            try:
                self._ocr = PaddleOCR(**options)
            except Exception as exc:
                raise ProviderError(
                    "provider_initialization",
                    "PaddleOCR PP-OCRv4 model initialization failed; check the CPU runtime and model paths",
                    503,
                    retryable=True,
                ) from exc
            return self._ocr


_NUMBER_RE = re.compile(r"(?<![A-Za-z])(?:PHP|₱|P)?\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_METADATA_RE = re.compile(r"\b(total|subtotal|grand total|amount due|vat|tax|change|cash|invoice|receipt|date|time|qty|quantity|price)\b", re.IGNORECASE)
_PROVIDER_CACHE: dict[str, OCRProvider] = {}
_PROVIDER_CACHE_LOCK = Lock()


def normalize_paddle_result(
    raw_results: Any,
    *,
    filename: str = "receipt.jpg",
    model_version: str = "PP-OCRv4",
    detection_model: str | None = "PP-OCRv4_mobile_det",
    recognition_model: str | None = "en_PP-OCRv4_mobile_rec",
) -> OCRReceiptResult:
    """Convert PaddleOCR 3.x result objects into the gateway contract.

    PaddleOCR returns text detections, not a guaranteed receipt table. We
    group detections by their vertical position and only create draft lines
    when a row contains an item name, quantity, unit cost, and line total.
    Anything ambiguous remains in raw_result for manual review.
    """

    mapping = _first_result_mapping(raw_results)
    entries = _paddle_entries(mapping)
    row_groups = _group_paddle_entry_rows(entries)
    rows = [(row["text"], row["confidence"]) for row in row_groups]
    parsed_lines, unparsed_rows = _parse_paddle_receipt_rows(row_groups)

    total = _extract_total(rows)
    merchant_name = _extract_merchant(rows)
    receipt_number = _extract_receipt_number(rows)
    warnings = [
        "PaddleOCR PP-OCRv4 text was normalized locally; review every line before confirmation.",
        f"Source: {filename}",
    ]
    if unparsed_rows:
        warnings.append("Some OCR rows were not converted into line items; check the source text.")
    if not parsed_lines:
        warnings.append("No structured line items were inferred; review the receipt manually.")

    text_lines = [
        {
            "text": entry["text"],
            "confidence": float(entry["confidence"]),
            "box": _plain_value(entry.get("box")),
        }
        for entry in entries
    ]
    raw_result = {
        "model": model_version,
        "detection_model": detection_model,
        "recognition_model": recognition_model,
        "text_lines": text_lines,
        "rows": [text for text, _ in rows],
    }
    return OCRReceiptResult(
        provider="paddleocr_ppocrv4",
        provider_request_id=f"paddle-{uuid4().hex[:12]}",
        merchant_name=merchant_name,
        receipt_number=receipt_number,
        purchased_at=None,
        currency="PHP",
        total=total,
        lines=parsed_lines,
        warnings=warnings,
        raw_result=raw_result,
    )


def _paddle_entries(mapping: Mapping[str, Any]) -> list[dict[str, Any]]:
    texts = _as_list(mapping.get("rec_texts"))
    scores = _as_list(mapping.get("rec_scores"))
    boxes = _as_list(mapping.get("rec_boxes"))
    if not boxes:
        boxes = _as_list(mapping.get("rec_polys"))
    if not boxes:
        boxes = _as_list(mapping.get("dt_polys"))

    entries: list[dict[str, Any]] = []
    for index, value in enumerate(texts):
        text = str(value or "").strip()
        if not text:
            continue
        confidence = _confidence(scores[index] if index < len(scores) else None)
        box = boxes[index] if index < len(boxes) else None
        entries.append({"text": text[:500], "confidence": confidence, "box": box, "index": index})
    return entries


def _group_paddle_entries(entries: list[dict[str, Any]]) -> list[tuple[str, Decimal]]:
    return [(row["text"], row["confidence"]) for row in _group_paddle_entry_rows(entries)]


def _group_paddle_entry_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return []
    sortable = sorted(entries, key=_entry_position)
    rows: list[dict[str, Any]] = []
    for entry in sortable:
        bounds = _box_bounds(entry.get("box"))
        if bounds is None:
            rows.append({"entries": [entry], "center_y": float(entry["index"]), "height": 1.0})
            continue
        x1, y1, x2, y2 = bounds
        center_y = (y1 + y2) / 2
        height = max(1.0, y2 - y1)
        matching_row = next(
            (
                row
                for row in rows
                if abs(center_y - row["center_y"]) <= max(8.0, height * 0.6, row["height"] * 0.6)
            ),
            None,
        )
        if matching_row is None:
            rows.append({"entries": [entry], "center_y": center_y, "height": height})
        else:
            matching_row["entries"].append(entry)
            row_centers = [
                (item_bounds[1] + item_bounds[3]) / 2
                for item in matching_row["entries"]
                if (item_bounds := _box_bounds(item.get("box"))) is not None
            ]
            matching_row["center_y"] = sum(row_centers) / max(1, len(row_centers))
            matching_row["height"] = max(matching_row["height"], height)

    grouped: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda value: value["center_y"]):
        row_entries = sorted(row["entries"], key=_entry_position)
        text = re.sub(r"\s+", " ", " ".join(entry["text"] for entry in row_entries)).strip()
        confidence = sum((entry["confidence"] for entry in row_entries), Decimal("0")) / max(1, len(row_entries))
        if text:
            grouped.append(
                {
                    "text": text[:500],
                    "confidence": _confidence(confidence),
                    "entries": row_entries,
                    "center_y": row["center_y"],
                }
            )
    return grouped


def _entry_position(entry: dict[str, Any]) -> tuple[float, float]:
    bounds = _box_bounds(entry.get("box"))
    if bounds is None:
        position = float(entry["index"])
        return position, position
    return bounds[1], bounds[0]


_ITEM_HEADER_RE = re.compile(r"^\s*(\d{2,5})\s*(?=[A-Za-z])(.+?)\s*$")
_QTY_ROW_RE = re.compile(
    r"^\s*(\d[\d,]*(?:\.\d+)?)\s*[x×*]\s*(?:PHP|₱|P)?\s*(\d[\d,]*(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
_DATE_LIKE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\b\d{1,2}:\d{2}\b", re.IGNORECASE)
_METADATA_PREFIX_RE = re.compile(r"^\s*(?:employee|pos|cash|total|subtotal|change|store|invoice|receipt)\b", re.IGNORECASE)


def _parse_paddle_receipt_rows(rows: list[dict[str, Any]]) -> tuple[list[OCRReceiptLine], list[str]]:
    parsed_lines: list[OCRReceiptLine] = []
    unparsed_rows: list[str] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        row_text = str(row["text"])
        item_header = _parse_paddle_item_header(row_text)
        if item_header is not None:
            quantity_index = index + 1
            continuation: str | None = None
            if (
                quantity_index + 1 < len(rows)
                and _is_numeric_continuation(str(rows[quantity_index]["text"]))
                and _parse_quantity_row(str(rows[quantity_index + 1]["text"])) is not None
            ):
                continuation = str(rows[quantity_index]["text"]).strip()
                quantity_index += 1
            quantity_row = _parse_quantity_row(str(rows[quantity_index]["text"])) if quantity_index < len(rows) else None
            if quantity_row is not None:
                parsed_quantity, unit_cost = quantity_row
                name = item_header["name"]
                if continuation:
                    name = f"{name} {continuation}"
                line_total = item_header["line_total"] or _quantized(parsed_quantity * unit_cost, Decimal("0.01"))
                raw_text = " ".join(
                    part
                    for part in (row_text, continuation, str(rows[quantity_index]["text"]))
                    if part
                )
                confidence = _confidence((row["confidence"] + rows[quantity_index]["confidence"]) / Decimal("2"))
                parsed_lines.append(
                    OCRReceiptLine(
                        raw_text=raw_text[:500],
                        name=name[:160],
                        quantity=parsed_quantity,
                        unit_cost=unit_cost,
                        line_total=line_total or Decimal("0.00"),
                        confidence=confidence,
                    )
                )
                index = quantity_index + 1
                continue
            if row_text and not _is_metadata_text(row_text):
                unparsed_rows.append(row_text)
            index += 1
            continue

        parsed = _parse_paddle_line(row_text, row["confidence"])
        if parsed is None:
            if row_text and not _is_metadata_text(row_text):
                unparsed_rows.append(row_text)
        else:
            parsed_lines.append(parsed)
        index += 1
    return parsed_lines, unparsed_rows


def _parse_paddle_item_header(text: str) -> dict[str, Any] | None:
    if _is_metadata_text(text) or _parse_quantity_row(text) is not None:
        return None
    match = _ITEM_HEADER_RE.match(text)
    if match is None:
        return None
    body = match.group(2).strip()
    matches = list(_NUMBER_RE.finditer(body))
    line_total: Decimal | None = None
    name = body
    if matches:
        last = matches[-1]
        candidate = _decimal(last.group(1))
        token = last.group(1)
        if candidate is not None and ("." in token or len(matches) > 1):
            line_total = _quantized(candidate, Decimal("0.01"))
            name = body[: last.start()]
    name = re.sub(r"^[\s|:#*.-]+|[\s|:#*.-]+$", "", name).strip()
    if not name or _is_metadata_text(name):
        return None
    return {"name": name, "line_total": line_total}


def _parse_quantity_row(text: str) -> tuple[Decimal, Decimal] | None:
    match = _QTY_ROW_RE.match(text)
    if match is None:
        return None
    parsed_quantity = _quantized(_decimal(match.group(1)), Decimal("0.001"))
    unit_cost = _quantized(_decimal(match.group(2)), Decimal("0.01"))
    if parsed_quantity is None or unit_cost is None or parsed_quantity <= 0 or unit_cost < 0:
        return None
    return parsed_quantity, unit_cost


def _is_numeric_continuation(text: str) -> bool:
    return bool(re.fullmatch(r"\s*\d{1,5}(?:\.\d+)?\s*", text))


def _is_metadata_text(text: str) -> bool:
    return bool(
        _METADATA_RE.search(text)
        or _DATE_LIKE_RE.search(text)
        or _METADATA_PREFIX_RE.search(text)
        or _parse_quantity_row(text) is not None
        or text.strip().startswith("#")
    )


def _parse_paddle_line(text: str, confidence: Decimal) -> OCRReceiptLine | None:
    if _is_metadata_text(text):
        return None
    matches = list(_NUMBER_RE.finditer(text))
    if len(matches) < 3:
        return None
    selected = matches[-3:]
    name = re.sub(r"^[\s|:#*.-]+|[\s|:#*.-]+$", "", text[: selected[0].start()]).strip()
    if not name or _METADATA_RE.search(name):
        return None
    quantity = _quantized(_decimal(selected[0].group(1)), Decimal("0.001"))
    unit_cost = _quantized(_decimal(selected[1].group(1)), Decimal("0.01"))
    line_total = _quantized(_decimal(selected[2].group(1)), Decimal("0.01"))
    if quantity is None or unit_cost is None or line_total is None or quantity <= 0 or unit_cost < 0 or line_total < 0:
        return None
    return OCRReceiptLine(
        raw_text=text[:500],
        name=name[:160],
        quantity=quantity,
        unit_cost=unit_cost,
        line_total=line_total,
        confidence=_confidence(confidence),
    )


def _extract_total(rows: list[tuple[str, Decimal]]) -> Decimal | None:
    for text, _ in reversed(rows):
        if not re.search(r"\b(?:grand\s+)?total\b|\bamount\s+due\b", text, re.IGNORECASE):
            continue
        matches = list(_NUMBER_RE.finditer(text))
        if matches:
            return _quantized(_decimal(matches[-1].group(1)), Decimal("0.01"))
    return None


def _extract_merchant(rows: list[tuple[str, Decimal]]) -> str | None:
    for text, _ in rows[:5]:
        if text and _parse_paddle_line(text, Decimal("1")) is None and _parse_paddle_item_header(text) is None and not _is_metadata_text(text):
            return text[:160]
    return None


def _extract_receipt_number(rows: list[tuple[str, Decimal]]) -> str | None:
    pattern = re.compile(r"\b(?:receipt|invoice|or)\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{2,})\b", re.IGNORECASE)
    for text, _ in rows:
        match = pattern.search(text)
        if match:
            return match.group(1)[:80]
        hash_match = re.search(r"#\s*([A-Z0-9][A-Z0-9-]{2,})\b", text, re.IGNORECASE)
        if hash_match:
            return hash_match.group(1)[:80]
    return None


def _first_result_mapping(raw_results: Any) -> Mapping[str, Any]:
    values = raw_results if isinstance(raw_results, (list, tuple)) else [raw_results]
    for value in values:
        mapping = _result_mapping(value)
        if mapping:
            return mapping
    return {}


def _result_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        mapping: Mapping[str, Any] = value
    else:
        try:
            serialized = getattr(value, "json")
            serialized = serialized() if callable(serialized) else serialized
            if isinstance(serialized, str):
                serialized = json.loads(serialized)
            mapping = serialized if isinstance(serialized, Mapping) else {}
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            mapping = {}
    nested = mapping.get("res") if isinstance(mapping, Mapping) else None
    return nested if isinstance(nested, Mapping) else mapping


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    try:
        converted = value.tolist()
    except AttributeError:
        return []
    return converted if isinstance(converted, list) else [converted]


def _plain_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    try:
        return _plain_value(value.tolist())
    except AttributeError:
        return str(value)


def _box_bounds(box: Any) -> tuple[float, float, float, float] | None:
    value = _plain_value(box)
    if not isinstance(value, list) or len(value) < 4:
        return None
    if all(isinstance(item, (int, float)) for item in value[:4]):
        x1, y1, x2, y2 = (float(item) for item in value[:4])
        return x1, y1, x2, y2
    points = [point for point in value if isinstance(point, list) and len(point) >= 2]
    if len(points) < 2:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    cleaned = str(value or "").replace(",", "").strip()
    if not cleaned:
        return default
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return default


def _confidence(value: Any) -> Decimal:
    parsed = _decimal(value, Decimal("0.5")) or Decimal("0.5")
    if not parsed.is_finite():
        parsed = Decimal("0.5")
    return _quantized(min(max(parsed, Decimal("0")), Decimal("1")), Decimal("0.0001"))


def _quantized(value: Decimal | None, scale: Decimal, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    return value.quantize(scale, rounding=ROUND_HALF_UP)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def build_provider() -> OCRProvider:
    configured = os.getenv("OCR_GATEWAY_PROVIDER")
    provider = (configured if configured is not None and configured.strip() else os.getenv("OCR_PROVIDER", "mock")).strip().lower()
    cache_key = provider
    with _PROVIDER_CACHE_LOCK:
        cached = _PROVIDER_CACHE.get(cache_key)
        if cached is not None:
            return cached
        if provider in {"mock", "local"}:
            instance: OCRProvider = MockOCRProvider()
        elif provider in {"paddle", "paddleocr", "paddleocr_ppocrv4", "gateway"}:
            instance = PaddleOCRProvider()
        else:
            raise ProviderError("provider_not_configured", f"Unsupported OCR provider: {provider}", 503)
        _PROVIDER_CACHE[cache_key] = instance
        return instance
