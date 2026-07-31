import os

from rapidocr import RapidOCR

_engine: RapidOCR | None = None


def get_engine() -> RapidOCR:
    global _engine
    if _engine is None:
        # Loaded once per worker process and reused across jobs.
        _engine = RapidOCR()
    return _engine


def ocr_frame(frame_path: str) -> list[dict]:
    engine = get_engine()
    result = engine(frame_path)

    events = []
    if result.txts:
        for text, confidence in zip(result.txts, result.scores):
            events.append({
                "text": text,
                "confidence": float(confidence),
                "frame": os.path.basename(frame_path),
            })
    return events
