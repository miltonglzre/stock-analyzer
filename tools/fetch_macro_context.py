"""
fetch_macro_context.py — Macro environment & historical context agent.

Analyzes current macro conditions (VIX, yields, oil, gold, market trend)
and matches them to historical market events for contextual insights.

Output: .tmp/{TICKER}_macro_context.json

Usage:
    python tools/fetch_macro_context.py AAPL
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json

import yfinance as yf

# ── Historical market events database ─────────────────────────────────────────

HISTORICAL_EVENTS = [
    {
        "id": "great_depression",
        "name": "Gran Depresión",
        "period": "1929-1932",
        "category": "crash",
        "sp500_drawdown": -86,
        "recovery_years": 25,
        "triggers": ["colapso bancario", "deflación", "errores de política monetaria"],
        "sectors_hurt": ["Financials", "Industrials", "Consumer Discretionary"],
        "sectors_safe": ["Utilities", "Consumer Staples"],
        "macro_signals": {"high_debt": True, "deflation_risk": True, "bank_stress": True},
        "lesson": "El colapso del crédito y los errores de política prolongan las crisis. Efectivo y bonos superan acciones."
    },
    {
        "id": "oil_shock_1973",
        "name": "Crisis del Petróleo / Stagflación",
        "period": "1973-1974",
        "category": "recession",
        "sp500_drawdown": -48,
        "recovery_years": 7,
        "triggers": ["embargo petrolero OPEC", "inflación elevada", "subidas de tasas Fed"],
        "sectors_hurt": ["Consumer Discretionary", "Airlines", "Automotive"],
        "sectors_safe": ["Energy", "Commodities", "Gold"],
        "macro_signals": {"high_inflation": True, "high_oil": True, "high_rates": True},
        "lesson": "Stagflación: inflación + recesión simultáneas. Energía y materias primas protegen el portfolio."
    },
    {
        "id": "black_monday_1987",
        "name": "Lunes Negro",
        "period": "1987-10",
        "category": "crash",
        "sp500_drawdown": -34,
        "recovery_years": 2,
        "triggers": ["sobrevaloración", "program trading", "déficit comercial EEUU"],
        "sectors_hurt": ["All sectors"],
        "sectors_safe": ["Gold", "Bonds"],
        "macro_signals": {"high_pe_ratios": True, "algorithmic_selling": True},
        "lesson": "Crashes de un día son comprables si los fundamentos macro son sólidos. Recuperación rápida en 2 años."
    },
    {
        "id": "gulf_war_1990",
        "name": "Guerra del Golfo / Recesión 1990",
        "period": "1990-1991",
        "category": "geopolitical",
        "sp500_drawdown": -20,
        "recovery_years": 1,
        "triggers": ["invasión Kuwait", "shock de petróleo", "recesión EEUU"],
        "sectors_hurt": ["Airlines", "Consumer Discretionary", "Tourism"],
        "sectors_safe": ["Defense", "Energy", "Gold"],
        "macro_signals": {"geopolitical_risk": True, "oil_spike": True},
        "lesson": "Conflictos geopolíticos causan correcciones temporales. Defense y Energy se benefician."
    },
    {
        "id": "asian_crisis_1997",
        "name": "Crisis Financiera Asiática",
        "period": "1997-1998",
        "category": "financial",
        "sp500_drawdown": -19,
        "recovery_years": 1,
        "triggers": ["devaluación baht tailandés", "crisis de divisas", "contagio global"],
        "sectors_hurt": ["Emerging Markets", "Financials", "Technology"],
        "sectors_safe": ["US Domestic", "Consumer Staples"],
        "macro_signals": {"em_stress": True, "currency_crisis": True},
        "lesson": "Crisis de mercados emergentes impactan brevemente a EEUU. Empresas domésticas resisten mejor."
    },
    {
        "id": "dotcom_crash",
        "name": "Burbuja Punto-com",
        "period": "2000-2002",
        "category": "bubble",
        "sp500_drawdown": -49,
        "recovery_years": 7,
        "triggers": ["valoraciones extremas tecnología", "subidas de tasas Fed", "colapso capital riesgo"],
        "sectors_hurt": ["Technology", "Telecommunications", "Media"],
        "sectors_safe": ["Energy", "Healthcare", "Consumer Staples", "Financials"],
        "macro_signals": {"high_pe_ratios": True, "high_rates": True, "speculation": True},
        "lesson": "P/E > 100 en tech es insostenible. Diversificar fuera del sector dominante del ciclo anterior."
    },
    {
        "id": "sept_11_2001",
        "name": "Ataques del 11 de Septiembre",
        "period": "2001-09",
        "category": "geopolitical",
        "sp500_drawdown": -12,
        "recovery_years": 0.5,
        "triggers": ["ataques terroristas", "cierre mercados 4 días", "shock de confianza"],
        "sectors_hurt": ["Airlines", "Tourism", "Insurance"],
        "sectors_safe": ["Defense", "Homeland Security", "Gold"],
        "macro_signals": {"geopolitical_shock": True, "vix_spike": True},
        "lesson": "Shocks externos extremos = oportunidades de compra. Mercado recuperó en meses."
    },
    {
        "id": "financial_crisis_2008",
        "name": "Crisis Financiera Global",
        "period": "2007-2009",
        "category": "crash",
        "sp500_drawdown": -57,
        "recovery_years": 5,
        "triggers": ["burbuja inmobiliaria", "hipotecas subprime", "apalancamiento bancario excesivo", "colapso Lehman"],
        "sectors_hurt": ["Financials", "Real Estate", "Consumer Discretionary"],
        "sectors_safe": ["Gold", "Treasuries", "Consumer Staples"],
        "macro_signals": {"credit_risk": True, "housing_bubble": True, "bank_stress": True, "high_leverage": True},
        "lesson": "El exceso de crédito crea crisis sistémicas. La diversificación real requiere activos no correlacionados."
    },
    {
        "id": "flash_crash_2010",
        "name": "Flash Crash",
        "period": "2010-05",
        "category": "technical",
        "sp500_drawdown": -9,
        "recovery_years": 0.1,
        "triggers": ["órdenes de venta algorítmicas", "falta de liquidez", "efecto cascada"],
        "sectors_hurt": ["All sectors temporarily"],
        "sectors_safe": [],
        "macro_signals": {"algorithmic_risk": True},
        "lesson": "Crashes algorítmicos son ruido. Mantener posiciones sólidas durante volatilidad extrema de corto plazo."
    },
    {
        "id": "european_debt_2011",
        "name": "Crisis Deuda Europea",
        "period": "2011-2012",
        "category": "financial",
        "sp500_drawdown": -21,
        "recovery_years": 1,
        "triggers": ["crisis deuda Grecia", "contagio España/Italia", "riesgo ruptura eurozona"],
        "sectors_hurt": ["Financials", "European Exporters"],
        "sectors_safe": ["US Domestic", "Dollar Assets", "Gold"],
        "macro_signals": {"sovereign_debt_risk": True, "em_stress": True},
        "lesson": "Crisis soberanas europeas con recuperación rápida en EEUU. Buscar refugio en activos domésticos."
    },
    {
        "id": "oil_collapse_2015",
        "name": "Colapso del Petróleo / China",
        "period": "2015-2016",
        "category": "commodity",
        "sp500_drawdown": -15,
        "recovery_years": 1,
        "triggers": ["exceso oferta petróleo OPEC", "desaceleración China", "fortaleza dólar"],
        "sectors_hurt": ["Energy", "Materials", "Emerging Markets"],
        "sectors_safe": ["Technology", "Consumer Discretionary", "Healthcare"],
        "macro_signals": {"low_oil": True, "china_slowdown": True, "strong_dollar": True},
        "lesson": "Caída del petróleo es positiva para consumidores y tech. Negativa para energía y commodities."
    },
    {
        "id": "covid_crash_2020",
        "name": "Crash COVID-19",
        "period": "2020-02/03",
        "category": "pandemic",
        "sp500_drawdown": -34,
        "recovery_years": 0.5,
        "triggers": ["pandemia global", "cierre economías", "shock demanda/oferta simultáneo"],
        "sectors_hurt": ["Airlines", "Hospitality", "Retail", "Oil"],
        "sectors_safe": ["Technology", "Healthcare", "E-commerce", "Streaming"],
        "macro_signals": {"pandemic": True, "vix_spike": True, "oil_collapse": True},
        "lesson": "Pandemias crean ganadores (tech, healthcare) y perdedores (travel, retail). Recuperación en V posible con estímulo masivo."
    },
    {
        "id": "fed_hike_2022",
        "name": "Ciclo Agresivo de Alzas Fed / Guerra Ucrania",
        "period": "2022",
        "category": "rates",
        "sp500_drawdown": -27,
        "recovery_years": 2,
        "triggers": ["inflación 9%+", "alzas Fed 425bps en 12 meses", "invasión Ucrania", "crisis energética Europa"],
        "sectors_hurt": ["Technology", "Growth Stocks", "ARK-type", "Crypto"],
        "sectors_safe": ["Energy", "Defense", "Value Stocks", "Financials"],
        "macro_signals": {"high_inflation": True, "high_rates": True, "geopolitical_risk": True, "strong_dollar": True},
        "lesson": "Alzas de tasas destruyen valoraciones de crecimiento. Value y energía son refugio en ciclos restrictivos."
    },
    {
        "id": "tariffs_2025",
        "name": "Guerra Arancelaria / Incertidumbre Comercial",
        "period": "2025-2026",
        "category": "trade_war",
        "sp500_drawdown": -15,
        "recovery_years": None,
        "triggers": ["aranceles EEUU-China", "retaliación comercial global", "incertidumbre política"],
        "sectors_hurt": ["Technology", "Semiconductors", "Consumer Discretionary", "Global Supply Chains"],
        "sectors_safe": ["Domestic US Companies", "Defense", "Agriculture", "Basic Materials"],
        "macro_signals": {"trade_war": True, "geopolitical_risk": True, "supply_chain_risk": True},
        "lesson": "Empresas con cadenas de suministro domésticas y bajo riesgo arancelario son más resilientes."
    },
]

# ── Macro indicators fetch ─────────────────────────────────────────────────────

MACRO_TICKERS = {
    "vix":      "^VIX",
    "yield_10y": "^TNX",
    "yield_2y":  "^IRX",
    "oil":      "CL=F",
    "gold":     "GC=F",
    "dxy":      "DX-Y.NYB",
    "spy":      "SPY",
}


def _fetch_macro_indicators() -> dict:
    """Fetch current macro market indicators."""
    result = {}
    for key, symbol in MACRO_TICKERS.items():
        try:
            t = yf.Ticker(symbol)
            fi = t.fast_info
            price = getattr(fi, "last_price", None)
            if price:
                result[key] = round(float(price), 2)
        except Exception:
            pass

    # SPY 3-month trend
    try:
        spy = yf.Ticker("SPY")
        hist = spy.history(period="3mo")
        if not hist.empty:
            ret_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
            result["spy_3m_return"] = round(ret_3m, 2)
            # SPY 52-week drawdown
            hist_1y = spy.history(period="1y")
            if not hist_1y.empty:
                peak = hist_1y["Close"].max()
                current = hist_1y["Close"].iloc[-1]
                result["spy_drawdown_from_peak"] = round((current / peak - 1) * 100, 2)
    except Exception:
        pass

    return result


def _identify_regime(indicators: dict) -> dict:
    """Classify current macro regime based on indicators."""
    vix = indicators.get("vix", 20)
    yield_10y = indicators.get("yield_10y", 4.0)
    yield_2y  = indicators.get("yield_2y", 4.0)
    oil = indicators.get("oil", 70)
    spy_3m = indicators.get("spy_3m_return", 0)
    drawdown = indicators.get("spy_drawdown_from_peak", 0)

    signals = []
    risk_flags = []

    # VIX analysis
    if vix > 35:
        signals.append("Miedo extremo en el mercado (VIX > 35)")
        risk_flags.append("high_vix")
    elif vix > 25:
        signals.append("Estrés de mercado elevado (VIX > 25)")
        risk_flags.append("elevated_vix")
    else:
        signals.append(f"Volatilidad controlada (VIX = {vix:.1f})")

    # Yield curve (2y vs 10y)
    if yield_10y and yield_2y:
        spread = yield_10y - yield_2y
        if spread < 0:
            signals.append(f"⚠ Curva de rendimiento invertida ({spread:.2f}%) — señal de recesión histórica")
            risk_flags.append("inverted_yield_curve")
        elif spread < 0.5:
            signals.append(f"Curva de rendimiento plana ({spread:.2f}%) — precaución")
        else:
            signals.append(f"Curva de rendimiento normal (+{spread:.2f}%)")

    # Rates
    if yield_10y > 5.0:
        signals.append(f"Tasas 10Y muy elevadas ({yield_10y:.1f}%) — presión sobre valoraciones growth")
        risk_flags.append("high_rates")
    elif yield_10y > 4.0:
        signals.append(f"Tasas 10Y moderadas ({yield_10y:.1f}%)")

    # Oil
    if oil > 100:
        signals.append(f"Petróleo elevado (${oil:.0f}) — riesgo inflacionario")
        risk_flags.append("high_oil")
    elif oil < 50:
        signals.append(f"Petróleo bajo (${oil:.0f}) — deflacionario, positivo para consumo")

    # Market trend
    if drawdown < -20:
        signals.append(f"Mercado en territorio bajista ({drawdown:.1f}% desde máximos)")
        risk_flags.append("bear_market")
    elif drawdown < -10:
        signals.append(f"Corrección de mercado significativa ({drawdown:.1f}% desde máximos)")
    elif spy_3m > 5:
        signals.append(f"Tendencia alcista fuerte en S&P 500 (+{spy_3m:.1f}% en 3 meses)")

    # Regime classification
    if "inverted_yield_curve" in risk_flags and "high_vix" in risk_flags:
        regime = "recession_risk"
        regime_label = "Riesgo de Recesión"
    elif "bear_market" in risk_flags:
        regime = "bear_market"
        regime_label = "Mercado Bajista"
    elif "high_rates" in risk_flags and "high_vix" not in risk_flags:
        regime = "rate_tightening"
        regime_label = "Ciclo Restrictivo"
    elif "high_vix" in risk_flags:
        regime = "high_volatility"
        regime_label = "Alta Volatilidad"
    elif "elevated_vix" in risk_flags:
        regime = "moderate_stress"
        regime_label = "Estrés Moderado"
    else:
        regime = "normal"
        regime_label = "Normal / Alcista"

    return {
        "regime": regime,
        "regime_label": regime_label,
        "signals": signals,
        "risk_flags": risk_flags,
    }


def _find_historical_parallels(regime: str, risk_flags: list) -> list:
    """Find historical events most similar to current conditions."""
    parallels = []
    for event in HISTORICAL_EVENTS:
        score = 0
        macro_signals = event.get("macro_signals", {})

        if regime == "recession_risk" and (macro_signals.get("credit_risk") or macro_signals.get("bank_stress")):
            score += 3
        if regime == "rate_tightening" and macro_signals.get("high_rates"):
            score += 3
        if regime == "bear_market" and event["sp500_drawdown"] < -30:
            score += 2
        if "inverted_yield_curve" in risk_flags and macro_signals.get("high_rates"):
            score += 2
        if "high_oil" in risk_flags and macro_signals.get("high_oil"):
            score += 2
        if "high_vix" in risk_flags and macro_signals.get("geopolitical_risk"):
            score += 1
        if "trade_war" in str(risk_flags) and macro_signals.get("trade_war"):
            score += 3

        if score > 0:
            parallels.append({
                "event": event["name"],
                "period": event["period"],
                "similarity_score": score,
                "sp500_impact": event["sp500_drawdown"],
                "recovery_years": event.get("recovery_years"),
                "sectors_safe": event["sectors_safe"],
                "sectors_hurt": event["sectors_hurt"],
                "lesson": event["lesson"],
            })

    parallels.sort(key=lambda x: x["similarity_score"], reverse=True)
    return parallels[:3]  # Top 3 most similar


def _macro_score(regime: str, risk_flags: list) -> float:
    """Convert macro regime to a score adjustment (-0.3 to +0.1)."""
    regime_scores = {
        "recession_risk":  -0.30,
        "bear_market":     -0.25,
        "rate_tightening": -0.15,
        "high_volatility": -0.20,
        "moderate_stress": -0.10,
        "normal":          +0.05,
    }
    base = regime_scores.get(regime, 0)

    # Additional penalties
    if "inverted_yield_curve" in risk_flags:
        base -= 0.05
    if "high_oil" in risk_flags:
        base -= 0.03

    return max(-0.30, min(0.10, base))


def run(ticker: str) -> dict:
    """
    Run the macro context agent for a given ticker.
    Returns macro environment assessment + historical parallels.
    """
    indicators = _fetch_macro_indicators()
    regime_info = _identify_regime(indicators)
    parallels = _find_historical_parallels(
        regime_info["regime"], regime_info["risk_flags"]
    )
    score = _macro_score(regime_info["regime"], regime_info["risk_flags"])

    result = {
        "indicators": indicators,
        "regime": regime_info["regime"],
        "regime_label": regime_info["regime_label"],
        "macro_signals": regime_info["signals"],
        "risk_flags": regime_info["risk_flags"],
        "historical_parallels": parallels,
        "macro_score": round(score, 3),
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    save_json(tmp_path(f"{ticker}_macro_context.json"), result)
    return result


if __name__ == "__main__":
    ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    result = run(ticker)
    print(json.dumps(result, indent=2, ensure_ascii=False))
