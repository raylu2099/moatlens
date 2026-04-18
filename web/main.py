"""
Moatlens web app — single-user mode.

No auth, no multi-tenant. Bind to 127.0.0.1 only.
Keys come from .env (shared with CLI).

Routes:
- GET  /                   → redirect to /history (or /audit/new if no audits yet)
- GET  /audit/new          → ticker form
- POST /audit/new          → run audit, redirect to view
- GET  /audit/<ticker>/<date>   → view report (with "vs last" diff when available)
- GET  /audit/<ticker>/diff     → diff latest vs previous for a ticker
- GET  /history            → list all past audits
- GET  /learn              → knowledge base index
- GET  /learn/<concept>    → single concept page
- GET  /api/status         → healthcheck
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.orchestrator import run_audit_auto
from engine.report_renderer import render_markdown
from shared.config import load_config, load_keys_from_env
from shared.storage import list_audits, load_audit, load_last_two_audits, save_audit
from web.diff import render_audit_diff_html


cfg = load_config()

app = FastAPI(title="Moatlens (single-user)", version="0.2.0")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["app_name"] = "Moatlens"


@app.get("/")
async def root():
    audits = list_audits(cfg)
    if not audits:
        return RedirectResponse("/audit/new", status_code=302)
    return RedirectResponse("/history", status_code=302)


# ==================== Audit ====================

@app.get("/audit/new", response_class=HTMLResponse)
async def audit_new_get(request: Request):
    keys = load_keys_from_env()
    ok, missing = keys.has_required()
    return templates.TemplateResponse(request, "audit/new.html", {
        "missing_keys": missing if not ok else [],
    })


@app.post("/audit/new")
async def audit_new_post(
    request: Request,
    ticker: Annotated[str, Form()],
    anchor_thesis: Annotated[str, Form()] = "",
    tech_mode: Annotated[str, Form()] = "",
):
    ticker = ticker.strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9]{0,5}(\.[A-Z]{1,2})?$", ticker):
        raise HTTPException(400, "Invalid ticker format")

    keys = load_keys_from_env()
    ok, missing = keys.has_required()
    if not ok:
        raise HTTPException(400, f"Missing keys: {missing} — add them to .env")

    try:
        report = run_audit_auto(
            cfg, keys, ticker,
            anchor_thesis=anchor_thesis,
            tech_mode=bool(tech_mode),
        )
    except Exception as e:
        # Orchestrator already catches per-stage errors; this is defensive only.
        raise HTTPException(500, "Audit engine failed — check server logs")

    md = render_markdown(report)
    save_audit(cfg, report, md)
    return RedirectResponse(f"/audit/{ticker}/{report.audit_date}", status_code=302)


# IMPORTANT: declare /audit/{ticker}/diff *before* /audit/{ticker}/{date} —
# FastAPI matches routes in declaration order, and a literal "diff" would
# otherwise be captured by the {date} placeholder.
@app.get("/audit/{ticker}/diff", response_class=HTMLResponse)
async def audit_diff(request: Request, ticker: str):
    ticker = ticker.upper()
    current, previous = load_last_two_audits(cfg, ticker)
    if not current:
        raise HTTPException(404, "No audits for this ticker")
    if not previous:
        raise HTTPException(404, "Need at least 2 audits to diff")
    diff_html = render_audit_diff_html(current, previous)
    return templates.TemplateResponse(request, "audit/diff.html", {
        "ticker": ticker,
        "current_date": current.audit_date,
        "previous_date": previous.audit_date,
        "diff_html": diff_html,
    })


@app.get("/audit/{ticker}/{date}", response_class=HTMLResponse)
async def audit_view(request: Request, ticker: str, date: str):
    ticker = ticker.upper()
    # Defence in depth: only ISO-like dates are valid — prevents the route
    # from intercepting other literal words if a future route adds one.
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(404, "Invalid date")
    report = load_audit(cfg, ticker, date)
    if not report:
        raise HTTPException(404, "Audit not found")

    current, previous = load_last_two_audits(cfg, ticker)
    diff_html = ""
    if current and previous and current.audit_date == date:
        diff_html = render_audit_diff_html(current, previous)

    return templates.TemplateResponse(request, "audit/report.html", {
        "report": report, "ticker": ticker, "date": date,
        "diff_html": diff_html,
    })


# ==================== History ====================

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request, q: str = "", filter_action: str = ""):
    audits = list_audits(cfg)
    if q:
        q_upper = q.upper()
        audits = [a for a in audits if q_upper in a["ticker"]]
    if filter_action:
        audits = [a for a in audits if a["action"] == filter_action.upper()]
    return templates.TemplateResponse(request, "history.html", {
        "audits": audits, "q": q, "filter_action": filter_action,
    })


# ==================== Learn ====================

@app.get("/learn", response_class=HTMLResponse)
async def learn_index(request: Request):
    concepts_dir = cfg.docs_dir / "concepts"
    concepts = []
    if concepts_dir.exists():
        for p in sorted(concepts_dir.glob("*.md")):
            title = p.stem.replace("-", " ").title()
            concepts.append({"slug": p.stem, "title": title})
    return templates.TemplateResponse(request, "learn/index.html", {"concepts": concepts})


@app.get("/learn/{slug}", response_class=HTMLResponse)
async def learn_concept(request: Request, slug: str):
    # Restrict slug to safe chars — no path traversal possible.
    if not re.match(r"^[a-z0-9_-]+$", slug):
        raise HTTPException(404)
    path = cfg.docs_dir / "concepts" / f"{slug}.md"
    if not path.exists():
        raise HTTPException(404)
    raw_md = path.read_text(encoding="utf-8")
    try:
        import markdown as md_lib
        content_html = md_lib.markdown(raw_md, extensions=["extra", "tables"])
    except ImportError:
        # Fallback — raw markdown in a <pre>.
        from html import escape
        content_html = f'<pre class="whitespace-pre-wrap">{escape(raw_md)}</pre>'
    return templates.TemplateResponse(request, "learn/concept.html", {
        "content": content_html, "slug": slug,
    })


# ==================== API ====================

@app.get("/api/status", response_class=JSONResponse)
async def api_status():
    return {"status": "ok", "version": "0.2.0", "mode": "single-user",
            "timestamp": datetime.now().isoformat()}
