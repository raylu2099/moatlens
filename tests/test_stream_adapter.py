"""Stream adapter tests — monkeypatch every stage so no network or Claude calls."""
from __future__ import annotations

import pytest

from engine import stream_adapter
from engine.models import Metric, StageResult, Verdict
from shared.chat import ChatSession, save_session
from shared.config import ApiKeys, Config
from shared.storage import audits_root
from engine.wisdom import wisdom_path


@pytest.fixture
def cfg(tmp_path) -> Config:
    data = tmp_path / "data"
    data.mkdir()
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    # Minimal wisdom.yaml so we can get quotes
    (prompts / "wisdom.yaml").write_text("""
- id: q1
  author: Warren Buffett
  text_en: "en 1"
  text_cn: "中 1"
  source: "s1"
  themes: [competence]
  stages: [1, 2]
  triggers: []
- id: q2
  author: Charlie Munger
  text_en: "en 2"
  text_cn: "中 2"
  source: "s2"
  themes: [inversion]
  stages: [3, 4, 5, 6, 7, 8]
  triggers: [action_buy]
""", encoding="utf-8")
    return Config(
        data_dir=data, cache_dir=data / "cache",
        prompts_dir=prompts, docs_dir=tmp_path / "docs",
        claude_model="claude-sonnet-4-5",
        pplx_model_search="sonar", pplx_model_analysis="sonar-pro",
        cache_fundamentals_ttl=60, cache_perplexity_ttl=60, cache_macro_ttl=60,
        project_root=tmp_path,
    )


@pytest.fixture
def keys() -> ApiKeys:
    return ApiKeys(anthropic="sk-ant-test", perplexity="pplx-test",
                   financial_datasets="fd-test", fred="")


@pytest.fixture(autouse=True)
def stub_all_stages_and_company(monkeypatch):
    """Replace every stage's run + company-info fetch + coach with stubs."""

    def fake_company_info(ticker):
        return {"long_name": f"{ticker} Corp"}
    monkeypatch.setattr(
        "engine.providers.yfinance_provider.fetch_company_info", fake_company_info,
    )

    def make_stub(sid, name):
        def _run(*args, **kwargs):
            raw = {"cost_usd": 0.0}
            if sid in (3, 4):
                raw["claude_parsed"] = {"summary_cn": f"s{sid} stub"}
            if sid == 6:
                raw["base_iv"] = 100
                raw["valuation"] = {"base_iv": 100, "current_price": 80}
            if sid == 7:
                raw["margin_of_safety_pct"] = 35
                raw["current_price"] = 80
                raw["target_buy"] = 70
                raw["target_sell"] = 110
            return StageResult(
                stage_id=sid, stage_name=name,
                verdict=Verdict.PASS,
                metrics=[Metric(name=f"m{sid}", value=1.0, threshold=">=1",
                                **{"pass": True})],
                findings=[f"stub finding for {sid}"],
                raw_data=raw,
            )
        return _run

    import engine.stages as pkg
    for sid, mod_name in [
        (1, "s1_competence"), (2, "s2_integrity"),
        (3, "s3_moat"), (4, "s4_capital"),
        (5, "s5_owner_earnings"), (6, "s6_valuation"),
        (7, "s7_safety"), (8, "s8_inversion"),
    ]:
        mod = getattr(pkg, mod_name)
        monkeypatch.setattr(mod, "run", make_stub(sid, mod.STAGE_NAME))

    # Force rule-mode coach so no Haiku network call
    monkeypatch.setenv("MOATLENS_COACH", "rule")


def _collect(gen):
    return list(gen)


def test_stream_emits_expected_event_order(cfg, keys):
    session = ChatSession.new("AAPL")
    session.anchor_thesis = "生态锁定"
    save_session(cfg, session)

    events = _collect(stream_adapter.stream_audit(cfg, keys, session))
    kinds = [e[0] for e in events]

    # Must start with session_started, then alternate stage_start -> stage_complete
    assert kinds[0] == "session_started"
    assert "final" in kinds
    # Final must come AFTER the last stage_complete
    last_complete = max(i for i, k in enumerate(kinds) if k == "stage_complete")
    final_idx = kinds.index("final")
    assert final_idx > last_complete


def test_stream_yields_8_stage_completes(cfg, keys):
    session = ChatSession.new("AAPL")
    save_session(cfg, session)
    events = _collect(stream_adapter.stream_audit(cfg, keys, session))
    completes = [e for e in events if e[0] == "stage_complete"]
    assert len(completes) == 8
    assert [e[1]["stage_id"] for e in completes] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_stream_emits_unique_quotes_no_repeat_within_session(cfg, keys):
    """
    With only 2 quotes in the fixture (q1 covers stages 1-2, q2 covers 3-8),
    dedup means at most 2 quote events across all 8 stages — never repeat.
    """
    session = ChatSession.new("AAPL")
    save_session(cfg, session)
    events = _collect(stream_adapter.stream_audit(cfg, keys, session))
    quotes = [e for e in events if e[0] == "quote"]
    quote_ids = [q[1]["quote"]["id"] for q in quotes]
    # Every quote id is unique (dedup works)
    assert len(quote_ids) == len(set(quote_ids))
    # At least one quote was emitted (system isn't silent)
    assert len(quote_ids) >= 1


def test_stream_emits_commentary_per_stage_complete(cfg, keys):
    session = ChatSession.new("AAPL")
    save_session(cfg, session)
    events = _collect(stream_adapter.stream_audit(cfg, keys, session))
    commentaries = [e for e in events if e[0] == "commentary"]
    assert len(commentaries) == 8
    # Each commentary is Chinese (rule mode)
    for _, payload in commentaries:
        assert "问自己" in payload["text"]


def test_stream_final_contains_munger_questions(cfg, keys):
    session = ChatSession.new("AAPL")
    save_session(cfg, session)
    events = _collect(stream_adapter.stream_audit(cfg, keys, session))
    final_events = [e[1] for e in events if e[0] == "final"]
    assert len(final_events) == 1
    final = final_events[0]
    assert "munger_questions" in final
    assert len(final["munger_questions"]) == 3
    assert all("?" in q or "？" in q for q in final["munger_questions"])


def test_stream_saves_session_state(cfg, keys):
    session = ChatSession.new("AAPL")
    save_session(cfg, session)
    _collect(stream_adapter.stream_audit(cfg, keys, session))

    from shared.chat import load_session
    reloaded = load_session(cfg, session.session_id)
    assert reloaded is not None
    assert reloaded.audit_status == "complete"
    assert reloaded.current_stage == 9
    assert reloaded.report_date  # set after save_audit
    # Transcript has entries for each stage
    assert len(reloaded.messages) >= 8


def test_stream_saves_audit_to_disk(cfg, keys):
    session = ChatSession.new("AAPL")
    save_session(cfg, session)
    _collect(stream_adapter.stream_audit(cfg, keys, session))

    # Audit files should now exist under data/audits/AAPL/
    aapl_dir = audits_root(cfg) / "AAPL"
    assert aapl_dir.exists()
    jsons = list(aapl_dir.glob("*.json"))
    assert len(jsons) == 1


def test_stream_handles_skip_claude_flag(cfg, keys):
    session = ChatSession.new("AAPL")
    save_session(cfg, session)
    events = _collect(stream_adapter.stream_audit(cfg, keys, session, skip_claude=True))
    # All 8 stage_complete events still fire (stages 3/4/8 return synthetic SKIP)
    completes = [e for e in events if e[0] == "stage_complete"]
    assert len(completes) == 8
    # Stages 3, 4, 8 should be SKIP because of skip_claude
    by_id = {c[1]["stage_id"]: c[1] for c in completes}
    for sid in (3, 4, 8):
        assert by_id[sid]["verdict"] == "SKIP"
