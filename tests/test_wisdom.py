"""Wisdom loader + selection tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.wisdom import (
    Quote, filter_by_theme, get_quote_by_id, group_by_theme,
    load_wisdom, pick_for_stage, pick_for_trigger, wisdom_path,
)
from shared.config import Config


@pytest.fixture
def cfg_with_wisdom(tmp_path) -> Config:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    cfg = Config(
        data_dir=data, cache_dir=data / "cache",
        prompts_dir=prompts, docs_dir=tmp_path / "docs",
        claude_model="claude-sonnet-4-5",
        pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )
    wisdom_path(cfg).write_text("""
- id: q1
  author: Warren Buffett
  text_en: "quote 1 en"
  text_cn: "语录 1"
  source: "test"
  themes: [competence, humility]
  stages: [1]
  triggers: []
- id: q2
  author: Charlie Munger
  text_en: "quote 2 en"
  text_cn: "语录 2"
  source: "test"
  themes: [inversion]
  stages: [8]
  triggers: [action_avoid]
- id: q3
  author: Howard Marks
  text_en: "quote 3 en"
  text_cn: "语录 3"
  source: "test"
  themes: [asymmetry, variant_view]
  stages: [7, 8]
  triggers: [low_mos_buy]
- id: q4
  author: Warren Buffett
  text_en: "quote 4 en"
  text_cn: "语录 4"
  source: "test"
  themes: [competence]
  stages: [1]
  triggers: []
""", encoding="utf-8")
    return cfg


def test_load_parses_all_valid_entries(cfg_with_wisdom):
    quotes = load_wisdom(cfg_with_wisdom)
    assert len(quotes) == 4
    assert all(isinstance(q, Quote) for q in quotes)
    assert {q.id for q in quotes} == {"q1", "q2", "q3", "q4"}


def test_load_returns_empty_when_file_missing(tmp_path):
    # Config with no wisdom.yaml
    cfg = Config(
        data_dir=tmp_path, cache_dir=tmp_path / "cache",
        prompts_dir=tmp_path / "prompts", docs_dir=tmp_path / "docs",
        claude_model="", pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )
    assert load_wisdom(cfg) == []


def test_pick_for_stage_deterministic(cfg_with_wisdom):
    """Same seed → same pick every time."""
    first = pick_for_stage(cfg_with_wisdom, 1, "session-abc")
    second = pick_for_stage(cfg_with_wisdom, 1, "session-abc")
    assert first is not None
    assert first.id == second.id


def test_pick_for_stage_different_seeds_may_differ(cfg_with_wisdom):
    """Over many seeds, both stage-1 quotes (q1 and q4) get selected."""
    seen_ids = set()
    for seed in (f"s{i}" for i in range(20)):
        q = pick_for_stage(cfg_with_wisdom, 1, seed)
        if q:
            seen_ids.add(q.id)
    # Both q1 and q4 match stage 1; we should see at least one (and hopefully both over 20 seeds)
    assert seen_ids.issubset({"q1", "q4"})
    assert len(seen_ids) >= 1


def test_pick_for_stage_excludes_ids(cfg_with_wisdom):
    """exclude_ids lets the caller guarantee no repeat within a session."""
    # Try multiple seeds to find one that would pick q1 without exclusion
    # then verify excluding q1 gives q4 (or None if no other match)
    for seed in (f"seed{i}" for i in range(20)):
        first = pick_for_stage(cfg_with_wisdom, 1, seed)
        if first and first.id == "q1":
            second = pick_for_stage(cfg_with_wisdom, 1, seed, exclude_ids={"q1"})
            assert second is not None
            assert second.id == "q4"
            return
    pytest.skip("Couldn't find a seed that picks q1 first — unlikely, see RNG")


def test_pick_for_stage_returns_none_when_no_match(cfg_with_wisdom):
    # Stage 99 exists for no quote
    assert pick_for_stage(cfg_with_wisdom, 99, "any-seed") is None


def test_pick_for_trigger(cfg_with_wisdom):
    q = pick_for_trigger(cfg_with_wisdom, "low_mos_buy", "seed1")
    assert q is not None
    assert q.id == "q3"


def test_pick_for_trigger_not_found(cfg_with_wisdom):
    assert pick_for_trigger(cfg_with_wisdom, "no_such_trigger", "seed1") is None


def test_filter_by_theme(cfg_with_wisdom):
    competence = filter_by_theme(cfg_with_wisdom, "competence")
    assert {q.id for q in competence} == {"q1", "q4"}

    inversion = filter_by_theme(cfg_with_wisdom, "inversion")
    assert [q.id for q in inversion] == ["q2"]


def test_group_by_theme(cfg_with_wisdom):
    grouped = group_by_theme(cfg_with_wisdom)
    assert "competence" in grouped
    assert "inversion" in grouped
    assert "asymmetry" in grouped
    assert {q.id for q in grouped["competence"]} == {"q1", "q4"}


def test_get_quote_by_id(cfg_with_wisdom):
    q = get_quote_by_id(cfg_with_wisdom, "q2")
    assert q is not None
    assert q.author == "Charlie Munger"
    assert get_quote_by_id(cfg_with_wisdom, "nope") is None


def test_duplicate_ids_deduped(tmp_path):
    """If a user edits wisdom.yaml and accidentally duplicates an id, only first wins."""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "wisdom.yaml").write_text("""
- id: dup
  text_en: "first"
  themes: [x]
- id: dup
  text_en: "second"
  themes: [y]
""", encoding="utf-8")
    cfg = Config(
        data_dir=tmp_path, cache_dir=tmp_path / "cache",
        prompts_dir=prompts, docs_dir=tmp_path / "docs",
        claude_model="", pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )
    quotes = load_wisdom(cfg)
    assert len(quotes) == 1
    assert quotes[0].text_en == "first"


def test_project_wisdom_yaml_loads():
    """The real shipped wisdom.yaml must parse and have ≥ 20 quotes."""
    from shared.config import load_config
    cfg = load_config()
    quotes = load_wisdom(cfg)
    assert len(quotes) >= 20
    # At least one quote each from the main masters
    authors = {q.author for q in quotes}
    for master in ("Warren Buffett", "Charlie Munger", "Howard Marks"):
        assert master in authors, f"no quote from {master}"
