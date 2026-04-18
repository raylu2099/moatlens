"""
Prompt loader tests — verify version extraction and mtime-aware caching.
"""
from __future__ import annotations

import time

import pytest

from engine.prompts_loader import load_prompt
from shared.config import Config


@pytest.fixture
def cfg_with_prompts(tmp_path) -> Config:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    return Config(
        data_dir=data, cache_dir=data / "cache",
        prompts_dir=prompts, docs_dir=tmp_path / "docs",
        claude_model="claude-sonnet-4-5",
        pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )


def test_load_prompt_with_version_marker(cfg_with_prompts):
    p = cfg_with_prompts.prompts_dir / "foo.md"
    p.write_text("<!-- version: 7 -->\nHello prompt body.", encoding="utf-8")
    body, ver = load_prompt(cfg_with_prompts, "foo")
    assert ver == "7"
    assert "Hello prompt body" in body


def test_load_prompt_without_version_defaults_to_one(cfg_with_prompts):
    p = cfg_with_prompts.prompts_dir / "bar.md"
    p.write_text("no marker here", encoding="utf-8")
    _, ver = load_prompt(cfg_with_prompts, "bar")
    assert ver == "1"


def test_load_prompt_missing_raises(cfg_with_prompts):
    with pytest.raises(FileNotFoundError):
        load_prompt(cfg_with_prompts, "does-not-exist")


def test_load_prompt_picks_up_edits_via_mtime(cfg_with_prompts):
    p = cfg_with_prompts.prompts_dir / "live.md"
    p.write_text("<!-- version: 1 -->\nv1 body", encoding="utf-8")
    body1, ver1 = load_prompt(cfg_with_prompts, "live")
    assert ver1 == "1" and "v1 body" in body1

    # Ensure new mtime
    time.sleep(0.01)
    p.write_text("<!-- version: 2 -->\nv2 body", encoding="utf-8")
    # Bump mtime explicitly in case the sleep wasn't enough on slow FS.
    import os
    stat = p.stat()
    os.utime(p, (stat.st_atime, stat.st_mtime + 1))

    body2, ver2 = load_prompt(cfg_with_prompts, "live")
    assert ver2 == "2"
    assert "v2 body" in body2


def test_project_prompts_are_loadable():
    """Real prompts shipped with the repo must parse."""
    from shared.config import load_config
    cfg = load_config()
    for slug in ("s3_moat", "s4_capital", "s8_inversion"):
        body, ver = load_prompt(cfg, slug)
        assert body.strip(), f"{slug} body is empty"
        assert ver, f"{slug} version missing"
