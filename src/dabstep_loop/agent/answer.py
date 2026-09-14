"""Pull the answer out of the agent's final text. The contract is `{"agent_answer": ...}`."""

from __future__ import annotations

import json
import re

_JSON_STR = re.compile(r'\{\s*"agent_answer"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}', re.S)
_JSON_ANY = re.compile(r'\{\s*"agent_answer"\s*:\s*(.+?)\s*\}', re.S)


def extract_agent_answer(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    # A fenced block first, if the model wrapped it.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    m = _JSON_STR.search(text)
    if m:
        try:
            return str(json.loads(f'"{m.group(1)}"')).strip()
        except json.JSONDecodeError:
            return m.group(1).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "agent_answer" in parsed:
            v = parsed["agent_answer"]
            return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v).strip()
    except (json.JSONDecodeError, TypeError):
        pass
    m = _JSON_ANY.search(text)
    if m:
        return m.group(1).strip().strip('"')
    return text
