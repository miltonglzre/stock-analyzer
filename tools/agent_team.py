"""
agent_team.py — Multi-agent orchestration for comprehensive stock analysis.

Team structure:
  TechnicalAgent     — Chart patterns, momentum, support/resistance
  FundamentalAgent   — Financials, valuation, earnings quality
  SentimentAgent     — News NLP, market mood, analyst sentiment
  RiskAgent          — Volatility, drawdown risk, position sizing
  OpportunityAgent   — Catalysts, sector tailwinds, momentum
  MacroContextAgent  — Historical parallels, macro regime, geopolitical

The Orchestrator runs all agents and applies cross-agent logic:
  - Macro regime dampens/amplifies individual agent scores
  - High VIX overrides bullish signals with a risk penalty
  - Historical parallels adjust sector-specific confidence

Usage:
    from agent_team import run_team_analysis
    result = run_team_analysis("AAPL")
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, load_json, save_json


# ── Agent base class ──────────────────────────────────────────────────────────

class BaseAgent:
    name: str = "Base"
    weight: float = 0.0

    def run(self, ticker: str) -> dict:
        raise NotImplementedError

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)


# ── Individual agents ─────────────────────────────────────────────────────────

class TechnicalAgent(BaseAgent):
    name = "Technical"
    weight = 0.30

    def run(self, ticker: str) -> dict:
        from fetch_technicals import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)


class FundamentalAgent(BaseAgent):
    name = "Fundamental"
    weight = 0.25

    def run(self, ticker: str) -> dict:
        from fetch_fundamentals import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)


class SentimentAgent(BaseAgent):
    name = "Sentiment"
    weight = 0.20

    def run(self, ticker: str) -> dict:
        from fetch_news import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)


class RiskAgent(BaseAgent):
    name = "Risk"
    weight = 0.15

    def run(self, ticker: str) -> dict:
        from fetch_risk_factors import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)


class OpportunityAgent(BaseAgent):
    name = "Opportunity"
    weight = 0.10

    def run(self, ticker: str) -> dict:
        from fetch_opportunities import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)


class MacroContextAgent(BaseAgent):
    name = "MacroContext"
    weight = 0.0  # Modifier, not direct scorer

    def run(self, ticker: str) -> dict:
        from fetch_macro_context import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("macro_score", 0.0)


# ── Cross-agent signal propagation ────────────────────────────────────────────

def _apply_cross_agent_logic(scores: dict, macro_result: dict) -> dict:
    """
    Apply inter-agent adjustments based on macro context.
    Macro regime modifies how other agents' signals are weighted.
    """
    adjusted = dict(scores)
    regime = macro_result.get("regime", "normal")
    risk_flags = macro_result.get("risk_flags", [])
    macro_score = macro_result.get("macro_score", 0)

    # Bear market / recession risk: dampen bullish signals
    if regime in ("recession_risk", "bear_market"):
        for key in ["Technical", "Fundamental", "Sentiment"]:
            if adjusted.get(key, 0) > 0:
                adjusted[key] *= 0.7  # 30% penalty on positive signals

    # High volatility: reduce confidence in all signals
    elif regime == "high_volatility":
        for key in adjusted:
            adjusted[key] *= 0.85

    # Rate tightening: penalize growth-sensitive signals
    elif regime == "rate_tightening":
        if adjusted.get("Fundamental", 0) > 0.3:
            adjusted["Fundamental"] *= 0.8
        if adjusted.get("Technical", 0) > 0.3:
            adjusted["Technical"] *= 0.9

    # Inverted yield curve: additional caution
    if "inverted_yield_curve" in risk_flags:
        for key in ["Technical", "Sentiment"]:
            adjusted[key] = adjusted.get(key, 0) - 0.05

    # Add macro contribution
    adjusted["MacroContext"] = macro_score

    return adjusted


def _compute_team_consensus(adjusted_scores: dict) -> dict:
    """Compute team consensus score and recommendation."""
    agent_weights = {
        "Technical":    0.28,
        "Fundamental":  0.23,
        "Sentiment":    0.18,
        "Risk":         0.14,
        "Opportunity":  0.09,
        "MacroContext": 0.08,
    }

    total_weight = 0.0
    weighted_sum = 0.0
    for agent_name, weight in agent_weights.items():
        score = adjusted_scores.get(agent_name, 0)
        weighted_sum += score * weight
        total_weight += weight

    consensus = weighted_sum / total_weight if total_weight > 0 else 0

    # Agreement: how many agents agree on direction
    scores = [v for k, v in adjusted_scores.items() if k != "MacroContext"]
    bullish_count = sum(1 for s in scores if s > 0.1)
    bearish_count = sum(1 for s in scores if s < -0.1)
    n = len(scores)
    agreement = max(bullish_count, bearish_count) / n if n > 0 else 0

    # Team recommendation
    if consensus > 0.25:
        team_rec = "Buy"
    elif consensus > 0.05:
        team_rec = "Watch"
    elif consensus < -0.25:
        team_rec = "Sell"
    elif consensus < -0.05:
        team_rec = "Caution"
    else:
        team_rec = "Neutral"

    return {
        "consensus_score": round(consensus, 3),
        "team_recommendation": team_rec,
        "agent_agreement": round(agreement, 2),
        "bullish_agents": bullish_count,
        "bearish_agents": bearish_count,
        "adjusted_scores": {k: round(v, 3) for k, v in adjusted_scores.items()},
    }


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run_team_analysis(ticker: str) -> dict:
    """
    Run the full agent team analysis for a ticker.

    Returns dict with:
      - agent_results: raw output from each agent
      - raw_scores: score extracted from each agent
      - adjusted_scores: scores after cross-agent logic
      - team_consensus: final team verdict
      - macro_context: macro environment assessment
    """
    agents = [
        TechnicalAgent(),
        FundamentalAgent(),
        SentimentAgent(),
        RiskAgent(),
        OpportunityAgent(),
    ]
    macro_agent = MacroContextAgent()

    agent_results = {}
    raw_scores = {}

    # Run standard agents
    for agent in agents:
        try:
            result = agent.run(ticker)
            agent_results[agent.name] = result
            raw_scores[agent.name] = agent.extract_score(result)
        except Exception as e:
            agent_results[agent.name] = {"error": str(e)}
            raw_scores[agent.name] = 0.0

    # Run macro context agent (shared across all tickers)
    try:
        macro_result = macro_agent.run(ticker)
        agent_results["MacroContext"] = macro_result
    except Exception as e:
        macro_result = {"regime": "normal", "macro_score": 0, "risk_flags": [], "error": str(e)}
        agent_results["MacroContext"] = macro_result

    # Apply cross-agent logic
    adjusted_scores = _apply_cross_agent_logic(raw_scores, macro_result)

    # Compute team consensus
    consensus = _compute_team_consensus(adjusted_scores)

    final = {
        "ticker": ticker,
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "agent_results": agent_results,
        "raw_scores": {k: round(v, 3) for k, v in raw_scores.items()},
        "adjusted_scores": consensus["adjusted_scores"],
        "team_consensus": consensus,
        "macro_context": macro_result,
    }

    save_json(tmp_path(f"{ticker}_team_analysis.json"), final)
    return final


if __name__ == "__main__":
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    result = run_team_analysis(ticker)
    # Print summary
    print(f"\n{'='*60}")
    print(f"TEAM ANALYSIS: {ticker}")
    print(f"{'='*60}")
    tc = result["team_consensus"]
    print(f"Consensus Score: {tc['consensus_score']:+.3f}")
    print(f"Team Recommendation: {tc['team_recommendation']}")
    print(f"Agent Agreement: {tc['agent_agreement']:.0%}")
    print(f"\nAgent Scores (adjusted):")
    for agent, score in tc["adjusted_scores"].items():
        bar = "█" * int(abs(score) * 20)
        direction = "+" if score >= 0 else ""
        print(f"  {agent:<15} {direction}{score:.3f}  {bar}")
    mc = result.get("macro_context", {})
    print(f"\nMacro Regime: {mc.get('regime_label', 'N/A')}")
    if mc.get("historical_parallels"):
        print(f"Historical Parallel: {mc['historical_parallels'][0]['event']}")
    print(f"{'='*60}\n")
