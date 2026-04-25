"""
Regression tests for the nightly-ops helpers (R2-3):
- engine/cache.py::cache_clear_stale
- shared/metrics.py::archive_cost_log + today_cost_utc

These run as part of `bin/nightly.sh`; a silent regression here grows
into disk bloat or a broken budget view.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from engine.cache import cache_clear_stale, cache_set
from shared.config import Config
from shared.metrics import archive_cost_log, log_cost, today_cost_utc


def _cfg(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        prompts_dir=tmp_path,
        docs_dir=tmp_path,
        claude_model="x",
        pplx_model_search="sonar",
        pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=3600,
        cache_perplexity_ttl=3600,
        cache_macro_ttl=3600,
        project_root=tmp_path,
    )


# =========================================================================
# cache_clear_stale
# =========================================================================


def test_cache_clear_stale_deletes_old_entries(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    # Write a "fresh" entry and an "old" entry with a stored_at far in the past.
    cache_set(cfg, "ns", "fresh_key", {"v": 1})

    old_file = cfg.cache_dir / "ns" / "oldhash.json"
    old_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.write_text(
        json.dumps(
            {
                "stored_at": time.time() - 60 * 86400,  # 60 days ago
                "value": {"v": 2},
                "key": "old_key",
            }
        )
    )

    n = cache_clear_stale(cfg, max_age_seconds=30 * 86400)
    assert n == 1

    # Fresh entry survived
    remaining = list((cfg.cache_dir / "ns").glob("*.json"))
    assert len(remaining) == 1


def test_cache_clear_stale_removes_corrupt_files(tmp_path):
    """A half-written cache file from a prior crash should be nuked, not
    left to confuse cache_get on the next run."""
    cfg = _cfg(tmp_path)
    (cfg.cache_dir / "ns").mkdir(parents=True, exist_ok=True)
    corrupt = cfg.cache_dir / "ns" / "corrupt.json"
    corrupt.write_text("{not valid json")

    n = cache_clear_stale(cfg, max_age_seconds=30 * 86400)
    assert n == 1
    assert not corrupt.exists()


# =========================================================================
# archive_cost_log
# =========================================================================


def test_archive_cost_log_splits_old_vs_new(tmp_path):
    cfg = _cfg(tmp_path)

    # One "recent" entry (today) and two "old" entries (different months).
    log_cost(cfg, provider="claude", cost_usd=0.01)  # today

    metrics_file = cfg.data_dir / "metrics" / "cost.jsonl"
    # Inject two old entries by hand — log_cost always stamps "now"
    old_a = {"ts": "2025-01-15T10:00:00+00:00", "provider": "claude", "cost_usd": 0.5}
    old_b = {"ts": "2025-02-03T11:00:00+00:00", "provider": "perplexity", "cost_usd": 0.3}
    with metrics_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(old_a) + "\n")
        f.write(json.dumps(old_b) + "\n")

    archived, kept = archive_cost_log(cfg, keep_days=30)
    assert archived == 2
    assert kept == 1  # today's entry stays in live file

    # Monthly archive files exist
    archive_dir = cfg.data_dir / "metrics" / "archive"
    assert (archive_dir / "cost-2025-01.jsonl").exists()
    assert (archive_dir / "cost-2025-02.jsonl").exists()

    # Live file now contains only today's entry
    live_lines = metrics_file.read_text().strip().split("\n")
    assert len(live_lines) == 1
    live_entry = json.loads(live_lines[0])
    assert live_entry["cost_usd"] == 0.01


def test_archive_cost_log_no_ops_when_no_old_entries(tmp_path):
    cfg = _cfg(tmp_path)
    log_cost(cfg, provider="claude", cost_usd=0.05)

    archived, kept = archive_cost_log(cfg, keep_days=30)
    assert archived == 0
    assert kept == 1


# =========================================================================
# today_cost_utc
# =========================================================================


def test_today_cost_utc_sums_only_today(tmp_path):
    cfg = _cfg(tmp_path)
    log_cost(cfg, provider="claude", cost_usd=0.10)

    # Inject a yesterday entry
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    metrics_file = cfg.data_dir / "metrics" / "cost.jsonl"
    with metrics_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": yesterday, "cost_usd": 1.00}) + "\n")

    today_total = today_cost_utc(cfg)
    assert today_total == pytest.approx(0.10)
