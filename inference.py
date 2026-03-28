import time
import logging
from dataclasses import dataclass
from typing import List, Tuple, Optional

import numpy as np
import onnxruntime as ort
from PIL import Image

from domain.classes import CLASS_COLORS, CLASS_NAMES

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    class_name: str
    class_id: int
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    color: str


def letterbox(
    image: Image.Image,
    target_size: int = 480,
) -> Tuple[np.ndarray, dict]:
    """Resize with padding to maintain aspect ratio."""
    orig_w, orig_h = image.size
    scale = min(target_size / orig_w, target_size / orig_h)
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)

    resized = image.resize((new_w, new_h), Image.BILINEAR)
    padded = Image.new("RGB", (target_size, target_size), (114, 114, 114))
    pad_x = (target_size - new_w) // 2
    pad_y = (target_size - new_h) // 2
    padded.paste(resized, (pad_x, pad_y))

    arr = np.array(padded, dtype=np.float32) / 255.0  # normalize [0,1]
    arr = arr.transpose(2, 0, 1)[np.newaxis, ...]     # (1, 3, target_size, target_size)

    scale_info = {
        "orig_w": orig_w, "orig_h": orig_h,
        "scale": scale, "pad_x": pad_x, "pad_y": pad_y,
    }
    return arr, scale_info


class ONNXInference:
    """Singleton ONNX inference wrapper for the SmartBin YOLO model."""

    def __init__(self, model_path: str):
        t0 = time.time()
        self.session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        elapsed = (time.time() - t0) * 1000
        logger.info(f"ONNX model loaded in {elapsed:.0f}ms from {model_path}")

    def preprocess(self, pil_image: Image.Image) -> Tuple[np.ndarray, dict]:
        rgb = pil_image.convert("RGB")
        return letterbox(rgb)

    def postprocess(
        self,
        output: np.ndarray,
        scale_info: dict,
        conf_thresh: float,
        iou_thresh: float,
    ) -> List[Detection]:
        """
        Model output: (300, 6) — already post-processed by the model.
        Each row: [x1, y1, x2, y2, confidence, class_id]
        Coordinates are in 640x640 letterboxed space.
        """
        preds = output   # (300, 6)

        confidences = preds[:, 4]
        mask = confidences >= conf_thresh
        if not mask.any():
            return []

        preds = preds[mask]
        detections = []
        s = scale_info
        for row in preds:
            x1, y1, x2, y2, conf, cid = row
            bx1 = int((x1 - s["pad_x"]) / s["scale"])
            by1 = int((y1 - s["pad_y"]) / s["scale"])
            bx2 = int((x2 - s["pad_x"]) / s["scale"])
            by2 = int((y2 - s["pad_y"]) / s["scale"])

            bx1 = max(0, min(bx1, s["orig_w"]))
            by1 = max(0, min(by1, s["orig_h"]))
            bx2 = max(0, min(bx2, s["orig_w"]))
            by2 = max(0, min(by2, s["orig_h"]))

            cid  = int(cid)
            name = CLASS_NAMES[cid] if cid < len(CLASS_NAMES) else "Unknown"
            detections.append(Detection(
                class_name=name,
                class_id=cid,
                confidence=float(conf),
                x1=bx1, y1=by1, x2=bx2, y2=by2,
                color=CLASS_COLORS.get(name, "#ffffff"),
            ))

        return detections

    def predict(
        self,
        pil_image: Image.Image,
        conf: float,
        iou: float,
    ) -> Tuple[List[Detection], int]:
        """Returns (detections, inference_ms)."""
        arr, scale_info = self.preprocess(pil_image)
        t0 = time.time()
        output = self.session.run(None, {self.input_name: arr})
        inference_ms = int((time.time() - t0) * 1000)
        detections = self.postprocess(output[0][0], scale_info, conf, iou)
        return detections, inference_ms


# Module-level singleton — loaded once at startup
_model_instance: Optional[ONNXInference] = None


def get_model() -> ONNXInference:
    global _model_instance
    if _model_instance is None:
        raise RuntimeError("Model not initialized. Call init_model() first.")
    return _model_instance


def init_model(model_path: str) -> ONNXInference:
    global _model_instance
    _model_instance = ONNXInference(model_path)
    return _model_instance
