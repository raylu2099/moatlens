"""
Moatlens web app — single-user mode.

No auth, no multi-tenant. Binds to 127.0.0.1.
Keys come from .env (shared with CLI).

Routes:
- GET  /                           redirect to /portfolio if holdings, else /history or /audit/new
- GET  /audit/new                  ticker form
- POST /audit/new                  run audit synchronously, redirect to view
- GET  /audit/<ticker>/diff        pairwise diff of latest two audits
- GET  /audit/<ticker>/<date>      view report (diff block embedded)
- GET  /history                    list all audits (with age + holding flag)
- GET  /portfolio                  holdings dashboard
- GET  /learn                      knowledge base
- GET  /learn/<concept>
- GET  /api/status                 healthcheck
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.orchestrator import run_audit_auto
from engine.providers import yfinance_provider as yfp
from engine.report_renderer import render_markdown
from shared.config import load_config, load_keys_from_env
from shared.holdings import is_holding, load_holdings
from shared.storage import list_audits, load_audit, load_last_two_audits, save_audit
from web.diff import render_audit_diff_html


cfg = load_config()

app = FastAPI(title="Moatlens (single-user)", version="0.3.0")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["app_name"] = "Moatlens"


@app.get("/")
async def root():
    holdings = load_holdings(cfg)
    if holdings:
        return RedirectResponse("/portfolio", status_code=302)
    audits = list_audits(cfg)
    if audits:
        return RedirectResponse("/history", status_code=302)
    return RedirectResponse("/audit/new", status_code=302)


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
    my_market_expectation: Annotated[str, Form()] = "",
    my_variant_view: Annotated[str, Form()] = "",
    tech_mode: Annotated[str, Form()] = "",
):
    ticker = ticker.strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9]{0,5}(\.[A-Z]{1,2})?$", ticker):
        raise HTTPException(400, "Ticker 格式无效")

    keys = load_keys_from_env()
    ok, missing = keys.has_required()
    if not ok:
        raise HTTPException(400, f"缺 key: {missing} —— 在 .env 里补上")

    try:
        report = run_audit_auto(
            cfg, keys, ticker,
            anchor_thesis=anchor_thesis,
            tech_mode=bool(tech_mode),
            my_market_expectation=my_market_expectation,
            my_variant_view=my_variant_view,
        )
    except Exception:
        raise HTTPException(500, "Audit 引擎失败 —— 查看服务器日志")

    md = render_markdown(report)
    save_audit(cfg, report, md)
    return RedirectResponse(f"/audit/{ticker}/{report.audit_date}", status_code=302)


# IMPORTANT: /audit/{ticker}/diff declared before /audit/{ticker}/{date} —
# FastAPI matches in order, and a literal "diff" would otherwise be captured by {date}.
@app.get("/audit/{ticker}/diff", response_class=HTMLResponse)
async def audit_diff(request: Request, ticker: str):
    ticker = ticker.upper()
    current, previous = load_last_two_audits(cfg, ticker)
    if not current:
        raise HTTPException(404, "该 ticker 没有 audit")
    if not previous:
        raise HTTPException(404, "至少需要两次 audit 才能 diff")
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
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(404, "日期格式无效")
    report = load_audit(cfg, ticker, date)
    if not report:
        raise HTTPException(404, "未找到 audit")

    current, previous = load_last_two_audits(cfg, ticker)
    diff_html = ""
    if current and previous and current.audit_date == date:
        diff_html = render_audit_diff_html(current, previous)

    return templates.TemplateResponse(request, "audit/report.html", {
        "report": report, "ticker": ticker, "date": date,
        "diff_html": diff_html,
        "is_holding": is_holding(cfg, ticker),
    })


# ==================== History ====================

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request, q: str = "", filter_action: str = ""):
    audits = list_audits(cfg)
    held = {h["ticker"] for h in load_holdings(cfg)}
    for a in audits:
        a["is_holding"] = a["ticker"] in held

    if q:
        q_upper = q.upper()
        audits = [a for a in audits if q_upper in a["ticker"]]
    if filter_action:
        audits = [a for a in audits if a["action"] == filter_action.upper()]

    stale_count = sum(1 for a in audits if a.get("stale_level") in ("stale", "very_stale"))
    return templates.TemplateResponse(request, "history.html", {
        "audits": audits, "q": q, "filter_action": filter_action,
        "stale_count": stale_count,
    })


# ==================== Portfolio ====================

@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio(request: Request):
    holdings = load_holdings(cfg)
    rows = []
    today = date.today()

    for h in holdings:
        ticker = h["ticker"]
        current, _ = load_last_two_audits(cfg, ticker)

        try:
            price = yfp.fetch_current_price(ticker)
        except Exception:
            price = None

        row = {
            "ticker": ticker,
            "size": h.get("size", ""),
            "note": h.get("note", ""),
            "price": price,
            "audit_date": None,
            "age_days": None,
            "stale_level": None,
            "target_buy": None,
            "target_sell": None,
            "mos_pct": None,
            "status": None,
        }

        if current:
            row["audit_date"] = current.audit_date
            try:
                age = (today - date.fromisoformat(current.audit_date)).days
                row["age_days"] = age
                row["stale_level"] = (
                    "very_stale" if age >= 180 else
                    "stale" if age >= 90 else "fresh"
                )
            except Exception:
                pass

            if current.thesis:
                row["target_buy"] = current.thesis.target_buy_price
                row["target_sell"] = current.thesis.target_sell_price

            s7 = next((s for s in current.stages if s.stage_id == 7), None)
            if s7:
                mos = s7.raw_data.get("margin_of_safety_pct")
                if mos is not None:
                    row["mos_pct"] = mos

            if price and row["target_buy"] and row["target_sell"]:
                if price <= row["target_buy"]:
                    row["status"] = "buy_zone"
                elif price >= row["target_sell"]:
                    row["status"] = "sell_zone"
                else:
                    row["status"] = "hold"

        rows.append(row)

    return templates.TemplateResponse(request, "portfolio.html", {"rows": rows})


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
        from html import escape
        content_html = f'<pre class="whitespace-pre-wrap">{escape(raw_md)}</pre>'
    return templates.TemplateResponse(request, "learn/concept.html", {
        "content": content_html, "slug": slug,
    })


# ==================== API ====================

@app.get("/api/status", response_class=JSONResponse)
async def api_status():
    return {"status": "ok", "version": "0.3.0", "mode": "single-user",
            "timestamp": datetime.now().isoformat()}
