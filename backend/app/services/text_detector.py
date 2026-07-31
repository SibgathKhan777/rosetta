import os
import threading
import urllib.request

import cv2

from app.core.config import settings

_net = None
_lock = threading.Lock()

# Standard EAST output layers: per-pixel "is this text" confidence map, and
# the geometry map (unused here — we only need presence, not bounding boxes).
_OUTPUT_LAYERS = ["feature_fusion/Conv_7/Sigmoid", "feature_fusion/concat_3"]


def _ensure_model() -> str:
    path = settings.east_model_path
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.download"
    urllib.request.urlretrieve(settings.east_model_url, tmp_path)
    os.replace(tmp_path, path)
    return path


def _get_net() -> cv2.dnn.Net:
    global _net
    if _net is None:
        with _lock:
            if _net is None:
                _net = cv2.dnn.readNet(_ensure_model())
    return _net


def has_text(image_path: str) -> bool:
    """EAST-based text-region presence check. Used as a pre-filter on
    densely-sampled candidate frames: cheap (no API cost, no OCR) yes/no
    signal for "does this frame contain readable text at all", so OCR and
    vision-LLM escalation only ever see frames worth reading.
    """
    image = cv2.imread(image_path)
    if image is None:
        return False

    # Fixed size regardless of source resolution — EAST's own accuracy
    # doesn't depend on native resolution for a presence check, but CPU cost
    # does: full-res inference measured ~5.3s/frame vs ~0.3s/frame at 320x320.
    size = settings.east_input_size
    resized = cv2.resize(image, (size, size))

    blob = cv2.dnn.blobFromImage(
        resized,
        1.0,
        (size, size),
        (123.68, 116.78, 103.94),
        swapRB=True,
        crop=False,
    )
    net = _get_net()
    net.setInput(blob)
    scores, _geometry = net.forward(_OUTPUT_LAYERS)

    return bool((scores > settings.text_detection_confidence).any())
