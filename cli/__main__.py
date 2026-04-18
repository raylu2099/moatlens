"""
Moatlens CLI.

Usage:
    python -m cli audit AAPL
    python -m cli audit NVDA --tech
    python -m cli audit TSLA --auto
    python -m cli audit NVDA --thesis "CUDA moat + AI cycle"
    python -m cli list
    python -m cli show AAPL 2026-04-17
    python -m cli diff AAPL
    python -m cli doctor
"""
from __future__ import annotations

import sys
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
    audits_dir, list_audits, load_last_two_audits, save_audit,
)


app = typer.Typer(help="Moatlens — Buffett/Munger lens for value investors.")
console = Console()


VERDICT_COLOR = {
    Verdict.PASS: "green",
    Verdict.BORDERLINE: "yellow",
    Verdict.FAIL: "red",
    Verdict.SKIP: "dim",
}


def _print_stage(num: int, result) -> None:
    color = VERDICT_COLOR.get(result.verdict, "white")
    console.print()
    console.rule(f"[{color}]Stage {num}: {result.stage_name} — {result.verdict.value}[/]")

    if result.metrics:
        t = Table(show_header=True, header_style="bold cyan")
        t.add_column("Metric")
        t.add_column("Value", justify="right")
        t.add_column("Target")
        t.add_column("Pass", justify="center")
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
        console.print(f"[dim]  API cost: ${cost:.4f} · elapsed {result.elapsed_seconds:.1f}s[/]")


@app.command()
def audit(
    ticker: str,
    auto: bool = typer.Option(False, "--auto", "-a", help="Run all stages without pausing"),
    tech: bool = typer.Option(False, "--tech", help="Tech stock mode"),
    thesis: str = typer.Option("", "--thesis", "-t", help="Your initial one-sentence thesis"),
):
    """Run an 8-stage audit on a ticker."""
    cfg = load_config()
    keys = load_keys_from_env()

    ok, missing = keys.has_required()
    if not ok:
        rprint(f"[red]Missing keys: {', '.join(missing)}[/]")
        rprint(f"[yellow]Add them to {cfg.project_root / '.env'} (see .env.example)[/]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold cyan]Moatlens Audit[/] · [bold]{ticker.upper()}[/]\n"
        f"Mode: {'Auto' if auto else 'Wizard (interactive)'}"
        + (f" · Tech" if tech else "")
        + (f"\nAnchor: {thesis}" if thesis else ""),
        border_style="cyan",
    ))

    if not thesis and not auto:
        console.print()
        thesis = Prompt.ask(
            "[bold]Before we start, in 2-3 sentences: why is this worth auditing?[/]\n"
            "[dim](Your anchor — Claude references it when inverting your thesis.)[/]",
            default="",
        )

    if auto:
        def cb(num, result):
            _print_stage(num, result)
        report = run_audit_auto(
            cfg, keys, ticker, anchor_thesis=thesis, tech_mode=tech, progress_callback=cb,
        )
    else:
        gen = run_audit_wizard(cfg, keys, ticker, anchor_thesis=thesis, tech_mode=tech)
        report = None
        try:
            num, result, report = next(gen)
            _print_stage(num, result)
            while True:
                console.print()
                if not Confirm.ask(f"[bold green]Continue to Stage {num + 1}?[/]", default=True):
                    rprint("[yellow]Aborted by user at stage boundary.[/]")
                    break
                num, result, report = gen.send(True)
                _print_stage(num, result)
        except StopIteration as e:
            if e.value:
                report = e.value

    if report is None:
        rprint("[red]No report generated.[/]")
        raise typer.Exit(1)

    console.print()
    console.rule("[bold magenta]📋 Final Verdict[/]")
    action = report.overall_action.value if report.overall_action else "PENDING"
    conf = report.overall_confidence.value if report.overall_confidence else "?"
    console.print(Panel(
        f"[bold]{ticker.upper()}[/] · {action} · Confidence {conf}\n"
        f"Passes: {sum(1 for s in report.stages if s.verdict == Verdict.PASS)}/{len(report.stages)}\n"
        f"Total API cost: ${report.total_api_cost_usd:.3f}",
        border_style="magenta",
    ))

    md = render_markdown(report)
    md_path, json_path = save_audit(cfg, report, md)
    console.print(f"\n[dim]Saved:[/]\n  {md_path}\n  {json_path}")


@app.command(name="list")
def list_cmd():
    """List all past audits."""
    cfg = load_config()
    audits = list_audits(cfg)
    if not audits:
        rprint("[dim]No audits yet. Run `python -m cli audit TICKER` to start.[/]")
        return
    t = Table(title="Past Audits", show_header=True, header_style="bold cyan")
    t.add_column("Ticker")
    t.add_column("Date")
    t.add_column("Action")
    t.add_column("Cost", justify="right")
    for a in audits[:50]:
        t.add_row(a["ticker"], a["audit_date"], a["action"] or "—", f"${a['total_cost_usd']:.3f}")
    console.print(t)


@app.command()
def show(ticker: str, date: str):
    """Display a saved audit report."""
    cfg = load_config()
    md_path = audits_dir(cfg, ticker) / f"{date}.md"
    if not md_path.exists():
        rprint(f"[red]Not found: {md_path}[/]")
        raise typer.Exit(1)
    console.print(md_path.read_text(encoding="utf-8"))


@app.command()
def diff(ticker: str):
    """Compare the two most recent audits of a ticker — how has the thesis evolved?"""
    from web.diff import render_audit_diff_text
    cfg = load_config()
    current, previous = load_last_two_audits(cfg, ticker)
    if not current:
        rprint(f"[red]No audits for {ticker.upper()}[/]")
        raise typer.Exit(1)
    if not previous:
        rprint(f"[yellow]Only one audit for {ticker.upper()} ({current.audit_date}). Need 2 to diff.[/]")
        raise typer.Exit(0)
    console.print(render_audit_diff_text(current, previous))


@app.command()
def doctor():
    """Verify API keys and provider connectivity."""
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).parent.parent / "bin" / "doctor.py")])


if __name__ == "__main__":
    app()
