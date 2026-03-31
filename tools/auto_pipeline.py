"""
auto_pipeline.py — Autonomous learning pipeline orchestrator.

Runs the full cycle without any Streamlit dependency:
  1. Close expired paper trades (regular + volatile)
  2. Run learning cycle if enough data
  3. Scan regular market → analyze top picks → register paper trades
  4. Scan volatile market → register volatile paper trades

Called from app.py via a background thread every N hours.

Usage:
    python tools/auto_pipeline.py
    python tools/auto_pipeline.py --force-scan
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    db_path, tmp_path, save_json, load_json,
    get_int, get_float,
)


# ── State management ───────────────────────────────────────────────────────────

def _state_path() -> Path:
    from utils import _ROOT
    p = _ROOT / ".tmp" / "auto_pipeline_state.json"
    p.parent.mkdir(exist_ok=True)
    return p


def load_pipeline_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {"running": False, "last_run_at": None, "last_results": {}}
    return load_json(p)


def save_pipeline_state(state: dict) -> None:
    save_json(_state_path(), state)


def is_pipeline_due(interval_hours: int = 4) -> bool:
    """Returns True if enough time has passed since last run (or never ran)."""
    state = load_pipeline_state()
    # If marked running but last_run_at is >1h ago, assume it died — reset
    if state.get("running"):
        last = state.get("last_run_at")
        if last:
            age_h = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600
            if age_h > 1:
                state["running"] = False
                save_pipeline_state(state)
            else:
                return False  # genuinely running
        else:
            state["running"] = False
            save_pipeline_state(state)

    last_run = state.get("last_run_at")
    if not last_run:
        return True
    age_h = (datetime.now() - datetime.fromisoformat(last_run)).total_seconds() / 3600
    return age_h >= interval_hours


# ── Single-ticker full analysis (no Streamlit) ─────────────────────────────────

def run_full_analysis(ticker: str, shared_info: dict | None = None) -> dict | None:
    """
    Run the complete 7-module analysis for one ticker and return the decision dict.
    Mirrors cached_run_analysis in app.py but without @st.cache_data.
    """
    import yfinance as yf
    from fetch_company_overview import fetch_company_overview
    from fetch_fundamentals     import fetch_fundamentals
    from fetch_news             import fetch_news
    from fetch_technicals       import fetch_technicals
    from fetch_risk_factors     import fetch_risk_factors
    from fetch_opportunities    import fetch_opportunities
    from decision_engine        import make_decision

    try:
        if shared_info is None:
            shared_info = yf.Ticker(ticker).info or {}

        fetch_company_overview(ticker, shared_info)
        fetch_fundamentals(ticker, shared_info)
        fetch_news(ticker, shared_info.get("longName") or shared_info.get("shortName", ""))
        fetch_technicals(ticker)
        fetch_risk_factors(ticker, shared_info)
        fetch_opportunities(ticker, shared_info)
        decision = make_decision(ticker)
        return decision
    except Exception as e:
        print(f"[WARN] Full analysis failed for {ticker}: {e}")
        return None


def run_light_analysis(ticker: str) -> dict | None:
    """
    Lighter analysis for volatile tickers: technicals + news + decision only.
    Skips fundamentals/overview (irrelevant for 3-day volatile plays).
    """
    import yfinance as yf
    from fetch_technicals import fetch_technicals
    from fetch_news       import fetch_news
    from decision_engine  import make_decision
    from utils            import tmp_path, load_json, save_json

    try:
        t = yf.Ticker(ticker)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        # Minimal overview so decision_engine doesn't choke
        ov_path = tmp_path(ticker, "overview")
        if not ov_path.exists():
            save_json(ov_path, {
                "ticker": ticker,
                "name": info.get("longName") or info.get("shortName", ticker),
                "sector": info.get("sector", "Unknown"),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            })

        # Ensure fundamentals/risks/opportunities stubs exist so make_decision can run
        from datetime import date
        for module, stub in [
            ("fundamentals",  {"ticker": ticker, "score": 0.0, "rating": "Unknown"}),
            ("risks",         {"ticker": ticker, "score": 0.0, "risk_level": "Unknown"}),
            ("opportunities", {"ticker": ticker, "score": 0.0, "opportunity_level": "Unknown"}),
        ]:
            p = tmp_path(ticker, module)
            if not p.exists():
                save_json(p, stub)

        fetch_news(ticker, info.get("longName", ""))
        fetch_technicals(ticker)
        decision = make_decision(ticker)
        return decision
    except Exception as e:
        print(f"[WARN] Light analysis failed for {ticker}: {e}")
        return None


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_autonomous_pipeline(
    top_n_regular:  int  = 5,
    top_n_volatile: int  = 5,
    eval_days_regular:  int = 10,
    eval_days_volatile: int = 3,
    force_scan: bool = False,
) -> dict:
    """
    Full autonomous learning cycle. Thread-safe via state file locking.
    """
    start = datetime.now()
    print(f"\n{'='*55}")
    print(f"  AUTO PIPELINE — {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    state = load_pipeline_state()
    state["running"] = True
    state["last_run_at"] = start.isoformat()
    save_pipeline_state(state)

    results = {
        "started_at":        start.isoformat(),
        "regular_closed":    0,
        "volatile_closed":   0,
        "learning_ran":      False,
        "regular_analyzed":  [],
        "volatile_analyzed": [],
        "errors":            [],
    }

    # ── Phase 0: Close expired trades ─────────────────────────────────────────
    try:
        from close_paper_trades import close_paper_trades
        reg_closed = close_paper_trades(eval_days=eval_days_regular, trade_type="regular")
        vol_closed = close_paper_trades(eval_days=eval_days_volatile, trade_type="volatile")
        results["regular_closed"]  = len(reg_closed)
        results["volatile_closed"] = len(vol_closed)
        print(f"\n[Phase 0] Closed: {len(reg_closed)} regular, {len(vol_closed)} volatile")
    except Exception as e:
        results["errors"].append(f"close_trades: {e}")
        print(f"[WARN] close_paper_trades failed: {e}")

    # ── Phase 0b: Learning cycles (regular + volatile) ────────────────────────
    try:
        from learning_cycle import run_learning_cycle
        lc = run_learning_cycle(eval_days=eval_days_regular, min_new_trades=3)
        results["learning_ran"] = lc.get("status") == "ok"
        print(f"[Phase 0b] Regular learning cycle: {lc.get('status')}")
    except Exception as e:
        results["errors"].append(f"learning_cycle: {e}")
        print(f"[WARN] learning_cycle failed: {e}")

    try:
        from volatile_learning import run_volatile_learning_cycle
        vlc = run_volatile_learning_cycle(min_samples=3)
        results["volatile_learning_ran"] = vlc.get("status") == "ok"
        print(f"[Phase 0b] Volatile learning cycle: {vlc.get('status')}")
    except Exception as e:
        results["errors"].append(f"volatile_learning_cycle: {e}")
        print(f"[WARN] volatile_learning_cycle failed: {e}")

    # ── Phase 1: Regular scanner ───────────────────────────────────────────────
    regular_candidates = []
    try:
        from market_scanner import run_scanner
        scan = run_scanner(force=force_scan)
        top_buys  = scan.get("top_buys", [])[:top_n_regular]
        top_sells = scan.get("top_sells", [])[:2]  # fewer sells
        regular_candidates = [r["ticker"] for r in (top_buys + top_sells)]
        print(f"\n[Phase 1] Regular candidates: {regular_candidates}")
    except Exception as e:
        results["errors"].append(f"market_scanner: {e}")
        print(f"[WARN] market_scanner failed: {e}")

    # ── Phase 2: Volatile scanner ──────────────────────────────────────────────
    volatile_candidates = []
    volatile_meta: dict[str, dict] = {}  # ticker → scanner metadata
    try:
        from volatile_scanner import scan_volatile_market
        vscan = scan_volatile_market(force=force_scan, top_n=top_n_volatile)
        for opp in vscan.get("opportunities", []):
            tk = opp["ticker"]
            volatile_candidates.append(tk)
            volatile_meta[tk] = opp
        print(f"[Phase 2] Volatile candidates: {volatile_candidates}")
    except Exception as e:
        results["errors"].append(f"volatile_scanner: {e}")
        print(f"[WARN] volatile_scanner failed: {e}")

    # ── Phase 3: Analyze regular picks ────────────────────────────────────────
    print(f"\n[Phase 3] Analyzing {len(regular_candidates)} regular tickers...")
    from auto_paper_trade import auto_paper_trade
    for ticker in regular_candidates:
        try:
            decision = run_full_analysis(ticker)
            if decision:
                pt_id = auto_paper_trade(ticker, decision, trade_type="regular")
                results["regular_analyzed"].append({
                    "ticker": ticker,
                    "rec": decision.get("recommendation"),
                    "score": decision.get("final_score"),
                    "paper_trade_id": pt_id,
                })
                print(f"  {ticker}: {decision.get('recommendation')} "
                      f"score={decision.get('final_score', 0):.3f} "
                      f"paper_trade={'#'+str(pt_id) if pt_id else 'skipped'}")
            time.sleep(2)  # gentle rate-limit buffer between tickers
        except Exception as e:
            results["errors"].append(f"analyze_{ticker}: {e}")
            print(f"  [WARN] {ticker}: {e}")

    # ── Phase 4: Analyze volatile picks ───────────────────────────────────────
    print(f"\n[Phase 4] Analyzing {len(volatile_candidates)} volatile tickers...")
    for ticker in volatile_candidates:
        try:
            decision = run_light_analysis(ticker)
            if decision:
                # Attach catalyst metadata so volatile_learning can parse outcomes
                meta = volatile_meta.get(ticker, {})
                events_str = ",".join(meta.get("events", []))
                decision["_volatile_meta"] = (
                    f"events={events_str} "
                    f"vol_ratio={meta.get('volume_ratio', '')} "
                    f"price_chg={meta.get('change_pct', '')} "
                    f"sector={meta.get('sector', 'Unknown')}"
                )
                pt_id = auto_paper_trade(ticker, decision, trade_type="volatile")
                results["volatile_analyzed"].append({
                    "ticker": ticker,
                    "rec": decision.get("recommendation"),
                    "score": decision.get("final_score"),
                    "paper_trade_id": pt_id,
                })
                print(f"  {ticker}: {decision.get('recommendation')} "
                      f"score={decision.get('final_score', 0):.3f} "
                      f"paper_trade={'#'+str(pt_id) if pt_id else 'skipped'}")
            time.sleep(1)
        except Exception as e:
            results["errors"].append(f"volatile_{ticker}: {e}")
            print(f"  [WARN] {ticker}: {e}")

    # ── Finalize ───────────────────────────────────────────────────────────────
    results["finished_at"] = datetime.now().isoformat()
    elapsed = (datetime.now() - start).total_seconds()
    results["elapsed_sec"] = round(elapsed)

    state = load_pipeline_state()
    state["running"]      = False
    state["last_run_at"]  = start.isoformat()
    state["last_results"] = results
    save_pipeline_state(state)

    print(f"\n{'='*55}")
    print(f"  Pipeline done in {elapsed:.0f}s  "
          f"| {len(results['regular_analyzed'])} regular "
          f"| {len(results['volatile_analyzed'])} volatile analyzed")
    print(f"{'='*55}\n")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the autonomous learning pipeline")
    parser.add_argument("--force-scan",     action="store_true")
    parser.add_argument("--regular-n",      type=int, default=5)
    parser.add_argument("--volatile-n",     type=int, default=5)
    parser.add_argument("--eval-days",      type=int, default=10)
    parser.add_argument("--eval-days-vol",  type=int, default=3)
    args = parser.parse_args()
    run_autonomous_pipeline(
        top_n_regular=args.regular_n,
        top_n_volatile=args.volatile_n,
        eval_days_regular=args.eval_days,
        eval_days_volatile=args.eval_days_vol,
        force_scan=args.force_scan,
    )
