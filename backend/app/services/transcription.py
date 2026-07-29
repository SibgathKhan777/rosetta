from faster_whisper import WhisperModel

from app.core.config import settings

_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        # Loaded once per worker process and reused across jobs.
        _model = WhisperModel(
            settings.whisper_model_size,
            device="cpu",
            compute_type=settings.whisper_compute_type,
        )
    return _model


def transcribe_audio(audio_path: str) -> tuple[str, list[dict]]:
    model = get_model()
    segments_iter, _info = model.transcribe(audio_path, beam_size=5)

    segments = []
    text_parts = []
    for seg in segments_iter:
        text = seg.text.strip()
        segments.append({"start": seg.start, "end": seg.end, "text": text})
        text_parts.append(text)

    return " ".join(text_parts).strip(), segments
