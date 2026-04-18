"""
Moatlens CLI entry point.

Usage:
    python -m cli audit AAPL
    python -m cli audit NVDA --tech
    python -m cli audit TSLA --auto                 # no wizard, run all at once
    python -m cli audit NVDA --thesis "CUDA moat + AI cycle"
    python -m cli list
    python -m cli show NVDA 2026-04-17
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
from engine.report_renderer import render_markdown, render_summary_line
from shared.config import load_config, load_keys_from_env
from shared.storage import list_audits, save_audit


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
        for f in result.findings[:15]:  # cap to avoid overflow
            console.print(f)

    cost = result.raw_data.get("cost_usd", 0)
    if cost:
        console.print(f"[dim]  API cost: ${cost:.4f} · elapsed {result.elapsed_seconds:.1f}s[/]")


@app.command()
def audit(
    ticker: str,
    auto: bool = typer.Option(False, "--auto", "-a", help="Run all stages without pausing"),
    tech: bool = typer.Option(False, "--tech", help="Tech stock mode (SBC check, higher PE tolerance)"),
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
            "[dim](This is your anchor. Claude references it when inverting your thesis.)[/]",
            default="",
        )

    if auto:
        # Auto mode — run everything
        def cb(num, result):
            _print_stage(num, result)
        report = run_audit_auto(cfg, keys, ticker, anchor_thesis=thesis, tech_mode=tech, progress_callback=cb)
    else:
        # Wizard mode — pause after each stage
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

    # Final verdict
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

    # Save
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
    t.add_column("Path")
    for ticker, date, path in audits[:30]:
        t.add_row(ticker, date, str(path))
    console.print(t)


@app.command()
def show(ticker: str, date: str):
    """Display a saved audit report."""
    cfg = load_config()
    from shared.storage import audits_dir
    md_path = audits_dir(cfg, ticker) / f"{date}.md"
    if not md_path.exists():
        rprint(f"[red]Not found: {md_path}[/]")
        raise typer.Exit(1)
    console.print(md_path.read_text(encoding="utf-8"))


@app.command()
def doctor():
    """Verify BYOK API keys and connectivity."""
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).parent.parent / "bin" / "doctor.py")])


if __name__ == "__main__":
    app()
