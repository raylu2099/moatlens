"""
Moatlens CLI.

Common flows:
    python -m cli audit AAPL                          # full audit (wizard)
    python -m cli audit AAPL --auto                   # non-interactive
    python -m cli audit AAPL --tech                   # tech stock mode
    python -m cli audit AAPL --no-claude              # skip stages 3/4/8 (free dry-run)
    python -m cli audit AAPL --only 6                 # only re-run DCF
    python -m cli audit AAPL --only 5,6,7             # re-run a subset
    python -m cli audit AAPL --from 5                 # run stages 5..8
    python -m cli audit AAPL --resume                 # continue from latest partial audit
    python -m cli list
    python -m cli show AAPL 2026-04-17
    python -m cli diff AAPL
    python -m cli doctor

Holdings tracking:
    python -m cli hold add AAPL --size 5%
    python -m cli hold list
    python -m cli hold check
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from engine.models import Verdict
from engine.orchestrator import run_audit_auto, run_audit_wizard
from engine.report_renderer import render_markdown
from shared.config import load_config, load_keys_from_env
from shared.storage import (
    audits_dir, list_audits, load_audit, load_last_two_audits, save_audit,
)


app = typer.Typer(help="Moatlens — 价值投资审视工具（Buffett/Munger lens）")
hold_app = typer.Typer(help="持仓跟踪 —— 标记 ticker 为持仓/观察，批量复盘")
app.add_typer(hold_app, name="hold")
console = Console()


VERDICT_COLOR = {
    Verdict.PASS: "green",
    Verdict.BORDERLINE: "yellow",
    Verdict.FAIL: "red",
    Verdict.SKIP: "dim",
}


def _parse_stage_list(s: str) -> list[int]:
    """Accepts '1,2,3' or '6' or '1 2 3'."""
    out = []
    for part in s.replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            raise typer.BadParameter(f"Not an int: {part!r}")
        if not 1 <= n <= 8:
            raise typer.BadParameter(f"Stage out of range 1-8: {n}")
        out.append(n)
    return out


def _print_stage(num: int, result) -> None:
    color = VERDICT_COLOR.get(result.verdict, "white")
    console.print()
    console.rule(f"[{color}]Stage {num}: {result.stage_name} — {result.verdict.value}[/]")

    if result.metrics:
        t = Table(show_header=True, header_style="bold cyan")
        t.add_column("指标")
        t.add_column("值", justify="right")
        t.add_column("阈值")
        t.add_column("通过", justify="center")
        for m in result.metrics:
            val = f"{m.value}{' ' + m.unit if m.unit else ''}" if m.value is not None else "—"
            pass_str = "✅" if m.pass_ else ("❌" if m.pass_ is False else "—")
            t.add_row(m.name, str(val), m.threshold, pass_str)
        console.print(t)

    if result.findings:
        for f in result.findings[:15]:
            console.print(f)

    cost = result.raw_data.get("cost_usd", 0)
    if cost:
        console.print(f"[dim]  API 成本: ${cost:.4f} · 耗时 {result.elapsed_seconds:.1f}s[/]")


@app.command()
def audit(
    ticker: str,
    auto: bool = typer.Option(False, "--auto", "-a", help="一次跑完，不在每 stage 之间暂停"),
    tech: bool = typer.Option(False, "--tech", help="科技股模式 (考虑 SBC 稀释, 更高 PE 容忍)"),
    thesis: str = typer.Option("", "--thesis", "-t", help="你的初始 1-2 句论点"),
    no_claude: bool = typer.Option(False, "--no-claude", help="跳过 stage 3/4/8 的 Claude 调用（免费 dry-run）"),
    only: str = typer.Option("", "--only", help="只跑指定 stage，例如 '6' 或 '5,6,7'"),
    from_stage: int = typer.Option(0, "--from", help="从指定 stage 开始跑 (1-8)"),
    resume: bool = typer.Option(False, "--resume", help="基于该 ticker 今天的最新 audit 增量续跑"),
):
    """运行 8-stage 审视流水线。"""
    cfg = load_config()
    keys = load_keys_from_env()

    ok, missing = keys.has_required()
    if not ok and not no_claude:
        # --no-claude still needs FD + Perplexity (stages 5/6 use FD; s3/s4 use perplexity).
        # So missing keys is still a problem. But we warn, let user proceed only if they really want.
        rprint(f"[red]缺 API keys: {', '.join(missing)}[/]")
        rprint(f"[yellow]在 {cfg.project_root / '.env'} 里填好再跑 (模板: .env.example)[/]")
        raise typer.Exit(1)

    only_stages = _parse_stage_list(only) if only else None
    from_s = from_stage if from_stage else None

    # --- Anchor thesis + variant view ---
    market_expectation = ""
    variant_view = ""
    if not thesis and not auto and not only_stages and from_s in (None, 1):
        console.print()
        thesis = Prompt.ask(
            "[bold]先用 2-3 句话写下：为什么这支值得被审视？[/]\n"
            "[dim](这是你的锚。Stage 8 做反方论证时会引用它。)[/]",
            default="",
        )

    if not only_stages and from_s in (None, 1) and not no_claude:
        console.print()
        market_expectation = Prompt.ask(
            "[bold]市场（当前价格）在 price in 什么？[/]\n"
            "[dim](反向 DCF 之外，你感受到的市场共识是什么 —— 具体点。)[/]",
            default="",
        )
        variant_view = Prompt.ask(
            "[bold]你与市场的差异观点（variant view）是什么？[/]\n"
            "[dim](Howard Marks: 超额收益 = 正确 × 非共识。没有差异就不该下注。)[/]",
            default="",
        )

    # --- Resume? ---
    resume_report = None
    if resume:
        today = datetime.now().strftime("%Y-%m-%d")
        resume_report = load_audit(cfg, ticker, today)
        if resume_report:
            console.print(f"[yellow]➤ 续跑今天的 {ticker.upper()} audit（已有 {len(resume_report.stages)} 个 stage 结果）[/]")
        else:
            rprint(f"[dim]没有找到 {ticker.upper()} {today} 的 partial audit，从头开始[/]")

    console.print(Panel(
        f"[bold cyan]Moatlens 审视[/] · [bold]{ticker.upper()}[/]\n"
        f"模式: {'Auto' if auto else 'Wizard (交互)'}"
        + (f" · Tech" if tech else "")
        + (f" · --no-claude" if no_claude else "")
        + (f" · --only {only_stages}" if only_stages else "")
        + (f" · --from {from_s}" if from_s else "")
        + (f"\nAnchor: {thesis}" if thesis else ""),
        border_style="cyan",
    ))

    common_kwargs = dict(
        anchor_thesis=thesis, tech_mode=tech,
        resume_from=resume_report,
        skip_claude=no_claude,
        only_stages=only_stages,
        from_stage=from_s,
        my_market_expectation=market_expectation,
        my_variant_view=variant_view,
    )

    if auto or only_stages or from_s:
        def cb(num, result):
            _print_stage(num, result)
        report = run_audit_auto(cfg, keys, ticker, progress_callback=cb, **common_kwargs)
    else:
        gen = run_audit_wizard(cfg, keys, ticker, **common_kwargs)
        report = None
        try:
            num, result, report = next(gen)
            _print_stage(num, result)
            while True:
                console.print()
                if not Confirm.ask(f"[bold green]继续 Stage {num + 1}?[/]", default=True):
                    rprint("[yellow]用户在 stage 边界中止。[/]")
                    break
                num, result, report = gen.send(True)
                _print_stage(num, result)
        except StopIteration as e:
            if e.value:
                report = e.value

    if report is None:
        rprint("[red]没有生成 report。[/]")
        raise typer.Exit(1)

    console.print()
    console.rule("[bold magenta]📋 最终判断[/]")
    action = report.overall_action.value if report.overall_action else "PENDING"
    conf = report.overall_confidence.value if report.overall_confidence else "?"
    pass_ct = sum(1 for s in report.stages if s.verdict == Verdict.PASS)
    console.print(Panel(
        f"[bold]{ticker.upper()}[/] · {action} · 置信度 {conf}\n"
        f"通过: {pass_ct}/{len(report.stages)}\n"
        f"API 总成本: ${report.total_api_cost_usd:.3f}",
        border_style="magenta",
    ))

    md = render_markdown(report)
    md_path, json_path = save_audit(cfg, report, md)
    console.print(f"\n[dim]已保存:[/]\n  {md_path}\n  {json_path}")


@app.command(name="list")
def list_cmd():
    """列出过往所有 audit。"""
    cfg = load_config()
    audits = list_audits(cfg)
    if not audits:
        rprint("[dim]还没有 audit. 用 `python -m cli audit TICKER` 开始。[/]")
        return
    t = Table(title="过往 Audits", show_header=True, header_style="bold cyan")
    t.add_column("Ticker")
    t.add_column("Date")
    t.add_column("Age")
    t.add_column("Action")
    t.add_column("Cost", justify="right")
    now = datetime.now().date()
    for a in audits[:50]:
        try:
            age = (now - datetime.fromisoformat(a["audit_date"]).date()).days
        except Exception:
            age = None
        age_str = "—"
        if age is not None:
            if age >= 180:
                age_str = f"[red]{age}d[/]"
            elif age >= 90:
                age_str = f"[yellow]{age}d[/]"
            else:
                age_str = f"[dim]{age}d[/]"
        t.add_row(a["ticker"], a["audit_date"], age_str,
                  a["action"] or "—", f"${a['total_cost_usd']:.3f}")
    console.print(t)


@app.command()
def show(ticker: str, date: str):
    """显示已保存的 audit report（markdown）。"""
    cfg = load_config()
    md_path = audits_dir(cfg, ticker) / f"{date}.md"
    if not md_path.exists():
        rprint(f"[red]未找到: {md_path}[/]")
        raise typer.Exit(1)
    console.print(md_path.read_text(encoding="utf-8"))


@app.command()
def diff(ticker: str):
    """比较某 ticker 最近两次 audit —— thesis 演变了吗？"""
    from web.diff import render_audit_diff_text
    cfg = load_config()
    current, previous = load_last_two_audits(cfg, ticker)
    if not current:
        rprint(f"[red]{ticker.upper()} 没有 audit 记录[/]")
        raise typer.Exit(1)
    if not previous:
        rprint(f"[yellow]{ticker.upper()} 只有一次 audit ({current.audit_date})，无法 diff[/]")
        raise typer.Exit(0)
    console.print(render_audit_diff_text(current, previous))


@app.command()
def doctor():
    """体检 API key 与依赖。"""
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).parent.parent / "bin" / "doctor.py")])


# =====================================================================
# Holdings sub-app
# =====================================================================

@hold_app.command("add")
def hold_add(
    ticker: str,
    size: str = typer.Option("", "--size", help='仓位百分比，例如 "5%" 或 "核心 8%"'),
    note: str = typer.Option("", "--note", help="备注（为何买、入场价格等）"),
):
    """标记 ticker 为持仓。"""
    from shared.holdings import add_holding, load_holdings
    cfg = load_config()
    add_holding(cfg, ticker, size=size, note=note)
    rprint(f"[green]✓[/] 已加入持仓: {ticker.upper()}" + (f"  仓位={size}" if size else ""))
    hold_list()


@hold_app.command("remove")
def hold_remove(ticker: str):
    """移除持仓标记。"""
    from shared.holdings import remove_holding
    cfg = load_config()
    if remove_holding(cfg, ticker):
        rprint(f"[yellow]-[/] 已移除: {ticker.upper()}")
    else:
        rprint(f"[dim]没有该持仓: {ticker.upper()}[/]")


@hold_app.command("list")
def hold_list():
    """列出当前持仓。"""
    from shared.holdings import load_holdings
    cfg = load_config()
    hs = load_holdings(cfg)
    if not hs:
        rprint("[dim]目前没有标记的持仓。用 `python -m cli hold add TICKER --size '5%'` 添加。[/]")
        return
    t = Table(title="持仓", show_header=True, header_style="bold gold1")
    t.add_column("Ticker")
    t.add_column("仓位")
    t.add_column("加入日期")
    t.add_column("备注")
    for h in hs:
        t.add_row(h["ticker"], h.get("size", ""), h.get("added_at", ""), h.get("note", "")[:40])
    console.print(t)


@hold_app.command("check")
def hold_check():
    """对所有持仓做一次简短对账：当前价 vs target_buy / target_sell 从最近一次 audit 里读。"""
    from shared.holdings import load_holdings
    from engine.providers import yfinance_provider as yfp
    cfg = load_config()
    hs = load_holdings(cfg)
    if not hs:
        rprint("[dim]目前没有持仓。[/]")
        return

    t = Table(title="持仓对账", show_header=True, header_style="bold cyan")
    t.add_column("Ticker")
    t.add_column("当前价", justify="right")
    t.add_column("理想买入", justify="right")
    t.add_column("开始减仓", justify="right")
    t.add_column("最近 Audit 日期")
    t.add_column("Audit Age")
    t.add_column("状态")

    now_d = datetime.now().date()
    for h in hs:
        ticker = h["ticker"]
        current, _ = load_last_two_audits(cfg, ticker)
        if not current or not current.thesis:
            t.add_row(ticker, "—", "—", "—", "—", "—", "[red]缺 audit[/]")
            continue

        try:
            price = yfp.fetch_current_price(ticker)
        except Exception:
            price = None
        tb = current.thesis.target_buy_price
        ts = current.thesis.target_sell_price
        age_d = (now_d - datetime.fromisoformat(current.audit_date).date()).days
        age_str = f"[red]{age_d}d[/]" if age_d >= 180 else (
            f"[yellow]{age_d}d[/]" if age_d >= 90 else f"[dim]{age_d}d[/]"
        )

        status = "[dim]—[/]"
        if price and tb and ts:
            if price <= tb:
                status = "[green]🟢 加仓区[/]"
            elif price >= ts:
                status = "[red]🔴 减仓区[/]"
            else:
                status = "[yellow]🟡 持有[/]"

        t.add_row(
            ticker,
            f"${price:.2f}" if price else "—",
            f"${tb:.2f}" if tb else "—",
            f"${ts:.2f}" if ts else "—",
            current.audit_date,
            age_str,
            status,
        )
    console.print(t)


if __name__ == "__main__":
    app()
