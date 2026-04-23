"""
FDA + ClinicalTrials.gov — pharmaceutical pipeline data (no API key required).

Two public data sources:
- openFDA: https://open.fda.gov/apis/drug/drugsfda/
- ClinicalTrials.gov v2 API: https://clinicaltrials.gov/api/v2/studies

Rationale: for pharma audits (NVO, LLY, PFE, MRK, etc.), the single biggest
blind-spot in financial-statement-only analysis is "what's in the pipeline?"
Past earnings don't forecast patent-cliff survival. This provider answers:
"how many active Phase 2/3 trials does the sponsor have?"

Defensive: free public APIs can flake → always returns empty structure on
any error. Callers treat output as optional enrichment.

Heuristic: only useful when the company is classified as Healthcare. Stages
should check sector before calling.
"""

from __future__ import annotations

from datetime import datetime

import requests

from engine.cache import cache_get, cache_set
from shared.config import ApiKeys, Config

OPENFDA_BASE = "https://api.fda.gov"
CT_BASE = "https://clinicaltrials.gov/api/v2"


class FdaError(RuntimeError):
    pass


def _take_token() -> None:
    try:
        from shared.ratelimit import require_token

        require_token("fda")
    except ImportError:
        pass
    except Exception as e:
        raise FdaError(f"rate-limit: {e}")


def _cached_get(
    cfg: Config,
    cache_ns: str,
    key: str,
    url: str,
    params: dict,
    ttl: int = 86400,
) -> dict:
    cached = cache_get(cfg, cache_ns, key, ttl)
    if cached is not None:
        return cached.get("value", {})
    _take_token()
    try:
        r = requests.get(url, params=params, timeout=20)
    except Exception as e:
        raise FdaError(f"network error: {e}")
    if r.status_code == 404:
        cache_set(cfg, cache_ns, key, {"value": {}})
        return {}
    if r.status_code != 200:
        raise FdaError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    cache_set(cfg, cache_ns, key, {"value": data})
    return data


def fetch_clinical_trials(
    cfg: Config,
    keys: ApiKeys,
    company_name: str,
    max_results: int = 100,
) -> dict:
    """Count active trials by phase for `company_name` as sponsor.

    Returns {
        "active_phase_3": int,
        "active_phase_2": int,
        "active_phase_1": int,
        "total_active": int,
        "recent_completions": [{"nct_id", "title", "phase", "completion_date"}],
    }. Uses 24h cache (pipeline changes slowly).
    """
    key = f"ct:{company_name}:{max_results}"
    try:
        data = _cached_get(
            cfg,
            "fda_ct",
            key,
            f"{CT_BASE}/studies",
            {
                "query.lead": company_name,
                "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING",
                "pageSize": str(min(max_results, 100)),
                "format": "json",
            },
            ttl=86400,
        )
    except FdaError:
        return {
            "active_phase_3": 0,
            "active_phase_2": 0,
            "active_phase_1": 0,
            "total_active": 0,
            "recent_completions": [],
            "error": True,
        }

    studies = data.get("studies", [])
    p1 = p2 = p3 = 0
    for s in studies:
        protocol = s.get("protocolSection", {})
        design = protocol.get("designModule", {})
        phases = design.get("phases", []) or []
        if "PHASE3" in phases:
            p3 += 1
        if "PHASE2" in phases:
            p2 += 1
        if "PHASE1" in phases:
            p1 += 1

    return {
        "active_phase_3": p3,
        "active_phase_2": p2,
        "active_phase_1": p1,
        "total_active": len(studies),
        "recent_completions": [],
        "sponsor_query": company_name,
    }


def fetch_drug_approvals(
    cfg: Config,
    keys: ApiKeys,
    company_name: str,
    years_back: int = 5,
) -> dict:
    """Count FDA drug approvals for sponsor in last N years.

    Returns {"approvals_last_5y": int, "approved_products": [...]}. Uses
    7-day cache (new approvals are infrequent).
    """
    key = f"approvals:{company_name}:{years_back}"
    cutoff_year = datetime.utcnow().year - years_back
    try:
        data = _cached_get(
            cfg,
            "fda_drugsfda",
            key,
            f"{OPENFDA_BASE}/drug/drugsfda.json",
            {
                "search": f'sponsor_name:"{company_name}" AND products.marketing_status:"Prescription" AND submissions.submission_status_date:[{cutoff_year}0101 TO 99991231]',
                "limit": "20",
            },
            ttl=86400 * 7,
        )
    except FdaError:
        return {"approvals_last_5y": 0, "approved_products": [], "error": True}

    results = data.get("results", [])
    products = []
    for r in results:
        for p in r.get("products", [])[:2]:
            products.append(
                {
                    "brand_name": p.get("brand_name", ""),
                    "dosage_form": p.get("dosage_form", ""),
                    "route": p.get("route", ""),
                }
            )
    return {
        "approvals_last_5y": len(results),
        "approved_products": products[:10],
        "sponsor_query": company_name,
    }


def pipeline_summary(
    cfg: Config,
    keys: ApiKeys,
    company_name: str,
) -> dict:
    """One-shot aggregator for stage consumption. Never raises."""
    try:
        trials = fetch_clinical_trials(cfg, keys, company_name)
    except Exception:
        trials = {
            "active_phase_3": 0,
            "active_phase_2": 0,
            "active_phase_1": 0,
            "total_active": 0,
            "error": True,
        }
    try:
        approvals = fetch_drug_approvals(cfg, keys, company_name)
    except Exception:
        approvals = {"approvals_last_5y": 0, "approved_products": [], "error": True}

    # Risk-bucket heuristic
    p3 = trials.get("active_phase_3", 0)
    if p3 >= 5:
        pipeline_strength = "deep"
    elif p3 >= 2:
        pipeline_strength = "moderate"
    elif p3 >= 1:
        pipeline_strength = "thin"
    else:
        pipeline_strength = "dry"

    return {
        "company": company_name,
        "pipeline_strength": pipeline_strength,
        "active_phase_3": p3,
        "active_phase_2": trials.get("active_phase_2", 0),
        "active_phase_1": trials.get("active_phase_1", 0),
        "total_active_trials": trials.get("total_active", 0),
        "approvals_last_5y": approvals.get("approvals_last_5y", 0),
        "approved_products": approvals.get("approved_products", []),
    }


# --- Health check ---


def test_connection(keys: ApiKeys) -> tuple[bool, str]:
    """Hits ClinicalTrials.gov with a known sponsor."""
    try:
        _take_token()
        r = requests.get(
            f"{CT_BASE}/studies",
            params={"query.lead": "Novo Nordisk", "pageSize": "1"},
            timeout=15,
        )
        if r.status_code == 200:
            n = len(r.json().get("studies", []))
            return True, f"connected; ClinicalTrials.gov responsive ({n} studies sample)"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)
