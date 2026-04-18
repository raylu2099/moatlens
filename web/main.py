"""
Moatlens web app — FastAPI + Jinja2 + HTMX.

Routes:
- GET  /                   — Landing (demo audit visible to all)
- GET  /signup, POST /signup
- GET  /login, POST /login
- GET  /logout
- GET  /dashboard          — user home (audit list + thesis watchlist)
- GET  /audit/new          — start new audit (ticker form)
- POST /audit/new          — kick off audit, redirect to progress view
- GET  /audit/<id>/stream  — SSE live progress (8 stages)
- GET  /audit/<ticker>/<date>  — view report
- GET  /compare            — peer comparison
- GET  /history            — list all past audits with search/filter
- GET  /learn              — knowledge base index
- GET  /learn/<concept>    — single concept page
- GET  /settings           — BYOK key management
- POST /settings/key       — save a key
- POST /settings/key/test  — HTMX: test a key and return badge partial
- DEL  /settings/key       — delete a key
- GET  /report/<ticker>/<slug>  — SEO public share page
- GET  /api/status         — healthcheck
"""
from __future__ import annotations

import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    Cookie, Depends, FastAPI, Form, HTTPException, Query, Request, Response,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.models import Verdict
from engine.orchestrator import run_audit_auto
from engine.report_renderer import render_markdown
from shared.config import load_config
from shared.db import (
    create_user, get_shared_report, get_user_by_email, get_user_by_id,
    index_audit, init_db, list_user_audits, share_report,
)
from shared.storage import audits_dir, load_audit, save_audit
from web.auth import (
    current_user, hash_password, issue_session_cookie, verify_password,
)
from web.keys_manager import (
    get_key_statuses, load_user_keys, save_user_key, test_user_key,
)


cfg = load_config()
init_db(cfg)

app = FastAPI(title="Moatlens", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Global template vars
templates.env.globals["app_name"] = "Moatlens"


def _user(request: Request) -> dict | None:
    return current_user(request, cfg)


def _require_user(request: Request) -> dict:
    u = _user(request)
    if not u:
        raise HTTPException(302, headers={"Location": "/login"})
    return u


# ==================== Public pages ====================

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Landing page with demo audit."""
    demo_md_path = cfg.demo_dir / "AAPL" / "latest.md"
    demo_content = ""
    if demo_md_path.exists():
        demo_content = demo_md_path.read_text(encoding="utf-8")
    return templates.TemplateResponse(request, "landing.html", {
        
        "user": _user(request),
        "demo_content": demo_content,
        "demo_ticker": "AAPL",
    })


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    if _user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "auth/login.html", {
         "user": None, "error": None,
    })


@app.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    row = get_user_by_email(cfg, email)
    if not row or not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(request, "auth/login.html", {
             "user": None,
            "error": "Invalid email or password",
        })
    cookie = issue_session_cookie(cfg, row["id"])
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie("session", cookie, httponly=True, samesite="lax", max_age=7 * 86400)
    return resp


@app.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request):
    if _user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "auth/signup.html", {
         "user": None, "error": None,
    })


@app.post("/signup", response_class=HTMLResponse)
async def signup_post(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
):
    email = email.strip().lower()
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        return templates.TemplateResponse(request, "auth/signup.html", {
             "user": None, "error": "Invalid email format",
        })
    if len(password) < 8:
        return templates.TemplateResponse(request, "auth/signup.html", {
             "user": None, "error": "Password must be ≥ 8 chars",
        })
    if get_user_by_email(cfg, email):
        return templates.TemplateResponse(request, "auth/signup.html", {
             "user": None, "error": "Email already registered",
        })
    uid = create_user(cfg, email, hash_password(password), display_name)
    cookie = issue_session_cookie(cfg, uid)
    resp = RedirectResponse("/settings?first=1", status_code=302)
    resp.set_cookie("session", cookie, httponly=True, samesite="lax", max_age=7 * 86400)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("session")
    return resp


# ==================== Authenticated pages ====================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = _require_user(request)
    audits = list_user_audits(cfg, user["id"], limit=20)
    keys = get_key_statuses(cfg, user["id"])
    keys_ready = all(keys.get(p, {}).get("test_ok") for p in ("anthropic", "perplexity", "financial_datasets"))
    return templates.TemplateResponse(request, "dashboard.html", {
         "user": user,
        "audits": audits, "keys_ready": keys_ready, "keys": keys,
    })


@app.get("/audit/new", response_class=HTMLResponse)
async def audit_new_get(request: Request):
    user = _require_user(request)
    keys = get_key_statuses(cfg, user["id"])
    required = ["anthropic", "perplexity", "financial_datasets"]
    missing = [p for p in required if not keys.get(p, {}).get("test_ok")]
    if missing:
        return templates.TemplateResponse(request, "audit/new.html", {
             "user": user, "missing_keys": missing,
        })
    return templates.TemplateResponse(request, "audit/new.html", {
         "user": user, "missing_keys": [],
    })


@app.post("/audit/new")
async def audit_new_post(
    request: Request,
    ticker: Annotated[str, Form()],
    anchor_thesis: Annotated[str, Form()] = "",
    tech_mode: Annotated[str, Form()] = "",
):
    user = _require_user(request)
    ticker = ticker.strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9.-]{0,6}$", ticker):
        raise HTTPException(400, "Invalid ticker format")

    keys = load_user_keys(cfg, user["id"])
    ok, missing = keys.has_required()
    if not ok:
        raise HTTPException(400, f"Missing keys: {missing}")

    # Run the audit (synchronous for v1 — for long-running, add Celery/queue later)
    try:
        report = run_audit_auto(
            cfg, keys, ticker,
            anchor_thesis=anchor_thesis,
            tech_mode=bool(tech_mode),
        )
    except Exception as e:
        raise HTTPException(500, f"Audit failed: {e}")

    md = render_markdown(report)
    md_path, json_path = save_audit(cfg, report, md, user_id=str(user["id"]))

    # Index in DB for fast listing
    action = report.overall_action.value if report.overall_action else "PENDING"
    conf = report.overall_confidence.value if report.overall_confidence else ""
    index_audit(
        cfg, user["id"], ticker, report.audit_date,
        str(md_path), action, conf, report.total_api_cost_usd,
    )

    return RedirectResponse(f"/audit/{ticker}/{report.audit_date}", status_code=302)


@app.get("/audit/{ticker}/{date}", response_class=HTMLResponse)
async def audit_view(request: Request, ticker: str, date: str):
    user = _require_user(request)
    report = load_audit(cfg, ticker, date, user_id=str(user["id"]))
    if not report:
        raise HTTPException(404, "Audit not found")
    return templates.TemplateResponse(request, "audit/report.html", {
         "user": user, "report": report,
        "ticker": ticker.upper(), "date": date,
    })


@app.post("/audit/{ticker}/{date}/share")
async def audit_share(request: Request, ticker: str, date: str):
    user = _require_user(request)
    slug = f"{ticker.lower()}-{date}-{uuid.uuid4().hex[:8]}"
    share_report(cfg, user["id"], ticker, date, slug)
    return {"slug": slug, "url": f"/report/{ticker.lower()}/{slug}"}


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request, q: str = "", filter_action: str = ""):
    user = _require_user(request)
    audits = list_user_audits(cfg, user["id"], limit=200)
    if q:
        q_upper = q.upper()
        audits = [a for a in audits if q_upper in a["ticker"]]
    if filter_action:
        audits = [a for a in audits if a["action"] == filter_action.upper()]
    return templates.TemplateResponse(request, "history.html", {
         "user": user, "audits": audits,
        "q": q, "filter_action": filter_action,
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_get(request: Request, first: int = 0):
    user = _require_user(request)
    keys = get_key_statuses(cfg, user["id"])
    return templates.TemplateResponse(request, "settings.html", {
         "user": user, "keys": keys,
        "is_first_visit": bool(first),
    })


@app.post("/settings/key")
async def settings_save_key(
    request: Request,
    provider: Annotated[str, Form()],
    key: Annotated[str, Form()],
):
    user = _require_user(request)
    if provider not in ("anthropic", "perplexity", "financial_datasets", "fred"):
        raise HTTPException(400, "Unknown provider")
    if not key or len(key) < 8:
        raise HTTPException(400, "Key too short")
    save_user_key(cfg, user["id"], provider, key.strip())
    # Auto-test after save
    ok, msg = test_user_key(cfg, user["id"], provider)
    return HTMLResponse(_key_status_partial(provider, True, ok, msg, key))


@app.post("/settings/key/test")
async def settings_test_key(
    request: Request,
    provider: Annotated[str, Form()],
):
    user = _require_user(request)
    ok, msg = test_user_key(cfg, user["id"], provider)
    statuses = get_key_statuses(cfg, user["id"])
    info = statuses.get(provider, {})
    return HTMLResponse(_key_status_partial(
        provider, info.get("has_key", False), ok, msg, "",
    ))


def _key_status_partial(provider: str, has_key: bool, ok: bool, msg: str, mask_source: str) -> str:
    from shared.crypto import mask_key
    masked = mask_key(mask_source) if mask_source else ""
    if not has_key:
        return f'<span class="text-gray-500">Not set</span>'
    status_color = "text-green-400" if ok else "text-red-400"
    icon = "✅" if ok else "❌"
    m_html = f'<span class="text-gray-500 ml-2">{masked}</span>' if masked else ""
    return f'<span class="{status_color}">{icon} {msg}</span>{m_html}'


# ==================== SEO public share ====================

@app.get("/report/{ticker}/{slug}", response_class=HTMLResponse)
async def public_report(request: Request, ticker: str, slug: str):
    shared = get_shared_report(cfg, slug)
    if not shared or not shared.get("public"):
        raise HTTPException(404, "Report not found or private")
    report = load_audit(
        cfg, shared["ticker"], shared["audit_date"],
        user_id=str(shared["user_id"]),
    )
    if not report:
        raise HTTPException(404, "Report data missing")
    return templates.TemplateResponse(request, "public_report.html", {
         "user": _user(request), "report": report,
        "ticker": shared["ticker"], "date": shared["audit_date"],
        "views": shared.get("views", 0),
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
    return templates.TemplateResponse(request, "learn/index.html", {
         "user": _user(request), "concepts": concepts,
    })


@app.get("/learn/{slug}", response_class=HTMLResponse)
async def learn_concept(request: Request, slug: str):
    path = cfg.docs_dir / "concepts" / f"{slug}.md"
    if not path.exists():
        raise HTTPException(404)
    content = path.read_text(encoding="utf-8")
    return templates.TemplateResponse(request, "learn/concept.html", {
         "user": _user(request),
        "content": content, "slug": slug,
    })


# ==================== API ====================

@app.get("/api/status", response_class=JSONResponse)
async def api_status():
    return {"status": "ok", "version": "0.1.0", "timestamp": datetime.now().isoformat()}
