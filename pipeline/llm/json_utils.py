import json
import re
from typing import Any

_OPEN_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*")
_CLOSE_FENCE_RE = re.compile(r"\s*```\s*$")


def strip_markdown_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = _OPEN_FENCE_RE.sub("", text)
        text = _CLOSE_FENCE_RE.sub("", text)
    return text.strip()


def parse_llm_json(raw: str) -> Any:
    """Parse JSON from an LLM reply, tolerating ```json fences and surrounding prose.

    Raises json.JSONDecodeError when no JSON object can be recovered.
    """
    text = strip_markdown_fences(raw)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Last resort: grab the outermost {...} block from a prose-wrapped reply.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("no JSON object found in LLM response", text or "", 0)
