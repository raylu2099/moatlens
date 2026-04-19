"""
Perplexity search — qualitative research provider.

Model constraint: ONLY `sonar` and `sonar-pro`. Never `sonar-reasoning-pro`
or `sonar-deep-research` (too expensive for this use case).

Retries on transient errors (429/5xx/timeouts) with exponential backoff.
"""
from __future__ import annotations

import json
import sys
import time

import requests

from engine.cache import cache_get, cache_set
from shared.config import ApiKeys, Config


PPLX_ENDPOINT = "https://api.perplexity.ai/chat/completions"


class PerplexityError(RuntimeError):
    pass


def _call(
    keys: ApiKeys,
    prompt: str,
    model: str = "sonar",
    max_tokens: int = 600,
    recency: str | None = None,
    domain_filter: list[str] | None = None,
    max_retries: int = 2,
) -> dict:
    """HTTP call with retry. Returns a dict with either data or {"error": msg}."""
    if not keys.perplexity:
        return {"error": "PERPLEXITY_API_KEY missing"}

    # Rate-limit guard
    try:
        from shared.ratelimit import require_token
        require_token("perplexity")
    except ImportError:
        pass
    except Exception as e:
        return {"error": f"rate-limit: {e}"}

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "web_search_options": {"search_context_size": "high"},
    }
    if recency:
        body["search_recency_filter"] = recency
    if domain_filter:
        body["search_domain_filter"] = domain_filter

    last_err: str = ""
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(
                PPLX_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {keys.perplexity}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(body),
                timeout=60,
            )
            if r.status_code in (408, 429, 500, 502, 503, 504):
                last_err = f"HTTP {r.status_code}: {r.text[:150]}"
                if attempt < max_retries:
                    time.sleep(1.5 ** attempt)
                    continue
                return {"error": last_err}
            if r.status_code != 200:
                return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
            return r.json()
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < max_retries:
                time.sleep(1.5 ** attempt)
                continue
            print(f"[perplexity] {last_err}", file=sys.stderr)
            return {"error": last_err}
    return {"error": last_err or "unknown"}


def research(
    cfg: Config,
    keys: ApiKeys,
    prompt: str,
    model: str | None = None,
    max_tokens: int = 600,
    recency: str | None = "month",
    domain_filter: list[str] | None = None,
    cache_ns: str = "pplx_research",
) -> tuple[str, list[dict], float]:
    """
    Return (synthesized_answer, search_results, cost_usd).
    Cached per-prompt for `cache_perplexity_ttl`.
    """
    m = model or cfg.pplx_model_search
    cache_key = f"{m}|{prompt[:200]}|{recency}|{domain_filter}"
    cached = cache_get(cfg, cache_ns, cache_key, cfg.cache_perplexity_ttl)
    if cached is not None:
        return cached.get("answer", ""), cached.get("results", []), 0.0

    data = _call(
        keys, prompt, model=m, max_tokens=max_tokens,
        recency=recency, domain_filter=domain_filter,
    )
    if "error" in data:
        return f"[Perplexity error: {data['error']}]", [], 0.0

    answer = (
        data.get("choices", [{}])[0]
        .get("message", {}).get("content", "")
    ).strip()
    results = data.get("search_results", []) or []
    cost = float(data.get("usage", {}).get("cost", {}).get("total_cost", 0))

    # Log metrics — never raises
    try:
        from shared.metrics import log_cost
        log_cost(cfg, provider="perplexity", model=m, cost_usd=cost, tag=cache_ns)
    except Exception:
        pass

    cache_set(cfg, cache_ns, cache_key, {"answer": answer, "results": results})
    return answer, results, cost


def test_connection(keys: ApiKeys) -> tuple[bool, str]:
    if not keys.perplexity:
        return False, "PERPLEXITY_API_KEY not set"
    data = _call(keys, "Reply with exactly: OK", max_tokens=10, recency=None, max_retries=0)
    if "error" in data:
        return False, data["error"]
    choices = data.get("choices", [])
    if choices:
        return True, f"model {data.get('model')} responded"
    return False, "unexpected response shape"
