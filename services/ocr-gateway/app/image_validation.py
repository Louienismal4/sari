from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from .errors import GatewayError


ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIN_IMAGE_SIDE = 15
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_PIXELS = 20_000_000


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    content_type: str


def validate_and_normalize(data: bytes, content_type: str | None) -> ValidatedImage:
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type not in ALLOWED_MIME_TYPES:
        raise GatewayError("invalid_image_type", "Receipt must be a JPG, PNG, or WEBP image", 415)
    if not data:
        raise GatewayError("empty_image", "Receipt image is empty", 422)
    if len(data) > MAX_IMAGE_BYTES:
        raise GatewayError("payload_too_large", "Receipt image must be 10 MB or smaller", 413)

    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
                raise GatewayError("image_too_small", "Receipt image is too small to read", 422)
            if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
                raise GatewayError("image_too_large", "Receipt image dimensions are too large", 422)
            if width * height > MAX_IMAGE_PIXELS:
                raise GatewayError("image_too_large", "Receipt image has too many pixels", 422)
            image.verify()

        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                background.alpha_composite(rgba)
                image = background.convert("RGB")
            else:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return ValidatedImage(data=output.getvalue(), content_type="image/jpeg")
    except GatewayError:
        raise
    except Exception as exc:
        raise GatewayError("invalid_image", "Receipt image could not be decoded", 422) from exc
