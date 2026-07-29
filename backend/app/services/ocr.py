import os

import easyocr

_reader: easyocr.Reader | None = None


def get_reader() -> easyocr.Reader:
    global _reader
    if _reader is None:
        # Loaded once per worker process and reused across jobs.
        _reader = easyocr.Reader(["en"], gpu=False)
    return _reader


def ocr_frame(frame_path: str) -> list[dict]:
    reader = get_reader()
    detections = reader.readtext(frame_path)

    events = []
    for _bbox, text, confidence in detections:
        events.append({
            "text": text,
            "confidence": float(confidence),
            "frame": os.path.basename(frame_path),
        })
    return events
