import io

from PIL import Image

from security import hash_ip, sanitize_filename, strip_exif, validate_image


def _make_jpeg(width=100, height=100):
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png(width=100, height=100):
    img = Image.new("RGB", (width, height), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_validate_image_accepts_jpeg():
    ok, reason = validate_image(_make_jpeg(), "test.jpg")
    assert ok is True
    assert reason == "ok"


def test_validate_image_accepts_png():
    ok, reason = validate_image(_make_png(), "test.png")
    assert ok is True


def test_validate_image_rejects_text():
    ok, reason = validate_image(b"this is not an image", "test.txt")
    assert ok is False
    assert "Invalid file type" in reason


def test_validate_image_rejects_oversized():
    ok, reason = validate_image(_make_jpeg(5000, 5000), "big.jpg")
    assert ok is False
    assert "too large" in reason


def test_hash_ip_consistent():
    h1 = hash_ip("192.168.1.1")
    h2 = hash_ip("192.168.1.1")
    assert h1 == h2
    assert len(h1) == 16


def test_hash_ip_different_ips():
    assert hash_ip("1.1.1.1") != hash_ip("8.8.8.8")


def test_sanitize_filename_format():
    name = sanitize_filename("jpg")
    assert name.endswith(".jpg")
    assert "_" in name


def test_strip_exif_returns_rgb():
    img = Image.new("RGB", (50, 50), color="green")
    result = strip_exif(img)
    assert result.mode == "RGB"
    assert result.size[0] > 0
