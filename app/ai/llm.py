"""Optional LLM access (Anthropic Messages API) using only the standard library.

Used only when ANTHROPIC_API_KEY is set. Any failure returns None and the offline assistant answers instead,
so the project never depends on the network."""
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("wallet.llm")
API_URL = "https://api.anthropic.com/v1/messages"


def ask_claude(system: str, user_text: str, *, api_key: str, model: str, max_tokens: int = 450, timeout: int = 20):
    if not api_key:
        return None
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": user_text}]}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        return text or None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        log.warning("LLM call failed (%s) - using the offline assistant", exc.__class__.__name__)
        return None
