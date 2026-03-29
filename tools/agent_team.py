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
    # Skills: list of capability strings this agent has
    skills: list = []
    description: str = ""

    def run(self, ticker: str) -> dict:
        raise NotImplementedError

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)

    def skill_filter(self, result: dict, macro_result: dict) -> dict:
        """
        Post-process result using agent-specific skills.
        Each agent may apply additional logic based on its skill set.
        """
        return result


# ── Individual agents ─────────────────────────────────────────────────────────

class TechnicalAgent(BaseAgent):
    name = "Technical"
    weight = 0.30
    description = "Analiza indicadores técnicos, patrones de precio y momentum"
    skills = [
        "rsi_divergence",        # Detecta divergencias RSI precio
        "volume_confirmation",   # Confirma señales con volumen inusual
        "trend_strength",        # Mide fuerza de tendencia (ADX-like via SMAs)
        "support_resistance",    # Niveles clave de soporte/resistencia
        "ma_cross_filter",       # Filtra señales por cruce de medias
        "bb_squeeze",            # Detecta compresión Bollinger (volatility contraction)
        "momentum_decay",        # Penaliza señales alcistas cuando RSI > 75 (sobrecompra extrema)
    ]

    def run(self, ticker: str) -> dict:
        from fetch_technicals import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)

    def skill_filter(self, result: dict, macro_result: dict) -> dict:
        """Apply RSI momentum decay and volume confirmation skills."""
        score = result.get("score", 0.0)
        rsi = result.get("rsi")
        volume_ratio = result.get("volume_ratio", 1.0) or 1.0

        # skill: momentum_decay — penalizar señal alcista con RSI extremo
        if rsi and rsi > 75 and score > 0:
            score *= 0.75
            result.setdefault("skill_notes", []).append(
                f"momentum_decay: RSI={rsi:.0f} sobrecomprado, señal alcista reducida 25%"
            )
        # skill: rsi_divergence — reforzar señal bajista con RSI muy bajo
        elif rsi and rsi < 25 and score < 0:
            score *= 0.75
            result.setdefault("skill_notes", []).append(
                f"rsi_divergence: RSI={rsi:.0f} sobrevendido, posible rebote, señal bajista reducida"
            )

        # skill: volume_confirmation — ampliar señales con volumen alto
        if volume_ratio > 2.0 and abs(score) > 0.1:
            score *= 1.15
            result.setdefault("skill_notes", []).append(
                f"volume_confirmation: volumen {volume_ratio:.1f}x — señal reforzada"
            )

        result["score"] = round(score, 4)
        return result


class FundamentalAgent(BaseAgent):
    name = "Fundamental"
    weight = 0.25
    description = "Evalúa fundamentos financieros, valuación y calidad de ganancias"
    skills = [
        "pe_context",            # Contextualiza P/E vs sector y mercado
        "earnings_quality",      # Detecta ganancias reales vs ajustadas
        "debt_stress_test",      # Penaliza deuda alta en entornos de tasas altas
        "revenue_acceleration",  # Premia aceleración de crecimiento de ingresos
        "margin_trend",          # Analiza tendencia de márgenes (expansión/contracción)
        "insider_alignment",     # Bonus si buybacks activos (señal de confianza mgmt)
    ]

    def run(self, ticker: str) -> dict:
        from fetch_fundamentals import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)

    def skill_filter(self, result: dict, macro_result: dict) -> dict:
        """Apply debt stress test when rates are high."""
        score = result.get("score", 0.0)
        metrics = result.get("metrics", {})
        risk_flags = macro_result.get("risk_flags", [])

        # skill: debt_stress_test — deuda alta + tasas altas = penalización extra
        if "high_rates" in risk_flags:
            de_ratio = metrics.get("debt_to_equity")
            if de_ratio and de_ratio > 2.0 and score > 0:
                score *= 0.80
                result.setdefault("skill_notes", []).append(
                    f"debt_stress_test: D/E={de_ratio:.1f} + tasas altas, score reducido 20%"
                )

        result["score"] = round(score, 4)
        return result


class SentimentAgent(BaseAgent):
    name = "Sentiment"
    weight = 0.20
    description = "Procesa noticias, sentimiento de mercado y narrativa mediática"
    skills = [
        "vader_nlp",             # Análisis NLP de texto de noticias con VADER
        "event_detection",       # Detecta earnings beats/misses, FDA, M&A
        "recency_weighting",     # Noticias recientes pesan más que antiguas
        "source_credibility",    # Reuters/Bloomberg vs blogs sin credibilidad
        "fear_greed_overlay",    # Ajusta sentimiento con índice Fear & Greed global
        "headline_anomaly",      # Alerta si hay spike inusual de cobertura mediática
        "noise_filter",          # Descarta noticias repetidas o sin contenido real
    ]

    def run(self, ticker: str) -> dict:
        from fetch_news import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)

    def skill_filter(self, result: dict, macro_result: dict) -> dict:
        """Apply fear_greed_overlay — dampen bullish sentiment in fearful markets."""
        score = result.get("score", 0.0)
        macro_indicators = macro_result.get("indicators", {})
        vix = macro_indicators.get("vix", 20)

        # skill: fear_greed_overlay — mercado con miedo extremo reduce sentimiento alcista
        if vix > 30 and score > 0.1:
            penalty = min(0.3, (vix - 30) / 100)
            score -= penalty
            result.setdefault("skill_notes", []).append(
                f"fear_greed_overlay: VIX={vix:.0f} (miedo), sentimiento alcista reducido en {penalty:.2f}"
            )

        result["score"] = round(score, 4)
        return result


class RiskAgent(BaseAgent):
    name = "Risk"
    weight = 0.15
    description = "Cuantifica volatilidad, riesgo de pérdida y tamaño de posición"
    skills = [
        "volatility_regime",     # Clasifica régimen de volatilidad: baja/media/alta
        "beta_adjustment",       # Ajusta riesgo por beta vs SPY
        "drawdown_history",      # Considera historial de drawdowns del ticker
        "liquidity_check",       # Penaliza acciones con volumen promedio bajo
        "earnings_binary_risk",  # Alerta de riesgo binario pre-earnings
        "sector_correlation",    # Detecta correlación alta con sector en estrés
        "position_sizing_hint",  # Sugiere % de portfolio basado en volatilidad
    ]

    def run(self, ticker: str) -> dict:
        from fetch_risk_factors import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)

    def skill_filter(self, result: dict, macro_result: dict) -> dict:
        """Apply volatility_regime — amplify risk penalty in high-volatility macro."""
        score = result.get("score", 0.0)
        regime = macro_result.get("regime", "normal")

        # skill: volatility_regime — en mercados con alta volatilidad, el riesgo pesa más
        if regime in ("high_volatility", "recession_risk", "bear_market") and score < 0:
            score *= 1.25
            result.setdefault("skill_notes", []).append(
                f"volatility_regime: régimen '{regime}', penalización de riesgo amplificada 25%"
            )

        result["score"] = round(score, 4)
        return result


class OpportunityAgent(BaseAgent):
    name = "Opportunity"
    weight = 0.10
    description = "Identifica catalizadores, momentum de sector y señales de impulso"
    skills = [
        "catalyst_detection",    # Earnings próximos, lanzamientos de producto, FDA
        "sector_rotation",       # Detecta rotación de capital hacia el sector
        "analyst_upgrade_bonus", # Premio por upgrades recientes de analistas
        "buyback_signal",        # Buybacks activos como señal de confianza
        "relative_strength",     # Compara performance vs SPY y sector
        "52w_breakout",          # Detecta aproximación a máximos de 52 semanas
        "macro_tailwind",        # Verifica si el sector se beneficia del régimen macro actual
    ]

    def run(self, ticker: str) -> dict:
        from fetch_opportunities import run as _run
        return _run(ticker)

    def extract_score(self, result: dict) -> float:
        return result.get("score", 0.0)

    def skill_filter(self, result: dict, macro_result: dict) -> dict:
        """Apply macro_tailwind — amplify opportunity in favorable macro regimes."""
        score = result.get("score", 0.0)
        regime = macro_result.get("regime", "normal")

        # skill: macro_tailwind — régimen normal/alcista amplifica oportunidades
        if regime == "normal" and score > 0.1:
            score *= 1.10
            result.setdefault("skill_notes", []).append(
                "macro_tailwind: régimen de mercado favorable, oportunidad amplificada 10%"
            )
        # skill: macro_tailwind inverso — en bear market, oportunidades se reducen
        elif regime in ("bear_market", "recession_risk") and score > 0:
            score *= 0.60
            result.setdefault("skill_notes", []).append(
                f"macro_tailwind: régimen '{regime}', oportunidades alcistas reducidas 40%"
            )

        result["score"] = round(score, 4)
        return result


class MacroContextAgent(BaseAgent):
    name = "MacroContext"
    weight = 0.0  # Modifier, not direct scorer
    description = "Analiza régimen macro, paralelos históricos y contexto geopolítico"
    skills = [
        "regime_classification",   # Clasifica régimen: normal/recesión/bear/restrictivo
        "yield_curve_analysis",    # Inversión de curva como predictor de recesión
        "historical_pattern_match",# Busca eventos históricos similares (1929-2026)
        "vix_regime",              # Clasifica mercado por nivel de VIX
        "geopolitical_overlay",    # Identifica riesgos geopolíticos activos
        "commodity_pressure",      # Impacto de petróleo/oro en sectores
        "fed_policy_context",      # Contexto de política monetaria Fed
        "cross_agent_modifier",    # Modifica scores de todos los demás agentes
    ]

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
    skill_notes = {}

    # Run macro context agent FIRST — other agents need it for skill_filter
    try:
        macro_result = macro_agent.run(ticker)
        agent_results["MacroContext"] = macro_result
    except Exception as e:
        macro_result = {"regime": "normal", "macro_score": 0, "risk_flags": [], "indicators": {}, "error": str(e)}
        agent_results["MacroContext"] = macro_result

    # Run standard agents and apply their skill filters
    for agent in agents:
        try:
            result = agent.run(ticker)
            # Apply agent-specific skills using macro context
            result = agent.skill_filter(result, macro_result)
            agent_results[agent.name] = result
            raw_scores[agent.name] = agent.extract_score(result)
            skill_notes[agent.name] = result.get("skill_notes", [])
        except Exception as e:
            agent_results[agent.name] = {"error": str(e)}
            raw_scores[agent.name] = 0.0
            skill_notes[agent.name] = []

    # Apply cross-agent logic
    adjusted_scores = _apply_cross_agent_logic(raw_scores, macro_result)

    # Compute team consensus
    consensus = _compute_team_consensus(adjusted_scores)

    # Build agent profile map for transparency
    agent_profiles = {
        a.name: {"description": a.description, "skills": a.skills, "weight": a.weight}
        for a in agents + [macro_agent]
    }

    final = {
        "ticker": ticker,
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "agent_results": agent_results,
        "agent_profiles": agent_profiles,
        "skill_notes": skill_notes,
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
