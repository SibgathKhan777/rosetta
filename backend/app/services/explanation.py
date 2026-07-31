import logging

from openai import OpenAI

from app.core.config import settings
from app.services.vision_llm import _THINK_BLOCK_RE, get_client
from app.services.vision_llm import is_enabled as is_enabled  # re-exported for callers

logger = logging.getLogger(__name__)

_fallback_client: OpenAI | None = None

PROMPT_TEMPLATE = """You are a patient teacher. A student just watched a video and wants you to \
explain it to them so they actually understand and could apply it themselves. Below is the \
video's spoken transcript and any on-screen text (code, terminal output, slides) that was \
captured from the video frames.

Write a clear, structured explanation aimed at someone learning this for the first time:
- What is this video about, in one or two sentences
- The key concepts it teaches, broken into steps or sections
- Any specific commands, code, or configuration shown on screen, explained in context
- A short takeaway of what the viewer should now be able to do

Title: {title}

Transcript:
{transcript}

On-screen text:
{ocr_text}
"""


def _get_fallback_client() -> OpenAI:
    global _fallback_client
    if _fallback_client is None:
        _fallback_client = OpenAI(api_key=settings.fallback_llm_api_key, base_url=settings.fallback_llm_base_url)
    return _fallback_client


def _raw_completion(messages: list, max_tokens: int) -> str:
    """Try the primary LLM (Groq) first; on any failure — most commonly
    Groq's free daily token quota being exhausted, confirmed to happen
    repeatedly under real usage — retry once via an OpenRouter free-tier
    model instead of giving up for the rest of the day.
    """
    try:
        response = get_client().chat.completions.create(
            model=settings.vision_llm_model, messages=messages, max_tokens=max_tokens
        )
        return response.choices[0].message.content or ""
    except Exception:
        if not settings.fallback_llm_api_key:
            raise
        logger.warning("Primary explanation LLM failed, retrying via OpenRouter fallback", exc_info=True)
        response = _get_fallback_client().chat.completions.create(
            model=settings.fallback_llm_model, messages=messages, max_tokens=max_tokens
        )
        return response.choices[0].message.content or ""


def generate_explanation(title: str, transcript: str, ocr_text: str) -> str:
    """Best-effort teaching explanation synthesized from the transcript and
    OCR text of a finished job. A failed call returns '' rather than failing
    the job — this is a value-add summary, not something the pipeline
    depends on.
    """
    limit = settings.explanation_max_input_chars
    prompt = PROMPT_TEMPLATE.format(
        title=title or "(untitled)",
        transcript=(transcript or "(no speech transcribed)")[:limit],
        ocr_text=(ocr_text or "(no on-screen text detected)")[:limit],
    )

    try:
        raw = _raw_completion([{"role": "user", "content": prompt}], settings.explanation_max_tokens)
        if "<think>" in raw and "</think>" not in raw:
            return ""
        return _THINK_BLOCK_RE.sub("", raw).strip()
    except Exception:
        return ""
