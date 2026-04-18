"""
Anthropic Claude provider — the analyst brain.

Two levels of invocation:
- analyze(): standard audit stage analysis (sonnet-4-5)
- analyze_cheap(): lightweight extraction (haiku-4-5)

Includes a small retry-with-backoff loop for transient failures (429/5xx/network).
Tracks cost automatically from response usage.
"""
from __future__ import annotations

import sys
import time

from anthropic import Anthropic, APIError, APIStatusError, APITimeoutError

from shared.config import ApiKeys, Config


PRICING = {
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-opus-4-5": {"input": 15.0, "output": 75.0},
}


class ClaudeError(RuntimeError):
    """Raised after retries are exhausted so stages can decide how to degrade."""


def _estimate_cost(model: str, input_tok: int, output_tok: int) -> float:
    p = PRICING.get(model, {"input": 3.0, "output": 15.0})
    return (input_tok * p["input"] + output_tok * p["output"]) / 1_000_000


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, APITimeoutError):
        return True
    if isinstance(exc, APIStatusError):
        code = getattr(exc, "status_code", None)
        return code in (408, 429, 500, 502, 503, 504)
    # Network-ish errors from underlying httpx
    name = type(exc).__name__.lower()
    return any(x in name for x in ("timeout", "connection", "remote"))


def analyze(
    cfg: Config,
    keys: ApiKeys,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    max_tokens: int = 4000,
    max_retries: int = 2,
    raise_on_error: bool = False,
) -> tuple[str, float]:
    """
    Call Claude with system+user prompts.
    Returns (text, cost_usd). On failure, returns an "[error: ...]" string
    unless raise_on_error=True, in which case ClaudeError is raised.
    """
    if not keys.anthropic:
        if raise_on_error:
            raise ClaudeError("ANTHROPIC_API_KEY missing")
        return "[ANTHROPIC_API_KEY missing — cannot analyze]", 0.0

    m = model or cfg.claude_model
    client = Anthropic(api_key=keys.anthropic)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.messages.create(
                model=m,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
            text = "\n".join(parts).strip()
            usage = response.usage
            cost = _estimate_cost(m, usage.input_tokens, usage.output_tokens)
            return text, cost

        except Exception as e:  # noqa: BLE001
            last_exc = e
            retryable = _is_retryable(e)
            if attempt < max_retries and retryable:
                sleep_s = 1.5 ** attempt  # 1, 1.5, 2.25 ...
                print(
                    f"[claude] attempt {attempt + 1} failed ({type(e).__name__}), "
                    f"retrying in {sleep_s:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(sleep_s)
                continue
            break

    if raise_on_error:
        raise ClaudeError(str(last_exc)) from last_exc
    print(f"[claude] giving up: {last_exc}", file=sys.stderr)
    return f"[Claude error: {last_exc}]", 0.0


def analyze_cheap(
    cfg: Config,
    keys: ApiKeys,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
) -> tuple[str, float]:
    return analyze(
        cfg, keys, system_prompt, user_prompt,
        model="claude-haiku-4-5", max_tokens=max_tokens,
    )


def test_connection(keys: ApiKeys) -> tuple[bool, str]:
    if not keys.anthropic:
        return False, "ANTHROPIC_API_KEY not set"
    try:
        client = Anthropic(api_key=keys.anthropic)
        r = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=20,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        )
        text = "".join(b.text for b in r.content if hasattr(b, "text"))
        return "OK" in text.upper(), f"haiku responded: {text[:30]}"
    except Exception as e:
        return False, str(e)[:150]
