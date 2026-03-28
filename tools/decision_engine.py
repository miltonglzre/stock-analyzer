"""
decision_engine.py — Combine all module scores into a final verdict.

Scoring formula:
  final_score = Σ(module_score × module_weight × signal_weights) / Σ(weights)

Modules and their base weights:
  fundamentals  → 0.25
  news          → 0.20
  technicals    → 0.30
  risk          → 0.15  (penalty only)
  opportunities → 0.10  (bonus only)

Signal-level weights from the learning system are applied on top.

Output: .tmp/{TICKER}_decision.json

Usage:
    python tools/decision_engine.py AAPL
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, load_json, save_json, load_weights, db_path


# ── Module weights (base) ──────────────────────────────────────────────────────
BASE_MODULE_WEIGHTS = {
    "fundamentals": 0.25,
    "news":         0.20,
    "technicals":   0.30,
    "risk":         0.15,
    "opportunities":0.10,
}


def _apply_signal_weights(tech_score: float, tech_signals: dict, weights: dict) -> float:
    """
    Adjust the technical score based on per-signal learned weights.
    Signals that historically perform well get amplified; poor ones get dampened.
    """
    active_signals = {k: v for k, v in tech_signals.items() if v}
    if not active_signals:
        return tech_score

    # Compute weighted multiplier from active signals
    multiplier_sum = 0.0
    count = 0
    for sig_name in active_signals:
        w = weights.get(sig_name, 1.0)
        multiplier_sum += w
        count += 1

    avg_multiplier = multiplier_sum / count if count > 0 else 1.0
    # Normalize: multiplier of 1.0 = no change, >1.0 = amplify, <1.0 = dampen
    # Scale so that avg_multiplier=1.0 means × 1.0
    adjusted = tech_score * min(avg_multiplier, 1.5)  # cap amplification at 1.5×
    return round(max(-1.0, min(1.0, adjusted)), 4)


def _map_news_score(news_sentiment: str, news_score: float, weights: dict) -> float:
    """Apply learned news signal weights to the raw VADER score."""
    if news_score > 0.05:
        w = weights.get("news_bullish", 1.0)
    elif news_score < -0.05:
        w = weights.get("news_bearish", 1.0)
    else:
        w = 1.0
    return round(max(-1.0, min(1.0, news_score * w)), 4)


def _map_fundamentals_score(fundamentals_score: float, rating: str, weights: dict) -> float:
    """Apply learned fundamentals signal weights."""
    if rating == "Strong":
        w = weights.get("fundamentals_strong", 1.0)
    elif rating == "Weak":
        w = weights.get("fundamentals_weak", 1.0)
    else:
        w = 1.0
    return round(max(-1.0, min(1.0, fundamentals_score * w)), 4)


def make_decision(ticker: str) -> dict:
    ticker = ticker.upper()
    weights = load_weights()

    # ── Load module outputs ────────────────────────────────────────────────────
    fundamentals = load_json(tmp_path(ticker, "fundamentals"))
    news = load_json(tmp_path(ticker, "news"))
    technicals = load_json(tmp_path(ticker, "technicals"))
    risks = load_json(tmp_path(ticker, "risks"))
    opportunities = load_json(tmp_path(ticker, "opportunities"))
    overview = load_json(tmp_path(ticker, "overview"))

    missing = []
    for name, d in [("fundamentals", fundamentals), ("news", news),
                    ("technicals", technicals), ("risks", risks), ("opportunities", opportunities)]:
        if not d:
            missing.append(name)

    if "technicals" in missing:
        print(f"[ERROR] Missing critical data: technicals. Run fetch_technicals.py first.")
        sys.exit(1)

    # ── Extract scores ─────────────────────────────────────────────────────────
    fund_score = fundamentals.get("score", 0.0)
    fund_rating = fundamentals.get("rating", "Neutral")
    news_score = news.get("sentiment_score", 0.0)
    news_label = news.get("sentiment", "Neutral")
    tech_score = technicals.get("score", 0.0)
    tech_signals = technicals.get("signals", {})
    risk_penalty = risks.get("score", 0.0)  # already negative
    opp_bonus = opportunities.get("score", 0.0)  # already positive

    # ── Apply learned signal weights ───────────────────────────────────────────
    fund_score_adj = _map_fundamentals_score(fund_score, fund_rating, weights)
    news_score_adj = _map_news_score(news_label, news_score, weights)
    tech_score_adj = _apply_signal_weights(tech_score, tech_signals, weights)

    # Risk and opportunity scores are penalites/bonuses, scale to -1..+1 range
    risk_score_adj = max(-1.0, risk_penalty)  # already in [-1, 0]
    opp_score_adj = min(1.0, opp_bonus)       # already in [0, 1]

    # ── Weighted combination ───────────────────────────────────────────────────
    mw = BASE_MODULE_WEIGHTS
    numerator = (
        fund_score_adj  * mw["fundamentals"] +
        news_score_adj  * mw["news"] +
        tech_score_adj  * mw["technicals"] +
        risk_score_adj  * mw["risk"] +
        opp_score_adj   * mw["opportunities"]
    )
    denominator = sum(mw.values())
    final_score = round(numerator / denominator, 4)
    final_score = max(-1.0, min(1.0, final_score))

    # ── Verdict ────────────────────────────────────────────────────────────────
    if final_score >= 0.15:
        verdict = "Bullish"
        recommendation = "Buy"
    elif final_score <= -0.15:
        verdict = "Bearish"
        recommendation = "Sell"
    else:
        verdict = "Neutral"
        recommendation = "Wait"

    confidence_pct = min(100, int(abs(final_score) * 100 + 20))  # floor at 20%
    if final_score == 0.0:
        confidence_pct = 20

    # ── Timing zones ──────────────────────────────────────────────────────────
    entry_zone_low = technicals.get("entry_zone_low")
    entry_zone_high = technicals.get("entry_zone_high")
    stop_loss = technicals.get("stop_loss")
    target_price = technicals.get("target_price")
    current_price = technicals.get("current_price")
    nearest_support = technicals.get("nearest_support")
    nearest_resistance = technicals.get("nearest_resistance")

    # Timing advice
    if recommendation == "Buy":
        if current_price and entry_zone_low and current_price <= entry_zone_high:
            timing = f"ENTER NOW — price ${current_price:.2f} is within entry zone (${entry_zone_low:.2f}–${entry_zone_high:.2f})"
        elif current_price and entry_zone_low and current_price > entry_zone_high:
            timing = f"WAIT FOR PULLBACK — entry zone ${entry_zone_low:.2f}–${entry_zone_high:.2f}, current ${current_price:.2f}"
        else:
            timing = "Entry zone unavailable — check technicals manually"
    elif recommendation == "Sell":
        timing = f"EXIT POSITION — bearish signals active. Stop at ${stop_loss:.2f}" if stop_loss else "Exit at current levels"
    else:
        timing = "Stay on sidelines — wait for clearer signal"

    # ── Build score breakdown ─────────────────────────────────────────────────
    score_breakdown = {
        "fundamentals":  {"raw": fundamentals.get("score", 0), "adjusted": fund_score_adj, "weight": mw["fundamentals"]},
        "news":          {"raw": news.get("sentiment_score", 0), "adjusted": news_score_adj, "weight": mw["news"]},
        "technicals":    {"raw": technicals.get("score", 0), "adjusted": tech_score_adj, "weight": mw["technicals"]},
        "risk":          {"raw": risks.get("score", 0), "adjusted": risk_score_adj, "weight": mw["risk"]},
        "opportunities": {"raw": opportunities.get("score", 0), "adjusted": opp_score_adj, "weight": mw["opportunities"]},
    }

    # ── Key reasons (top signals) ──────────────────────────────────────────────
    all_reasons = []
    all_reasons += (fundamentals.get("reasoning") or [])[:2]
    all_reasons += (news.get("top_positive_headlines") or [])[:1]
    all_reasons += (news.get("top_negative_headlines") or [])[:1]
    all_reasons += (technicals.get("reasoning") or [])[:2]
    all_reasons += (risks.get("reasoning") or [])[:2]
    all_reasons += (opportunities.get("reasoning") or [])[:2]

    data = {
        "ticker":            ticker,
        "run_date":          datetime.now().strftime("%Y-%m-%d %H:%M"),
        "verdict":           verdict,
        "recommendation":    recommendation,
        "confidence_pct":    confidence_pct,
        "final_score":       final_score,
        "timing":            timing,
        "entry_zone_low":    entry_zone_low,
        "entry_zone_high":   entry_zone_high,
        "stop_loss":         stop_loss,
        "target_price":      target_price,
        "current_price":     current_price,
        "nearest_support":   nearest_support,
        "nearest_resistance":nearest_resistance,
        "fundamentals_rating": fund_rating,
        "news_sentiment":    news_label,
        "risk_level":        risks.get("risk_level", "Unknown"),
        "opportunity_level": opportunities.get("opportunity_level", "Unknown"),
        "score_breakdown":   score_breakdown,
        "key_events":        news.get("key_events", []),
        "key_reasons":       all_reasons,
        "signals_active":    {k: v for k, v in tech_signals.items() if v},
        "weights_used":      weights,
        "missing_modules":   missing,
    }

    path = tmp_path(ticker, "decision")
    save_json(path, data)

    # ── Persist to analysis_reports ────────────────────────────────────────────
    _save_to_db(data)

    return data


def _save_to_db(data: dict):
    try:
        import sqlite3
        conn = sqlite3.connect(db_path())
        conn.execute("""
            INSERT INTO analysis_reports
              (ticker, run_date, fundamentals_rating, news_sentiment, verdict,
               confidence_pct, recommendation, entry_zone_low, entry_zone_high,
               stop_loss, target_price, full_report_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["ticker"], data["run_date"],
            data.get("fundamentals_rating"), data.get("news_sentiment"),
            data["verdict"], data["confidence_pct"], data["recommendation"],
            data.get("entry_zone_low"), data.get("entry_zone_high"),
            data.get("stop_loss"), data.get("target_price"),
            json.dumps(data),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WARN] Could not save report to DB: {e} (run db_init.py first)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/decision_engine.py <TICKER>")
        sys.exit(1)
    result = make_decision(sys.argv[1])
    print(json.dumps(result, indent=2))
