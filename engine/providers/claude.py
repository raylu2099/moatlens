"""
Anthropic Claude provider — the analyst brain.

Two levels of invocation:
- analyze(): standard audit stage analysis (model: sonnet-4-5)
- analyze_cheap(): lightweight extraction (model: haiku-4-5)

Uses Anthropic Python SDK for robustness (vs raw HTTP).
Tracks cost automatically from response usage.

Pricing (as of 2026-04): Sonnet-4-5 $3/Mtok input, $15/Mtok output.
Haiku-4-5 $1/Mtok input, $5/Mtok output.
"""
from __future__ import annotations

import sys

from anthropic import Anthropic

from shared.config import ApiKeys, Config


# Rough pricing per M tokens (USD) — update as pricing changes
PRICING = {
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-opus-4-5": {"input": 15.0, "output": 75.0},
}


def _estimate_cost(model: str, input_tok: int, output_tok: int) -> float:
    p = PRICING.get(model, {"input": 3.0, "output": 15.0})
    return (input_tok * p["input"] + output_tok * p["output"]) / 1_000_000


def analyze(
    cfg: Config,
    keys: ApiKeys,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    max_tokens: int = 4000,
) -> tuple[str, float]:
    """
    Call Claude with a system+user prompt. Returns (text, cost_usd).
    """
    if not keys.anthropic:
        return "[ANTHROPIC_API_KEY missing — cannot analyze]", 0.0

    m = model or cfg.claude_model
    client = Anthropic(api_key=keys.anthropic)

    try:
        response = client.messages.create(
            model=m,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        print(f"[claude] error: {e}", file=sys.stderr)
        return f"[Claude error: {e}]", 0.0

    parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    text = "\n".join(parts).strip()

    usage = response.usage
    cost = _estimate_cost(m, usage.input_tokens, usage.output_tokens)

    return text, cost


def analyze_cheap(
    cfg: Config,
    keys: ApiKeys,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
) -> tuple[str, float]:
    """Haiku model for quick extraction tasks."""
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
