"""
Guardrails for Claude JSON outputs.

Each stage that invokes Claude (s3 moat, s4 capital, s8 inversion) expects a
specific JSON shape. When Claude drifts (returns strings for ints, adds extra
keys, forgets required fields), parsing can produce garbage that downstream
code uses for verdict/metric calculations.

These pydantic models define the contract. `parse_claude_json(text, schema)`:
1. Extracts JSON from ```json fences or bare `{...}` blob
2. Validates against the pydantic model
3. On failure, returns a partial dict with whatever validated + `_parse_errors`

This is a defense-in-depth layer. It's OK for Claude to sometimes fail this —
stages already degrade gracefully (they keep `claude_output_raw` for forensics).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class MoatAnalysis(BaseModel):
    """Expected shape for Stage 3 (moat) Claude output."""

    total_score: int = Field(default=0, ge=0, le=100)
    moat_scores: dict[str, int] = Field(default_factory=dict)
    strongest_moats: list[str] = Field(default_factory=list)
    strongest_evidence: str = ""
    weakest_link: str = ""
    tech_moat_trend: str = ""
    tech_moat_evidence: str = ""
    lollapalooza: bool = False
    business_model_checks: dict[str, bool] = Field(default_factory=dict)
    business_model_score: int = Field(default=0, ge=0, le=11)
    summary_cn: str = ""
    munger_verdict: str = ""


class ManagementAnalysis(BaseModel):
    """Expected shape for Stage 4 (management) Claude output."""

    integrity_score: int = Field(default=0, ge=0, le=20)
    capital_allocation_score: int = Field(default=0, ge=0, le=20)
    shareholder_orientation_score: int = Field(default=0, ge=0, le=20)
    integrity_evidence: str = ""
    capital_evidence: str = ""
    red_flags: list[str] = Field(default_factory=list)
    buffett_verdict_cn: str = ""
    summary_cn: str = ""


class FailureMode(BaseModel):
    scenario: str = ""
    probability_pct: int = Field(default=0, ge=0, le=100)
    early_signals: list[str] = Field(default_factory=list)
    impact_on_thesis: str = ""


class VariantView(BaseModel):
    range_worst: str = ""
    range_base: str = ""
    range_best: str = ""
    most_likely_outcome: str = ""
    my_correctness_probability_pct: int = Field(default=0, ge=0, le=100)
    market_consensus: str = ""
    my_difference: str = ""
    price_reflects_scenario: str = ""
    price_sentiment: str = ""
    if_market_right: str = ""
    if_i_right: str = ""


class InversionAnalysis(BaseModel):
    """Expected shape for Stage 8 (inversion) Claude output."""

    failure_modes: list[FailureMode] = Field(default_factory=list)
    variant_view: VariantView = Field(default_factory=VariantView)
    munger_inversion_summary: str = ""


def _extract_json_blob(text: str) -> str:
    """Pull the first JSON object from Claude text — handles ```json fences."""
    text = text.strip()
    # Fenced form
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # Bare blob — find outermost {...}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group(0)
    return text


def _log_parse_failure(text: str, schema_name: str, errors: list[str]) -> None:
    """R3-6: dump raw Claude output + parse errors to disk for post-mortem.

    Without this, when sonnet drifts (returns string for int, drops a key),
    we lose the raw response — the stage proceeds with partial data and
    we have no way to look up "what did Claude actually say?". One file
    per failure, timestamped, under MOATLENS_DATA_DIR. Best-effort: any
    IO error is printed to stderr but never raised, since this is a
    diagnostic side-channel, not a correctness path.
    """
    try:
        data_dir = Path(os.environ.get("MOATLENS_DATA_DIR", "data"))
        log_dir = data_dir / "logs" / "claude-parse-errors"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = log_dir / f"{ts}_{schema_name}.json"
        path.write_text(
            json.dumps(
                {
                    "timestamp": ts,
                    "schema": schema_name,
                    "errors": errors,
                    "raw_text": text[:8000],  # cap for storage; truncate longest tails
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[guardrails] parse-error log write failed: {e}", file=sys.stderr)


def parse_claude_json(
    text: str,
    schema: type[BaseModel],
) -> tuple[dict, list[str]]:
    """
    Parse Claude output against `schema`. Returns (data_dict, errors).
    Never raises. If parsing totally fails, returns ({}, [reason]).
    """
    errors: list[str] = []
    schema_name = schema.__name__
    try:
        blob = _extract_json_blob(text)
        raw = json.loads(blob)
    except Exception as e:
        errors = [f"json_parse: {e}"]
        _log_parse_failure(text, schema_name, errors)
        return {}, errors

    try:
        validated = schema.model_validate(raw)
        return validated.model_dump(), errors
    except ValidationError as e:
        # Partial recovery: keep whatever fields parsed correctly
        for err in e.errors():
            loc = ".".join(str(p) for p in err.get("loc", []))
            errors.append(f"{loc}: {err.get('msg', '')}")
        _log_parse_failure(text, schema_name, errors)
        # Drop invalid fields and re-validate with defaults
        cleaned = {}
        if isinstance(raw, dict):
            valid_fields = set(schema.model_fields.keys())
            for k, v in raw.items():
                if k in valid_fields:
                    cleaned[k] = v
        try:
            validated = schema.model_validate(cleaned, strict=False)
            return validated.model_dump(), errors
        except ValidationError:
            return cleaned, errors
    except Exception as e:
        errors = [f"validation: {e}"]
        _log_parse_failure(text, schema_name, errors)
        return {}, errors


def validate_moat(text: str) -> tuple[dict, list[str]]:
    return parse_claude_json(text, MoatAnalysis)


def validate_management(text: str) -> tuple[dict, list[str]]:
    return parse_claude_json(text, ManagementAnalysis)


def validate_inversion(text: str) -> tuple[dict, list[str]]:
    return parse_claude_json(text, InversionAnalysis)
