import base64
import re

from openai import OpenAI

from app.core.config import settings

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_client: OpenAI | None = None

PROMPT = (
    "Transcribe any on-screen text visible in this video frame. "
    "Reply with just the text, or NONE if there is no readable text."
)


def is_enabled() -> bool:
    return bool(settings.vision_llm_api_key)


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.vision_llm_api_key, base_url=settings.vision_llm_base_url)
    return _client


def escalate_frame(image_path: str) -> str:
    """Second-pass on-screen text extraction for a frame OCR judged low-confidence
    or empty. Best-effort: a failed call returns '' rather than failing the job —
    this is a bounded quality improvement, not something the pipeline depends on.
    """
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    try:
        response = get_client().chat.completions.create(
            model=settings.vision_llm_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
            # Generous budget: reasoning models (e.g. Qwen3) inline their
            # chain-of-thought directly in content wrapped in <think>...</think>
            # rather than a separate field, and a busy frame (a code editor,
            # say) needs real room to both reason through it and still emit an
            # answer afterward. Confirmed directly: 300 was too tight and
            # truncated mid-reasoning on text-heavy frames, well before the
            # closing </think>.
            max_tokens=2048,
        )
        raw = response.choices[0].message.content or ""
        if "<think>" in raw and "</think>" not in raw:
            # Truncated mid-reasoning (hit max_tokens before finishing) — the
            # model never got to its actual answer, so there's nothing usable
            # here. Treat as a failed escalation rather than store raw
            # chain-of-thought as if it were transcribed text.
            return ""
        text = _THINK_BLOCK_RE.sub("", raw).strip()
        return "" if text.upper() == "NONE" else text
    except Exception:
        return ""
