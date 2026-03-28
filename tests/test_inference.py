import numpy as np
import pytest
from PIL import Image

import inference
from inference import Detection, letterbox


def test_letterbox_output_shape():
    img = Image.new("RGB", (640, 480))
    arr, scale_info = letterbox(img, target_size=480)
    assert arr.shape == (1, 3, 480, 480)
    assert arr.dtype == np.float32


def test_letterbox_scale_info():
    img = Image.new("RGB", (640, 480))
    _, info = letterbox(img, target_size=480)
    assert "orig_w" in info
    assert "orig_h" in info
    assert "scale" in info
    assert "pad_x" in info
    assert "pad_y" in info
    assert info["orig_w"] == 640
    assert info["orig_h"] == 480


def test_letterbox_square_image():
    img = Image.new("RGB", (480, 480))
    arr, info = letterbox(img, target_size=480)
    assert info["pad_x"] == 0
    assert info["pad_y"] == 0
    assert info["scale"] == 1.0


def test_detection_dataclass():
    det = Detection(
        class_name="Plastic",
        class_id=0,
        confidence=0.95,
        x1=10, y1=20, x2=100, y2=200,
        color="#1E90FF",
    )
    assert det.class_name == "Plastic"
    assert det.confidence == 0.95


def test_get_model_raises_before_init():
    old = inference._model_instance
    inference._model_instance = None
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            inference.get_model()
    finally:
        inference._model_instance = old
