"""
stock_analyzer.py — Main CLI entry point for the stock analysis platform.

Orchestrates all fetch tools and the decision engine, then prints a formatted
terminal report using rich.

Usage:
    python tools/stock_analyzer.py AAPL
    python tools/stock_analyzer.py TSLA --save
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# Force UTF-8 output on Windows to avoid encoding errors
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from utils import tmp_path, load_json

console = Console(force_terminal=True)


def _color_score(score: float) -> str:
    if score >= 0.3:
        return "bright_green"
    elif score >= 0.1:
        return "green"
    elif score >= -0.1:
        return "yellow"
    elif score >= -0.3:
        return "red"
    else:
        return "bright_red"


def _verdict_style(verdict: str) -> str:
    return {"Bullish": "bold bright_green", "Bearish": "bold bright_red", "Neutral": "bold yellow"}.get(verdict, "white")


def _rec_style(rec: str) -> str:
    return {"Buy": "bold green on dark_green", "Sell": "bold red on dark_red", "Wait": "bold yellow"}.get(rec, "white")


def print_report(ticker: str, decision: dict, overview: dict, fundamentals: dict,
                 news: dict, technicals: dict, risks: dict, opportunities: dict):
    console.print()

    # ── Header ─────────────────────────────────────────────────────────────────
    name = overview.get("name", ticker)
    sector = overview.get("sector", "N/A")
    industry = overview.get("industry", "N/A")
    current = decision.get("current_price", "N/A")
    run_date = decision.get("run_date", datetime.now().strftime("%Y-%m-%d %H:%M"))

    console.print(Panel(
        f"[bold white]{name}[/bold white]  [dim]({ticker})[/dim]\n"
        f"[dim]{sector} › {industry}[/dim]\n"
        f"[dim]Current Price: [/dim][bold white]${current}[/bold white]   "
        f"[dim]Analysis: {run_date}[/dim]",
        title="[bold cyan]STOCK ANALYSIS REPORT[/bold cyan]",
        border_style="cyan",
        expand=False,
    ))

    # ── Company Overview ───────────────────────────────────────────────────────
    desc = overview.get("description", "No description available.")
    if len(desc) > 400:
        desc = desc[:400] + "..."
    console.print(Panel(desc, title="[cyan]Company Overview[/cyan]", border_style="dim"))

    # ── Score table ────────────────────────────────────────────────────────────
    table = Table(title="Module Scores", box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Module", style="white", width=16)
    table.add_column("Score", justify="center", width=8)
    table.add_column("Rating", justify="center", width=14)
    table.add_column("Weight", justify="center", width=8)

    breakdown = decision.get("score_breakdown", {})

    def _fmt_score(s):
        col = _color_score(s)
        return f"[{col}]{s:+.2f}[/{col}]"

    table.add_row("Fundamentals",
        _fmt_score(breakdown.get("fundamentals", {}).get("adjusted", 0)),
        f"[{'green' if fundamentals.get('rating')=='Strong' else 'red' if fundamentals.get('rating')=='Weak' else 'yellow'}]{fundamentals.get('rating','N/A')}[/]",
        "25%")
    table.add_row("News / Sentiment",
        _fmt_score(breakdown.get("news", {}).get("adjusted", 0)),
        f"[{'green' if news.get('sentiment')=='Bullish' else 'red' if news.get('sentiment')=='Bearish' else 'yellow'}]{news.get('sentiment','N/A')}[/]",
        "20%")
    table.add_row("Technical",
        _fmt_score(breakdown.get("technicals", {}).get("adjusted", 0)),
        f"[{'green' if technicals.get('trend',{}).get('long_term')=='Bullish' else 'red'}]{technicals.get('trend',{}).get('long_term','N/A')} Trend[/]",
        "30%")
    table.add_row("Risk",
        _fmt_score(breakdown.get("risk", {}).get("adjusted", 0)),
        f"[{'green' if risks.get('risk_level')=='Low' else 'red' if risks.get('risk_level')=='High' else 'yellow'}]{risks.get('risk_level','N/A')}[/]",
        "15%")
    table.add_row("Opportunities",
        _fmt_score(breakdown.get("opportunities", {}).get("adjusted", 0)),
        f"[{'green' if opportunities.get('opportunity_level')=='High' else 'yellow'}]{opportunities.get('opportunity_level','N/A')}[/]",
        "10%")

    console.print(table)

    # ── Technical indicators ───────────────────────────────────────────────────
    tech_table = Table(title="Technical Indicators", box=box.SIMPLE, header_style="bold cyan")
    tech_table.add_column("Indicator", width=14)
    tech_table.add_column("Value", justify="right", width=12)
    tech_table.add_column("Signal", width=20)

    rsi = technicals.get("rsi")
    rsi_sig = "[green]Oversold (BUY)[/green]" if rsi and rsi < 30 else "[red]Overbought (SELL)[/red]" if rsi and rsi > 70 else "[yellow]Neutral[/yellow]"
    tech_table.add_row("RSI (14)", f"{rsi:.1f}" if rsi else "N/A", rsi_sig)

    macd = technicals.get("macd")
    macd_sig = technicals.get("macd_signal")
    if macd is not None and macd_sig is not None:
        macd_label = "[green]Bullish[/green]" if macd > macd_sig else "[red]Bearish[/red]"
        tech_table.add_row("MACD", f"{macd:.3f}", macd_label)

    sma50 = technicals.get("sma50")
    sma200 = technicals.get("sma200")
    if sma50 and sma200:
        cross = "[green]Golden Cross[/green]" if sma50 > sma200 else "[red]Death Cross[/red]"
        tech_table.add_row("SMA 50/200", f"{sma50:.2f}/{sma200:.2f}", cross)

    ns = technicals.get("nearest_support")
    nr = technicals.get("nearest_resistance")
    if ns:
        tech_table.add_row("Support", f"${ns:.2f}", "[green]Key level[/green]")
    if nr:
        tech_table.add_row("Resistance", f"${nr:.2f}", "[red]Key level[/red]")

    console.print(tech_table)

    # ── News highlights ────────────────────────────────────────────────────────
    news_panel_lines = []
    pos = news.get("top_positive_headlines", [])
    neg = news.get("top_negative_headlines", [])
    if pos:
        news_panel_lines.append("[green]Positive:[/green]")
        for h in pos[:2]:
            news_panel_lines.append(f"  • {h[:90]}")
    if neg:
        news_panel_lines.append("[red]Negative:[/red]")
        for h in neg[:2]:
            news_panel_lines.append(f"  • {h[:90]}")
    key_events = news.get("key_events", [])
    if key_events:
        news_panel_lines.append(f"\n[cyan]Key Events:[/cyan] {', '.join(key_events[:5])}")
    if news_panel_lines:
        console.print(Panel("\n".join(news_panel_lines),
                            title=f"[cyan]News ({news.get('total_articles',0)} articles — {news.get('sentiment','N/A')})[/cyan]",
                            border_style="dim"))

    # ── Risk & Opportunity ─────────────────────────────────────────────────────
    ro_table = Table(box=box.SIMPLE, show_header=False)
    ro_table.add_column("Cat", width=14, style="bold")
    ro_table.add_column("Details")
    risk_reasons = risks.get("reasoning", [])[:2]
    opp_reasons = opportunities.get("reasoning", [])[:2]
    for r in risk_reasons:
        ro_table.add_row("[red]Risk[/red]", r)
    for o in opp_reasons:
        ro_table.add_row("[green]Opportunity[/green]", o)
    if risk_reasons or opp_reasons:
        console.print(ro_table)

    # ── Verdict ────────────────────────────────────────────────────────────────
    verdict = decision["verdict"]
    rec = decision["recommendation"]
    conf = decision["confidence_pct"]
    score = decision["final_score"]
    timing = decision.get("timing", "")

    console.print()
    console.print(Panel(
        f"[{_verdict_style(verdict)}]  {verdict}  [/{_verdict_style(verdict)}]   "
        f"Score: [{_color_score(score)}]{score:+.3f}[/{_color_score(score)}]   "
        f"Confidence: [bold white]{conf}%[/bold white]\n\n"
        f"[{_rec_style(rec)}]  RECOMMENDATION: {rec}  [/{_rec_style(rec)}]\n\n"
        f"[dim]{timing}[/dim]",
        title="[bold]FINAL VERDICT[/bold]",
        border_style={"Bullish": "green", "Bearish": "red", "Neutral": "yellow"}.get(verdict, "white"),
        expand=False,
    ))

    # ── Timing details ─────────────────────────────────────────────────────────
    if rec == "Buy":
        console.print(
            f"  Entry Zone:  [green]${decision.get('entry_zone_low','?'):.2f} – ${decision.get('entry_zone_high','?'):.2f}[/green]\n"
            f"  Stop Loss:   [red]${decision.get('stop_loss','?'):.2f}[/red]\n"
            f"  Target:      [green]${decision.get('target_price','?'):.2f}[/green]"
        )
    elif rec == "Sell":
        console.print(
            f"  Stop Loss:   [red]${decision.get('stop_loss','?'):.2f}[/red]"
        )

    console.print()

    # ── Learning system hint ───────────────────────────────────────────────────
    console.print("[dim]Tip: After closing this trade, run:[/dim]")
    console.print(f"[dim]  python tools/record_trade.py {ticker} <entry_price> {rec}[/dim]")
    console.print()


def run_analysis(ticker: str, save: bool = False):
    ticker = ticker.upper()

    console.print(f"\n[cyan]Analyzing [bold]{ticker}[/bold]...[/cyan]")

    steps = [
        ("Company overview",   "fetch_company_overview", ticker),
        ("Fundamentals",       "fetch_fundamentals",     ticker),
        ("News & sentiment",   "fetch_news",             ticker),
        ("Technical analysis", "fetch_technicals",       ticker),
        ("Risk factors",       "fetch_risk_factors",     ticker),
        ("Opportunities",      "fetch_opportunities",    ticker),
    ]

    for label, module_name, arg in steps:
        console.print(f"  [dim]> {label}...[/dim]", end="")
        try:
            mod = __import__(module_name)
            fn_name = module_name.replace("fetch_", "fetch_")
            fn = getattr(mod, fn_name)
            fn(arg)
            console.print(f" [green]✓[/green]")
        except SystemExit:
            console.print(f" [red]✗ failed (see above)[/red]")
            sys.exit(1)
        except Exception as e:
            console.print(f" [yellow]⚠ {e}[/yellow]")

    # Run decision engine
    console.print("  [dim]> Computing verdict...[/dim]", end="")
    try:
        from decision_engine import make_decision
        decision = make_decision(ticker)
        console.print(" [green]✓[/green]")
    except Exception as e:
        console.print(f" [red]✗ {e}[/red]")
        sys.exit(1)

    # Load all module outputs for display
    overview       = load_json(tmp_path(ticker, "overview"))
    fundamentals   = load_json(tmp_path(ticker, "fundamentals"))
    news           = load_json(tmp_path(ticker, "news"))
    technicals     = load_json(tmp_path(ticker, "technicals"))
    risks          = load_json(tmp_path(ticker, "risks"))
    opportunities  = load_json(tmp_path(ticker, "opportunities"))

    print_report(ticker, decision, overview, fundamentals, news, technicals, risks, opportunities)

    if save:
        from utils import save_json
        out = tmp_path(ticker, "full_report")
        save_json(out, decision)
        console.print(f"[dim]Full report saved to: {out}[/dim]\n")


def main():
    parser = argparse.ArgumentParser(
        description="Stock analysis platform — Buy/Wait/Sell with confidence score"
    )
    parser.add_argument("ticker", help="Stock ticker symbol (e.g. AAPL, TSLA)")
    parser.add_argument("--save", action="store_true", help="Save full report JSON to .tmp/")
    args = parser.parse_args()

    run_analysis(args.ticker, save=args.save)


if __name__ == "__main__":
    main()
