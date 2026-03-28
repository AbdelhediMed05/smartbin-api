import hashlib
import io
import uuid
from datetime import datetime, timezone
from typing import Tuple

import magic
from PIL import Image


ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_DIMENSION = 4096


def validate_image(data: bytes, filename: str) -> Tuple[bool, str]:
    """Full image security validation pipeline."""
    # 1. MIME type via magic bytes
    mime = magic.from_buffer(data, mime=True)
    if mime not in ALLOWED_MIME_TYPES:
        return False, f"Invalid file type: {mime}. Only JPEG, PNG, WebP allowed."

    # 2. PIL verify (rejects malformed/polyglot files)
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception:
        return False, "File is corrupt or not a valid image."

    # 3. Re-open to check dimensions (verify() closes the image)
    try:
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w > MAX_DIMENSION or h > MAX_DIMENSION:
            return False, f"Image too large: {w}x{h}. Maximum {MAX_DIMENSION}x{MAX_DIMENSION}."
    except Exception:
        return False, "Could not read image dimensions."

    return True, "ok"


def hash_ip(ip: str) -> str:
    """SHA256 hash of IP, truncated to 16 chars. Never store raw IPs."""
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def sanitize_filename(ext: str = "jpg") -> str:
    """Generate a safe filename: {timestamp}_{uuid8}.ext — no PII."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    uid = str(uuid.uuid4()).replace("-", "")[:8]
    return f"{ts}_{uid}.{ext}"


def strip_exif(pil_image: Image.Image) -> Image.Image:
    """
    Remove EXIF by re-encoding through a JPEG buffer.
    Uses quality=75 — same as predict_service save — so the intermediate
    is not wasted at a higher quality than the final stored copy.
    The buffer is explicitly closed after decode to release memory promptly.
    """
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=75)
    buf.seek(0)
    result = Image.open(buf).convert("RGB")
    result.load()   # force decode now so buf can be closed immediately
    buf.close()
    return result
