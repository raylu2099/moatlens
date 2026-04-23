"""
Pydantic data models shared across engine, CLI, and Web.

Design rule: models are *data contracts*. Engine returns these; CLI and Web
render them. Audit reports embed raw provider data so they're reproducible
years later (Audit Snapshots feature).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --------- Verdicts & signals ---------


class Verdict(str, Enum):
    PASS = "PASS"
    BORDERLINE = "BORDERLINE"
    FAIL = "FAIL"
    SKIP = "SKIP"


class Action(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    WATCH = "WATCH"
    AVOID = "AVOID"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# --------- Stage building blocks ---------


class Metric(BaseModel):
    """A single data-backed fact within a stage."""

    name: str
    value: float | str | None = None
    unit: str = ""  # "%", "x", "years", "USD bn", etc.
    threshold: str = ""  # human-readable target, e.g. "> 15%"
    pass_: bool | None = Field(default=None, alias="pass")
    note: str = ""

    model_config = ConfigDict(populate_by_name=True)


class StageResult(BaseModel):
    """Output of a single audit stage."""

    stage_id: int
    stage_name: str
    verdict: Verdict
    metrics: list[Metric] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)  # qualitative bullet points
    raw_data: dict[str, Any] = Field(
        default_factory=dict
    )  # Audit Snapshot — embedded for reproducibility
    human_decision: str = ""  # If user overrode verdict, why
    elapsed_seconds: float = 0.0


# --------- Per-lens analysis ---------


class LensAnalysis(BaseModel):
    """Multi-analyst perspective output (Buffett/Munger/Marks/Bolton)."""

    lens: str  # "buffett" / "munger" / "marks" / "bolton"
    summary: str  # 1-3 sentence take
    key_questions: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


# --------- Valuation output ---------


class ValuationScenario(BaseModel):
    label: str  # "bear" / "base" / "bull"
    fcf_growth_rate: float  # %
    terminal_growth: float  # %
    wacc: float  # %
    intrinsic_value_per_share: float


class ValuationOutput(BaseModel):
    current_price: float | None = None
    dcf_scenarios: list[ValuationScenario] = Field(default_factory=list)
    reverse_dcf_implied_growth: float | None = None  # what growth current price assumes
    historical_multiple_percentile: dict[str, float] = Field(default_factory=dict)
    monte_carlo_p5: float | None = None
    monte_carlo_p50: float | None = None
    monte_carlo_p95: float | None = None


# --------- Position / thesis ---------


class Thesis(BaseModel):
    """Long-term investment thesis — not a trade ticket."""

    ticker: str
    entry_date: str = ""
    entry_price: float | None = None
    position_size_pct: str = ""  # "试水 1-2%" / "核心 5-10%"
    target_buy_price: float | None = None  # intrinsic × 0.7
    target_sell_price: float | None = None  # intrinsic × 1.1
    one_sentence_thesis: str = ""
    invalidation_conditions: list[str] = Field(default_factory=list)
    review_cadence: str = "quarterly"
    moat_assessment: str = ""
    management_note: str = ""


# --------- Full audit report ---------


class AuditReport(BaseModel):
    """The complete output of an audit. Serialized to Markdown + JSON."""

    ticker: str
    company_name: str = ""
    audit_date: str  # ISO YYYY-MM-DD
    audit_version: str = "0.1.0"
    generated_at: datetime

    # User input
    anchor_thesis: str = ""  # "why is this worth auditing" — written at start
    my_market_expectation: str = ""  # "what do you think the market is pricing in?"
    my_variant_view: str = ""  # "what's your non-consensus view?" (Howard Marks)

    # 8 stages
    stages: list[StageResult] = Field(default_factory=list)

    # Multi-lens analysis (populated after Stage 3+)
    lens_analyses: list[LensAnalysis] = Field(default_factory=list)

    # Valuation (populated in Stage 6)
    valuation: ValuationOutput | None = None

    # Final verdict
    overall_action: Action | None = None
    overall_confidence: ConfidenceLevel | None = None
    thesis: Thesis | None = None

    # Red/blue debate results (optional — if user ran --debate)
    debate_rounds: list[dict[str, str]] = Field(default_factory=list)

    # Inversion
    inversion_failure_modes: list[str] = Field(default_factory=list)

    # Variant View Canvas (9 questions — Stage 8)
    variant_view: dict[str, str] = Field(default_factory=dict)

    # Cost tracking
    total_api_cost_usd: float = 0.0
    provider_costs: dict[str, float] = Field(default_factory=dict)

    def summary_line(self) -> str:
        stages_passed = sum(1 for s in self.stages if s.verdict == Verdict.PASS)
        total = len(self.stages)
        action = self.overall_action.value if self.overall_action else "PENDING"
        return f"{self.ticker}: {stages_passed}/{total} passes → {action}"
