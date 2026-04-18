"""
Configuration loader. Reads .env, exposes typed config.

Single-user mode: keys come from process env (loaded from .env).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class ApiKeys:
    anthropic: str = ""
    perplexity: str = ""
    financial_datasets: str = ""
    fred: str = ""

    def has_required(self) -> tuple[bool, list[str]]:
        missing = []
        if not self.anthropic:
            missing.append("ANTHROPIC_API_KEY")
        if not self.perplexity:
            missing.append("PERPLEXITY_API_KEY")
        if not self.financial_datasets:
            missing.append("FINANCIAL_DATASETS_API_KEY")
        return len(missing) == 0, missing


@dataclass(frozen=True)
class Config:
    data_dir: Path
    cache_dir: Path
    prompts_dir: Path
    docs_dir: Path

    claude_model: str
    pplx_model_search: str
    pplx_model_analysis: str

    cache_fundamentals_ttl: int
    cache_perplexity_ttl: int
    cache_macro_ttl: int

    project_root: Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def load_config() -> Config:
    data_dir = Path(_env("MOATLENS_DATA_DIR", str(PROJECT_ROOT / "data")))
    cache_dir = Path(_env("MOATLENS_CACHE_DIR", str(PROJECT_ROOT / "data" / "cache")))
    prompts_dir = PROJECT_ROOT / "prompts"
    docs_dir = PROJECT_ROOT / "docs"

    for d in [data_dir, cache_dir]:
        d.mkdir(parents=True, exist_ok=True)

    return Config(
        data_dir=data_dir,
        cache_dir=cache_dir,
        prompts_dir=prompts_dir,
        docs_dir=docs_dir,
        claude_model=_env("CLAUDE_MODEL", "claude-sonnet-4-5"),
        pplx_model_search=_env("PPLX_MODEL_SEARCH", "sonar"),
        pplx_model_analysis=_env("PPLX_MODEL_ANALYSIS", "sonar-pro"),
        cache_fundamentals_ttl=int(_env("CACHE_FUNDAMENTALS_TTL", "43200")),
        cache_perplexity_ttl=int(_env("CACHE_PERPLEXITY_TTL", "21600")),
        cache_macro_ttl=int(_env("CACHE_MACRO_TTL", "86400")),
        project_root=PROJECT_ROOT,
    )


def load_keys_from_env() -> ApiKeys:
    return ApiKeys(
        anthropic=_env("ANTHROPIC_API_KEY"),
        perplexity=_env("PERPLEXITY_API_KEY"),
        financial_datasets=_env("FINANCIAL_DATASETS_API_KEY"),
        fred=_env("FRED_API_KEY"),
    )
