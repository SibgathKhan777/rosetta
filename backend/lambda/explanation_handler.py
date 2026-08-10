"""AWS Lambda handler for the explanation-generation step.

Deliberately does NOT import from backend/app/ — that package's
requirements.txt pulls in faster-whisper/rapidocr/onnxruntime/opencv, none
of which this step needs, and Lambda can't cheaply bundle them anyway. This
is a self-contained duplicate of app/services/explanation.py's prompt and
retry logic. If you change the prompt or fallback behavior there, mirror it
here manually — there is no shared import between the two.

Event (RequestResponse invoke payload):
    {"title": str, "transcript": str, "ocr_text": str}
Response:
    {"explanation": str}   # "" on any internal failure — never raises,
                            # matching generate_explanation()'s contract.
"""
import os
import re

from openai import OpenAI

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

VISION_LLM_API_KEY = os.environ["VISION_LLM_API_KEY"]
VISION_LLM_BASE_URL = os.environ.get("VISION_LLM_BASE_URL", "https://api.groq.com/openai/v1")
VISION_LLM_MODEL = os.environ.get("VISION_LLM_MODEL", "qwen/qwen3.6-27b")
FALLBACK_LLM_API_KEY = os.environ.get("FALLBACK_LLM_API_KEY", "")
FALLBACK_LLM_BASE_URL = os.environ.get("FALLBACK_LLM_BASE_URL", "https://openrouter.ai/api/v1")
FALLBACK_LLM_MODEL = os.environ.get("FALLBACK_LLM_MODEL", "openai/gpt-oss-20b:free")
EXPLANATION_MAX_INPUT_CHARS = int(os.environ.get("EXPLANATION_MAX_INPUT_CHARS", "12000"))
EXPLANATION_MAX_TOKENS = int(os.environ.get("EXPLANATION_MAX_TOKENS", "4096"))

# Copied verbatim from app/services/explanation.py — keep in sync manually.
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

_client = None
_fallback_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=VISION_LLM_API_KEY, base_url=VISION_LLM_BASE_URL)
    return _client


def _get_fallback_client() -> OpenAI:
    global _fallback_client
    if _fallback_client is None:
        _fallback_client = OpenAI(api_key=FALLBACK_LLM_API_KEY, base_url=FALLBACK_LLM_BASE_URL)
    return _fallback_client


def _raw_completion(messages: list, max_tokens: int) -> str:
    try:
        response = _get_client().chat.completions.create(
            model=VISION_LLM_MODEL, messages=messages, max_tokens=max_tokens
        )
        return response.choices[0].message.content or ""
    except Exception:
        if not FALLBACK_LLM_API_KEY:
            raise
        response = _get_fallback_client().chat.completions.create(
            model=FALLBACK_LLM_MODEL, messages=messages, max_tokens=max_tokens
        )
        return response.choices[0].message.content or ""


def handler(event, context):
    title = event.get("title") or "(untitled)"
    transcript = (event.get("transcript") or "(no speech transcribed)")[:EXPLANATION_MAX_INPUT_CHARS]
    ocr_text = (event.get("ocr_text") or "(no on-screen text detected)")[:EXPLANATION_MAX_INPUT_CHARS]
    prompt = PROMPT_TEMPLATE.format(title=title, transcript=transcript, ocr_text=ocr_text)
    try:
        raw = _raw_completion([{"role": "user", "content": prompt}], EXPLANATION_MAX_TOKENS)
        if "<think>" in raw and "</think>" not in raw:
            return {"explanation": ""}
        return {"explanation": _THINK_BLOCK_RE.sub("", raw).strip()}
    except Exception:
        return {"explanation": ""}
