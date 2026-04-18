"""
Audit diff — compare two AuditReport snapshots for the same ticker.

Produces:
- Per-stage verdict transitions
- Per-metric value deltas
- Claude verdict transitions (for stages 3/4/8 via parsed JSON)

Used by both web (HTML render) and CLI (text render).
"""
from __future__ import annotations

from html import escape
from typing import Any

from engine.models import AuditReport, StageResult, Verdict


def _verdict_transition(old: Verdict, new: Verdict) -> str:
    """Human-readable transition marker."""
    rank = {Verdict.PASS: 3, Verdict.BORDERLINE: 2, Verdict.FAIL: 1, Verdict.SKIP: 0}
    if old == new:
        return "="
    return "↑" if rank[new] > rank[old] else "↓"


def _find_metric(stage: StageResult, name: str):
    return next((m for m in stage.metrics if m.name == name), None)


def _claude_verdict(stage: StageResult) -> str:
    """Extract Claude judgment string from stages 3/4/8."""
    p = stage.raw_data.get("claude_parsed") or {}
    for k in ("munger_verdict", "buffett_verdict_cn", "munger_inversion_summary"):
        v = p.get(k)
        if v:
            return str(v)[:100]
    return ""


def compute_diff(current: AuditReport, previous: AuditReport) -> dict[str, Any]:
    """Return structured diff (used by both web and CLI renderers)."""
    stages_diff = []
    cur_by_id = {s.stage_id: s for s in current.stages}
    prev_by_id = {s.stage_id: s for s in previous.stages}
    all_ids = sorted(set(cur_by_id) | set(prev_by_id))

    for sid in all_ids:
        cs = cur_by_id.get(sid)
        ps = prev_by_id.get(sid)
        if not cs or not ps:
            stages_diff.append({
                "stage_id": sid,
                "stage_name": (cs or ps).stage_name,
                "only_in": "current" if cs else "previous",
            })
            continue

        # Per-metric deltas
        metric_changes = []
        prev_metrics_by_name = {m.name: m for m in ps.metrics}
        for m in cs.metrics:
            pm = prev_metrics_by_name.get(m.name)
            if pm is None:
                metric_changes.append({"name": m.name, "from": None, "to": m.value,
                                       "pass_from": None, "pass_to": m.pass_})
                continue
            if m.value != pm.value or m.pass_ != pm.pass_:
                metric_changes.append({"name": m.name,
                                       "from": pm.value, "to": m.value,
                                       "pass_from": pm.pass_, "pass_to": m.pass_})

        stages_diff.append({
            "stage_id": sid,
            "stage_name": cs.stage_name,
            "verdict_from": ps.verdict.value,
            "verdict_to": cs.verdict.value,
            "verdict_arrow": _verdict_transition(ps.verdict, cs.verdict),
            "claude_from": _claude_verdict(ps),
            "claude_to": _claude_verdict(cs),
            "metric_changes": metric_changes,
        })

    return {
        "ticker": current.ticker,
        "current_date": current.audit_date,
        "previous_date": previous.audit_date,
        "action_from": previous.overall_action.value if previous.overall_action else "",
        "action_to": current.overall_action.value if current.overall_action else "",
        "cost_from": previous.total_api_cost_usd,
        "cost_to": current.total_api_cost_usd,
        "stages": stages_diff,
    }


def render_audit_diff_html(current: AuditReport, previous: AuditReport) -> str:
    """Render the diff as an HTML fragment (embedded in report.html or diff.html)."""
    d = compute_diff(current, previous)
    out: list[str] = []
    out.append('<div class="bg-ink-800 border border-ink-700 rounded-lg p-5 mb-6">')
    out.append(
        f'<h3 class="text-lg font-semibold text-gold mb-3">📊 vs 上次审视 '
        f'({escape(d["previous_date"])})</h3>'
    )

    action_from = escape(d["action_from"] or "—")
    action_to = escape(d["action_to"] or "—")
    arrow = "→"
    action_color = "text-yellow-300" if action_from != action_to else "text-gray-400"
    out.append(
        f'<p class="text-sm mb-3">整体判断: '
        f'<span class="text-gray-400">{action_from}</span> '
        f'<span class="{action_color}">{arrow}</span> '
        f'<span class="font-bold">{action_to}</span></p>'
    )

    out.append('<div class="space-y-2 text-sm">')
    for s in d["stages"]:
        if "only_in" in s:
            out.append(
                f'<div class="text-gray-500">Stage {s["stage_id"]} '
                f'{escape(s["stage_name"])} — 仅 {s["only_in"]} 有</div>'
            )
            continue
        vf = s["verdict_from"]
        vt = s["verdict_to"]
        arrow_sym = s["verdict_arrow"]
        color = "text-gray-400" if arrow_sym == "=" else (
            "text-green-400" if arrow_sym == "↑" else "text-red-400"
        )
        out.append(
            f'<details class="border border-ink-700 rounded px-3 py-2">'
            f'<summary class="cursor-pointer font-medium">'
            f'<span class="text-gray-500">Stage {s["stage_id"]}</span> '
            f'{escape(s["stage_name"])} '
            f'<span class="{color}">{vf} {arrow_sym} {vt}</span>'
            f'</summary>'
        )
        if s["claude_from"] != s["claude_to"] and (s["claude_from"] or s["claude_to"]):
            out.append(
                f'<div class="mt-2 text-xs text-gray-400">'
                f'Claude: <em>{escape(s["claude_from"] or "—")}</em> → '
                f'<strong>{escape(s["claude_to"] or "—")}</strong>'
                f'</div>'
            )
        if s["metric_changes"]:
            out.append('<ul class="mt-2 text-xs space-y-1">')
            for mc in s["metric_changes"]:
                vfrom = "—" if mc["from"] is None else str(mc["from"])
                vto = "—" if mc["to"] is None else str(mc["to"])
                out.append(
                    f'<li>• {escape(mc["name"])}: '
                    f'<span class="text-gray-500">{escape(vfrom)}</span> → '
                    f'<span class="text-gray-200">{escape(vto)}</span></li>'
                )
            out.append('</ul>')
        out.append('</details>')
    out.append('</div>')
    out.append('</div>')
    return "\n".join(out)


def render_audit_diff_text(current: AuditReport, previous: AuditReport) -> str:
    """Render the diff as plain text (CLI)."""
    d = compute_diff(current, previous)
    lines = []
    lines.append(f"Diff: {d['ticker']}  {d['previous_date']}  →  {d['current_date']}")
    lines.append("")
    lines.append(f"Overall action:  {d['action_from'] or '—'}  →  {d['action_to'] or '—'}")
    lines.append(f"API cost:        ${d['cost_from']:.3f}  →  ${d['cost_to']:.3f}")
    lines.append("")
    lines.append("Stages:")
    for s in d["stages"]:
        if "only_in" in s:
            lines.append(f"  Stage {s['stage_id']}: only in {s['only_in']}")
            continue
        lines.append(
            f"  Stage {s['stage_id']} {s['stage_name']}: "
            f"{s['verdict_from']} {s['verdict_arrow']} {s['verdict_to']}"
        )
        if s["claude_from"] != s["claude_to"] and (s["claude_from"] or s["claude_to"]):
            lines.append(f"      Claude: {s['claude_from'] or '—'}  →  {s['claude_to'] or '—'}")
        for mc in s["metric_changes"]:
            vfrom = "—" if mc["from"] is None else str(mc["from"])
            vto = "—" if mc["to"] is None else str(mc["to"])
            lines.append(f"      · {mc['name']}: {vfrom} → {vto}")
    return "\n".join(lines)
