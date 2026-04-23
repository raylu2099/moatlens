# ruff: noqa: E402 — project-root imports must follow sys.path.insert below
"""
Moatlens web app v0.5 — three-mode landing + full hardening.

Binds to 127.0.0.1. No auth. Keys come from .env.

Routes:
- GET  /                           three-card home (chat / ask / portfolio)
- POST /chat/start                 start conversational audit
- GET  /chat/<id>                  chat page
- GET  /chat/<id>/stream           chat SSE
- POST /chat/<id>/message          set anchor thesis
- POST /ask/start                  start Q&A session (intent-routed stages)
- GET  /ask/<id>                   ask page
- GET  /ask/<id>/stream            ask SSE
- GET  /portfolio                  holdings dashboard (with briefing data)
- GET  /history                    audit history
- GET  /audit/<t>/diff             pairwise diff
- GET  /audit/<t>/<date>           view report
- GET  /audit/new                  legacy form
- POST /audit/new                  legacy synchronous audit
- GET  /wisdom                     quote library
- GET  /wisdom/<id>                single quote
- GET  /learn, /learn/<slug>       knowledge base
- GET  /api/status                 healthcheck
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import ask as ask_engine
from engine import wisdom as wisdom_mod
from engine.orchestrator import run_audit_auto
from engine.providers import yfinance_provider as yfp
from engine.report_renderer import render_markdown
from engine.stream_adapter import stream_audit
from shared.ask import AskSession, load_ask_session, save_ask_session
from shared.ask import cleanup_expired as cleanup_asks
from shared.chat import (
    ChatMessage,
    ChatSession,
    list_sessions,
    load_session,
    save_session,
)
from shared.chat import (
    cleanup_expired as cleanup_chats,
)
from shared.config import load_config, load_keys_from_env
from shared.holdings import is_holding, load_holdings
from shared.logging_setup import get_logger, setup_logging
from shared.storage import list_audits, load_audit, load_last_two_audits, save_audit
from web.diff import render_audit_diff_html

setup_logging()
log = get_logger("moatlens.web")

cfg = load_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: prune sessions older than 7 days; mark in-progress sessions as
    # error (they were running when uvicorn was killed).
    try:
        cleanup_chats(cfg)
        cleanup_asks(cfg)
        _recover_stale_sessions()
    except Exception as e:
        print(f"[startup] cleanup error: {e}", file=sys.stderr)
    yield
    # Shutdown: nothing to do; filesystem state is already consistent


def _recover_stale_sessions():
    """Mark any 'running' chat/ask sessions >10 min old as 'error'."""
    now = datetime.now(timezone.utc)
    for s in list_sessions(cfg, limit=1000):
        if s.get("audit_status") != "running":
            continue
        try:
            ts = s.get("updated_at", "")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_s = (now - dt).total_seconds()
            if age_s > 600:
                sess = load_session(cfg, s["session_id"])
                if sess:
                    sess.audit_status = "error"
                    sess.add(
                        ChatMessage.new(
                            "system",
                            "⚠️ 服务器重启时这次审视中断了。可以重新发起。",
                        )
                    )
                    save_session(cfg, sess)
        except Exception:
            continue


app = FastAPI(title="Moatlens", version="0.5.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["app_name"] = "Moatlens"


# =====================================================================
# Home (three-mode landing)
# =====================================================================


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    keys = load_keys_from_env()
    keys_missing = keys.has_required()[1]
    recent = list_sessions(cfg, limit=3)
    audits = list_audits(cfg)[:3]
    holdings = load_holdings(cfg)

    briefing = _build_briefing(holdings, audits)
    daily_quote = _daily_quote()

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "keys_missing": keys_missing,
            "recent_sessions": recent,
            "recent_audits": audits,
            "briefing": briefing,
            "daily_quote": daily_quote,
        },
    )


def _build_briefing(holdings: list[dict], audits: list[dict]) -> dict | None:
    """Assemble today's alerts from holdings state + audit ages."""
    if not holdings:
        return None
    alerts = []

    for h in holdings:
        ticker = h["ticker"]
        current, _ = load_last_two_audits(cfg, ticker)
        if not current:
            alerts.append(
                {
                    "icon": "⚠",
                    "color": "red",
                    "text": f"{ticker} 是持仓但从未 audit —— 补审一次",
                }
            )
            continue
        try:
            age = (date.today() - date.fromisoformat(current.audit_date)).days
        except Exception:
            age = 0
        if age >= 180:
            alerts.append(
                {
                    "icon": "⚠",
                    "color": "red",
                    "text": f"{ticker} thesis 已 {age} 天未复盘（季度纪律超期）",
                }
            )
        elif age >= 90:
            alerts.append(
                {
                    "icon": "⏳",
                    "color": "yellow",
                    "text": f"{ticker} thesis {age} 天，快到季度复盘窗口",
                }
            )
        # Check buy/sell zone
        if current.thesis:
            try:
                price = yfp.fetch_current_price(ticker)
            except Exception:
                price = None
            tb = current.thesis.target_buy_price
            ts_ = current.thesis.target_sell_price
            if price and tb and price <= tb:
                alerts.append(
                    {
                        "icon": "🟢",
                        "color": "green",
                        "text": f"{ticker} ${price:.0f} 在加仓区（≤ ${tb:.0f}）",
                    }
                )
            elif price and ts_ and price >= ts_:
                alerts.append(
                    {
                        "icon": "🔴",
                        "color": "red",
                        "text": f"{ticker} ${price:.0f} 在减仓区（≥ ${ts_:.0f}）",
                    }
                )

    return {"alerts": alerts, "total_holdings": len(holdings)}


def _daily_quote() -> dict | None:
    """Pick a deterministic daily quote by date hash."""
    quotes = wisdom_mod.load_wisdom(cfg)
    if not quotes:
        return None
    today = date.today().isoformat()
    idx = int(sha256(today.encode()).hexdigest(), 16) % len(quotes)
    q = quotes[idx]
    return {"text_cn": q.text_cn, "author": q.author, "source": q.source}


# =====================================================================
# Chat
# =====================================================================

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}(\.[A-Z]{1,2})?$")

_TICKER_STOPWORDS = {
    "AI",
    "IT",
    "US",
    "CN",
    "HK",
    "EU",
    "GDP",
    "CEO",
    "CFO",
    "COO",
    "ROI",
    "ROIC",
    "EPS",
    "PE",
    "PEG",
    "PB",
    "DCF",
    "WACC",
    "FCF",
    "SBC",
    "IPO",
    "ETF",
    "REIT",
    "NEW",
    "BUY",
    "SELL",
    "AVOID",
    "WATCH",
    "HOLD",
    "BUYS",
    "SELLS",
    "THE",
    "AND",
    "FOR",
    "BUT",
    "NOT",
    "YES",
    "NO",
    "WHY",
    "HOW",
    "WHEN",
    "WHAT",
    "WHERE",
    "WHO",
    "CAN",
    "WILL",
    "ARE",
    "WAS",
    "HAS",
    "HAVE",
    "THIS",
    "THAT",
    "WITH",
    "FROM",
    "INTO",
    "ONTO",
    "SHOULD",
    "WOULD",
    "COULD",
    "ONE",
    "TWO",
    "SIX",
    "TEN",
    "AT",
    "ALL",
    "ANY",
    "SOME",
    "MORE",
    "LESS",
    "GOOD",
    "BAD",
    "OK",
    "NOW",
    "LATER",
    "EVER",
    "NEVER",
    "ALSO",
    "JUST",
    "YOU",
    "YOUR",
    "MINE",
    "OURS",
    "THEM",
    "THEIR",
    "WANT",
    "NEED",
    "LIKE",
    "TODAY",
    "MAYBE",
    "AGAIN",
    "THINK",
    "KNOW",
    "SEEM",
    "LOOKS",
    "WORK",
    "MUCH",
    "MANY",
    "WHICH",
    "BEING",
    "DOING",
    "GOING",
    "MAKE",
    "MADE",
    "LOOK",
    "SEE",
    "CHECK",
    "ASK",
    "TELL",
    "GIVE",
    "TAKE",
    "SHI",
    "BU",
    "HAO",
}


def _extract_ticker(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if TICKER_RE.match(raw.upper()) and raw.upper() not in _TICKER_STOPWORDS:
        return raw.upper()
    allcaps = re.findall(r"\b[A-Z]{2,6}(?:\.[A-Z]{1,2})?\b", raw)
    for tok in allcaps:
        if TICKER_RE.match(tok) and tok not in _TICKER_STOPWORDS:
            return tok
    for tok in re.findall(r"\b[A-Za-z]{3,5}\b", raw):
        up = tok.upper()
        if TICKER_RE.match(up) and up not in _TICKER_STOPWORDS:
            return up
    return None


@app.post("/chat/start")
async def chat_start(
    request: Request,
    input: Annotated[str, Form()] = "",
):
    ticker = _extract_ticker(input)
    if not ticker:
        raise HTTPException(400, "没识别到 ticker。试试「AAPL」或「审视 NVDA」。")

    session = ChatSession.new(ticker)
    session.add(ChatMessage.new("user", input.strip()))
    session.add(
        ChatMessage.new(
            "coach",
            f"好。在我跑 {ticker} 数据之前，用一两句话告诉我：你为什么觉得它值得被审视？（说'不确定'也行）",
        )
    )
    save_session(cfg, session)
    return RedirectResponse(f"/chat/{session.session_id}", status_code=302)


@app.get("/chat/{session_id}", response_class=HTMLResponse)
async def chat_page(request: Request, session_id: str):
    if not session_id.isalnum():
        raise HTTPException(404)
    session = load_session(cfg, session_id)
    if not session:
        raise HTTPException(404, "对话不存在或已过期")
    keys = load_keys_from_env()
    return templates.TemplateResponse(
        request,
        "chat/session.html",
        {
            "session": session,
            "session_json": json.dumps(
                {
                    "session_id": session.session_id,
                    "ticker": session.ticker,
                    "audit_status": session.audit_status,
                    "current_stage": session.current_stage,
                    "anchor_thesis": session.anchor_thesis,
                    "report_date": session.report_date,
                },
                ensure_ascii=False,
            ),
            "keys_missing": keys.has_required()[1],
        },
    )


@app.post("/chat/{session_id}/message")
async def chat_message(
    request: Request,
    session_id: str,
    text: Annotated[str, Form()] = "",
    my_market_expectation: Annotated[str, Form()] = "",
    my_variant_view: Annotated[str, Form()] = "",
    tech_mode: Annotated[str, Form()] = "",
):
    if not session_id.isalnum():
        raise HTTPException(404)
    session = load_session(cfg, session_id)
    if not session:
        raise HTTPException(404)
    if session.audit_status != "pending":
        raise HTTPException(400, "审视已开始，无法修改输入")

    if text.strip():
        session.anchor_thesis = text.strip()
        session.add(ChatMessage.new("user", text.strip()))
    if my_market_expectation.strip():
        session.my_market_expectation = my_market_expectation.strip()
    if my_variant_view.strip():
        session.my_variant_view = my_variant_view.strip()
    if tech_mode:
        session.tech_mode = True
    save_session(cfg, session)
    return JSONResponse({"ok": True})


@app.get("/chat/{session_id}/stream")
async def chat_stream(request: Request, session_id: str):
    if not session_id.isalnum():
        raise HTTPException(404)
    session = load_session(cfg, session_id)
    if not session:
        raise HTTPException(404)
    if session.audit_status == "complete":

        def _replay():
            yield _sse(
                {
                    "kind": "already_complete",
                    "report_date": session.report_date,
                    "ticker": session.ticker,
                }
            )

        return StreamingResponse(_replay(), media_type="text/event-stream")

    keys = load_keys_from_env()

    async def _gen():
        yield ":ok\n\n"
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        done = asyncio.Event()

        def producer():
            try:
                for kind, payload in stream_audit(cfg, keys, session):
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("event", {"kind": kind, **payload})),
                        loop,
                    )
            except Exception as e:
                log.error("chat_stream producer failed", extra={"err": str(e)})
                asyncio.run_coroutine_threadsafe(
                    queue.put(("event", {"kind": "error", "message": f"{type(e).__name__}: {e}"})),
                    loop,
                )
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop)

        # Run the sync stream in a thread so we can interleave heartbeats
        import threading

        threading.Thread(target=producer, daemon=True).start()

        while not done.is_set():
            try:
                tag, data = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # Heartbeat — keeps proxies and browsers happy
                yield ":keepalive\n\n"
                continue
            if tag == "done":
                done.set()
                break
            yield _sse(data)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# =====================================================================
# Ask (Perplexity-style Q&A)
# =====================================================================


@app.post("/ask/start")
async def ask_start(
    request: Request,
    query: Annotated[str, Form()],
):
    query = query.strip()
    if not query:
        raise HTTPException(400, "请输入问题")
    ticker = _extract_ticker(query)
    if not ticker:
        raise HTTPException(400, "问题里没找到 ticker。试试「AAPL 值得买吗？」")

    session = AskSession.new(query=query, ticker=ticker)
    save_ask_session(cfg, session)
    return RedirectResponse(f"/ask/{session.session_id}", status_code=302)


@app.get("/ask/{session_id}", response_class=HTMLResponse)
async def ask_page(request: Request, session_id: str):
    if not session_id.isalnum():
        raise HTTPException(404)
    session = load_ask_session(cfg, session_id)
    if not session:
        raise HTTPException(404, "问题不存在或已过期")
    return templates.TemplateResponse(
        request,
        "ask/session.html",
        {
            "session": session,
            "session_json": json.dumps(
                {
                    "session_id": session.session_id,
                    "ticker": session.ticker,
                    "query": session.query,
                    "status": session.status,
                },
                ensure_ascii=False,
            ),
        },
    )


@app.get("/ask/{session_id}/stream")
async def ask_stream(request: Request, session_id: str):
    if not session_id.isalnum():
        raise HTTPException(404)
    session = load_ask_session(cfg, session_id)
    if not session:
        raise HTTPException(404)
    if session.status == "complete":

        def _replay():
            yield _sse({"kind": "already_complete", "ticker": session.ticker})

        return StreamingResponse(_replay(), media_type="text/event-stream")

    keys = load_keys_from_env()

    async def _gen():
        yield ":ok\n\n"
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def producer():
            try:
                for kind, payload in ask_engine.stream_ask(cfg, keys, session):
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("event", {"kind": kind, **payload})),
                        loop,
                    )
            except Exception as e:
                log.error("ask_stream producer failed", extra={"err": str(e)})
                asyncio.run_coroutine_threadsafe(
                    queue.put(("event", {"kind": "error", "message": f"{type(e).__name__}: {e}"})),
                    loop,
                )
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop)

        import threading

        threading.Thread(target=producer, daemon=True).start()

        while True:
            try:
                tag, data = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ":keepalive\n\n"
                continue
            if tag == "done":
                break
            yield _sse(data)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# =====================================================================
# Wisdom library
# =====================================================================


@app.get("/wisdom", response_class=HTMLResponse)
async def wisdom_index(request: Request):
    grouped = wisdom_mod.group_by_theme(cfg)
    preferred_order = [
        "competence",
        "moat",
        "management",
        "valuation",
        "margin_of_safety",
        "asymmetry",
        "variant_view",
        "contrarian",
        "inversion",
        "patience",
        "long_term",
        "sell_discipline",
        "emotion",
        "loss",
        "humility",
    ]
    ordered = []
    for t in preferred_order:
        if t in grouped:
            ordered.append((t, grouped.pop(t)))
    for t in sorted(grouped):
        ordered.append((t, grouped[t]))

    theme_label_cn = {
        "competence": "能力圈 & 谦逊",
        "moat": "护城河 & 好生意",
        "management": "管理层 & 诚信",
        "valuation": "估值 & 价格 vs 价值",
        "margin_of_safety": "安全边际",
        "asymmetry": "非对称性",
        "variant_view": "非共识 (Variant View)",
        "contrarian": "逆向",
        "inversion": "反过来想 (Inversion)",
        "patience": "耐心",
        "long_term": "长期",
        "sell_discipline": "卖出纪律",
        "emotion": "情绪管理",
        "loss": "亏损 & 风险",
        "humility": "谦逊",
        "misc": "其他",
    }

    return templates.TemplateResponse(
        request,
        "wisdom/index.html",
        {
            "grouped": ordered,
            "theme_label": theme_label_cn,
            "total": sum(len(qs) for _, qs in ordered),
        },
    )


@app.get("/wisdom/{quote_id}", response_class=HTMLResponse)
async def wisdom_detail(request: Request, quote_id: str):
    if not re.match(r"^[a-z0-9_]+$", quote_id):
        raise HTTPException(404)
    q = wisdom_mod.get_quote_by_id(cfg, quote_id)
    if not q:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "wisdom/detail.html", {"quote": q})


# =====================================================================
# Legacy audit form
# =====================================================================


@app.get("/audit/new", response_class=HTMLResponse)
async def audit_new_get(request: Request):
    keys = load_keys_from_env()
    ok, missing = keys.has_required()
    return templates.TemplateResponse(
        request,
        "audit/new.html",
        {
            "missing_keys": missing if not ok else [],
        },
    )


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
    if not TICKER_RE.match(ticker):
        raise HTTPException(400, "Ticker 格式无效")

    keys = load_keys_from_env()
    ok, missing = keys.has_required()
    if not ok:
        raise HTTPException(400, f"缺 key: {missing} —— 在 .env 里补上")

    try:
        report = run_audit_auto(
            cfg,
            keys,
            ticker,
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


# =====================================================================
# Audit view / diff
# =====================================================================


@app.get("/audit/{ticker}/diff", response_class=HTMLResponse)
async def audit_diff(request: Request, ticker: str):
    ticker = ticker.upper()
    current, previous = load_last_two_audits(cfg, ticker)
    if not current:
        raise HTTPException(404, "该 ticker 没有 audit")
    if not previous:
        raise HTTPException(404, "至少需要两次 audit 才能 diff")
    diff_html = render_audit_diff_html(current, previous)
    return templates.TemplateResponse(
        request,
        "audit/diff.html",
        {
            "ticker": ticker,
            "current_date": current.audit_date,
            "previous_date": previous.audit_date,
            "diff_html": diff_html,
        },
    )


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

    return templates.TemplateResponse(
        request,
        "audit/report.html",
        {
            "report": report,
            "ticker": ticker,
            "date": date,
            "diff_html": diff_html,
            "is_holding": is_holding(cfg, ticker),
        },
    )


# =====================================================================
# History
# =====================================================================


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
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "audits": audits,
            "q": q,
            "filter_action": filter_action,
            "stale_count": stale_count,
        },
    )


# =====================================================================
# Portfolio
# =====================================================================


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
            # v0.6: review-needed signal — prompts user to re-audit when
            # price has moved materially since last audit.
            "audit_price": None,
            "price_change_pct": None,
            "review_needed": False,
            "review_reason": None,
        }

        if current:
            row["audit_date"] = current.audit_date
            try:
                age = (today - date.fromisoformat(current.audit_date)).days
                row["age_days"] = age
                row["stale_level"] = (
                    "very_stale" if age >= 180 else "stale" if age >= 90 else "fresh"
                )
            except Exception:
                age = None
            if current.thesis:
                row["target_buy"] = current.thesis.target_buy_price
                row["target_sell"] = current.thesis.target_sell_price
            s7 = next((s for s in current.stages if s.stage_id == 7), None)
            if s7:
                mos = s7.raw_data.get("margin_of_safety_pct")
                if mos is not None:
                    row["mos_pct"] = mos
                audit_price = s7.raw_data.get("current_price")
                if audit_price:
                    row["audit_price"] = audit_price
                    if price and audit_price > 0:
                        chg = (price - audit_price) / audit_price * 100
                        row["price_change_pct"] = chg
                        # Review-needed heuristic: audit >= 30 days old AND
                        # price moved >= 15%. Not "stop-loss" — just a prompt
                        # to re-verify the thesis with fresh numbers.
                        if row.get("age_days") and row["age_days"] >= 30 and abs(chg) >= 15:
                            row["review_needed"] = True
                            direction = "涨" if chg > 0 else "跌"
                            row["review_reason"] = (
                                f"自 audit 已 {direction} {abs(chg):.0f}% "
                                f"(已过 {row['age_days']} 天)"
                            )
            if price and row["target_buy"] and row["target_sell"]:
                if price <= row["target_buy"]:
                    row["status"] = "buy_zone"
                elif price >= row["target_sell"]:
                    row["status"] = "sell_zone"
                else:
                    row["status"] = "hold"
        rows.append(row)

    return templates.TemplateResponse(request, "portfolio.html", {"rows": rows})


# =====================================================================
# Learn
# =====================================================================


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
    return templates.TemplateResponse(
        request,
        "learn/concept.html",
        {
            "content": content_html,
            "slug": slug,
        },
    )


# =====================================================================
# API
# =====================================================================


@app.get("/api/status", response_class=JSONResponse)
async def api_status():
    return {
        "status": "ok",
        "version": "0.5.0",
        "mode": "single-user",
        "timestamp": datetime.now().isoformat(),
    }
