"""
app.py — Stock Analysis Platform · Streamlit Dashboard
"""

import sys
import os
from pathlib import Path

# ── Path setup (must be first) ────────────────────────────────────────────────
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT / "tools"))

# ── NLTK download at startup (needed on Streamlit Cloud cold starts) ──────────
import nltk
nltk.download("vader_lexicon", quiet=True)

# ── DB init (safe no-op if tables already exist) ──────────────────────────────
from db_init import init_db
init_db()

# ── Standard imports ──────────────────────────────────────────────────────────
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import sqlite3
import yfinance as yf
from datetime import datetime

from utils import db_path, load_weights, tmp_path, load_json
from market_hours import get_market_status
from market_scanner import scan_market
from daily_picks import generate_daily_picks, load_daily_picks
from watchlist import WATCHLIST
from fetch_fear_greed import fetch_fear_greed

# ── Page config (must be the FIRST Streamlit call) ────────────────────────────
st.set_page_config(
    page_title="STOCKMANIA",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Password gate ─────────────────────────────────────────────────────────────
import streamlit.components.v1 as _components

def _check_password() -> bool:
    """
    Returns True if the user is authenticated.
    Auth persists across page refreshes (stored in browser sessionStorage).
    Clears when the tab is closed.
    """
    required_pw = None
    try:
        required_pw = st.secrets.get("APP_PASSWORD", None)
    except Exception:
        pass

    if not required_pw:
        return True

    # Already authenticated in this Python session
    if st.session_state.get("authenticated"):
        return True

    # JS bridge: if sessionStorage has auth token → add ?_sm=ok to URL → Streamlit sees it
    _components.html("""
    <script>
    (function() {
        try {
            if (sessionStorage.getItem('_sm_auth') === '1') {
                var url = new URL(window.parent.location.href);
                if (url.searchParams.get('_sm') !== 'ok') {
                    url.searchParams.set('_sm', 'ok');
                    window.parent.location.replace(url.toString());
                }
            }
        } catch(e) {}
    })();
    </script>
    """, height=0, scrolling=False)

    # If JS already set the param on a previous run, trust it
    if st.query_params.get("_sm") == "ok":
        st.session_state.authenticated = True
        return True

    # ── Login form ──────────────────────────────────────────────────────────
    st.markdown(
        "<div style='max-width:360px; margin:120px auto; text-align:center;'>"
        "<div style='font-size:3rem;'>📈</div>"
        "<h2 style='margin:12px 0 24px;'>STOCKMANIA</h2>"
        "</div>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        pw = st.text_input("Password", type="password", label_visibility="collapsed",
                           placeholder="Enter password")
        if st.button("Login", type="primary", use_container_width=True):
            if pw == required_pw:
                st.session_state.authenticated = True
                # Save to sessionStorage + redirect to ?_sm=ok (persists on refresh)
                _components.html("""
                <script>
                (function() {
                    try {
                        sessionStorage.setItem('_sm_auth', '1');
                        var url = new URL(window.parent.location.href);
                        url.searchParams.set('_sm', 'ok');
                        window.parent.location.replace(url.toString());
                    } catch(e) {}
                })();
                </script>
                """, height=0, scrolling=False)
            else:
                st.error("Incorrect password")
    return False

if not _check_password():
    st.stop()

# ── JS: hide sidebar toggle text artifact ────────────────────────────────────
_components.html("""
<script>
(function() {
    function hide() {
        try {
            var doc = window.parent.document;
            doc.querySelectorAll(
                '[data-testid="collapsedControl"],' +
                '[data-testid="stSidebarCollapsedControl"],' +
                '[data-testid*="ollapsedControl"]'
            ).forEach(function(el) { el.style.cssText = 'display:none!important'; });
        } catch(e) {}
    }
    hide();
    setInterval(hide, 800);
})();
</script>
""", height=0, scrolling=False)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

* { font-family: 'Inter', sans-serif !important; }

/* ── Global background ── */
[data-testid="stAppViewContainer"] {
    background: #070b18;
    background-image:
        radial-gradient(ellipse 60% 40% at 15% 10%, #0d1a4022 0%, transparent 70%),
        radial-gradient(ellipse 50% 40% at 85% 85%, #12082a18 0%, transparent 70%);
}
[data-testid="stMain"] { background: transparent; }
[data-testid="block-container"] { padding-top: 1.5rem; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #090d1e !important;
    border-right: 1px solid #1a2040 !important;
}
[data-testid="stSidebar"] > div { padding-top: 1.2rem; }

/* ── Tabs ── */
[data-testid="stTabs"] > div:first-child {
    background: #090d1e;
    border-bottom: 1px solid #1a2040;
    border-radius: 0;
    padding: 0 4px;
    gap: 2px;
}
[data-testid="stTabs"] button {
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.4px !important;
    color: #4a5580 !important;
    border-radius: 0 !important;
    padding: 12px 20px !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    transition: color 0.2s, border-color 0.2s, background 0.2s !important;
    background: transparent !important;
}
[data-testid="stTabs"] button:hover {
    color: #8892b0 !important;
    background: #ffffff06 !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #00d4aa !important;
    border-bottom: 2px solid #00d4aa !important;
    background: linear-gradient(180deg, transparent, #00d4aa0a) !important;
}
[data-testid="stTabs"] button p { font-size: 0.85rem !important; }

/* ── Metrics ── */
div[data-testid="stMetricValue"]  { font-size: 1.3rem !important; font-weight: 800 !important; color: #e8eaf6 !important; }
div[data-testid="stMetricLabel"]  { font-size: 0.72rem !important; color: #4a5580 !important; letter-spacing: 0.7px !important; text-transform: uppercase !important; }
div[data-testid="stMetricDelta"]  { font-size: 0.82rem !important; }
div[data-testid="metric-container"] {
    background: linear-gradient(145deg, #0d1428, #090d1e);
    border: 1px solid #1a2040;
    border-radius: 14px;
    padding: 14px 18px !important;
    box-shadow: 0 4px 20px #00000030;
}

/* ── Conviction cards ── */
.conviction-card {
    background: linear-gradient(145deg, #0b2235 0%, #071320 50%, #050e18 100%);
    border: 1px solid #00d4aa35;
    border-radius: 18px;
    padding: 22px 20px;
    margin-bottom: 10px;
    box-shadow: 0 0 35px #00d4aa08, 0 8px 32px #00000055, inset 0 1px 0 #00d4aa20;
    transition: border-color 0.25s, box-shadow 0.25s, transform 0.2s;
    position: relative;
    overflow: hidden;
}
.conviction-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, #00d4aa55, transparent);
}
.conviction-card:hover {
    border-color: #00d4aa70;
    box-shadow: 0 0 50px #00d4aa15, 0 12px 40px #00000065;
    transform: translateY(-3px);
}
.conviction-card-sell {
    background: linear-gradient(145deg, #280b0e 0%, #160507 50%, #0e0408 100%);
    border: 1px solid #ef535035;
    border-radius: 18px;
    padding: 22px 20px;
    margin-bottom: 10px;
    box-shadow: 0 0 35px #ef535008, 0 8px 32px #00000055, inset 0 1px 0 #ef535020;
    transition: border-color 0.25s, box-shadow 0.25s, transform 0.2s;
    position: relative; overflow: hidden;
}
.conviction-card-sell::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, #ef535055, transparent);
}
.conviction-card-sell:hover {
    border-color: #ef535070;
    box-shadow: 0 0 50px #ef535015, 0 12px 40px #00000065;
    transform: translateY(-3px);
}

/* ── Stat cards (Home tab) ── */
.stat-card {
    background: linear-gradient(145deg, #0d1428, #090d1e);
    border: 1px solid #1a2040;
    border-radius: 16px;
    padding: 20px 22px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, transform 0.2s;
}
.stat-card:hover { border-color: #2a3a6a; transform: translateY(-2px); }
.stat-card-green { border-bottom: 2px solid #00d4aa50; }
.stat-card-blue  { border-bottom: 2px solid #4f9cf950; }
.stat-card-red   { border-bottom: 2px solid #ef535050; }
.stat-card-orange{ border-bottom: 2px solid #f39c1250; }

/* ── Pick / scanner cards ── */
.pick-card {
    background: linear-gradient(135deg, #0d1428 0%, #090d1e 100%);
    border: 1px solid #1a2040;
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 8px;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.pick-card:hover { border-color: #2a3a6a; box-shadow: 0 4px 16px #4f9cf912; }

/* ── Section headers ── */
.section-header {
    background: linear-gradient(90deg, #4f9cf915, transparent);
    border-left: 3px solid #4f9cf9;
    padding: 8px 16px;
    border-radius: 0 10px 10px 0;
    margin: 20px 0 14px 0;
    font-size: 1.0rem;
    font-weight: 700;
    letter-spacing: 0.4px;
    color: #ccd6f6;
}

/* ── Verdict boxes ── */
.verdict-buy  { background: linear-gradient(135deg,#081f15,#050e0b);
                border: 1px solid #00d4aa45; border-radius: 16px; padding: 22px; text-align: center;
                box-shadow: 0 0 40px #00d4aa12, inset 0 1px 0 #00d4aa25; }
.verdict-sell { background: linear-gradient(135deg,#1f0808,#0e0505);
                border: 1px solid #ef535045; border-radius: 16px; padding: 22px; text-align: center;
                box-shadow: 0 0 40px #ef535012, inset 0 1px 0 #ef535025; }
.verdict-wait { background: linear-gradient(135deg,#1f1408,#0e0a05);
                border: 1px solid #f39c1245; border-radius: 16px; padding: 22px; text-align: center;
                box-shadow: 0 0 40px #f39c1212, inset 0 1px 0 #f39c1225; }
.big-rec { font-size: 2.6rem; font-weight: 900; letter-spacing: 3px; }

/* ── Market pill ── */
.market-open {
    display: inline-block; background: #00d4aa18; border: 1px solid #00d4aa;
    color: #00d4aa; font-weight: 700; border-radius: 20px;
    padding: 4px 14px; font-size: 0.82rem; animation: pulse-green 2.5s infinite;
}
.market-closed {
    display: inline-block; background: #ffffff06; border: 1px solid #1a2040;
    color: #4a5580; font-weight: 600; border-radius: 20px; padding: 4px 14px; font-size: 0.82rem;
}

/* ── Proj header ── */
.proj-header {
    background: linear-gradient(90deg, #130d28, #090d1e);
    border: 1px solid #2a1d50; border-radius: 14px; padding: 14px 20px; margin-bottom: 12px;
}

/* ── Animations ── */
@keyframes pulse-green {
    0%, 100% { box-shadow: 0 0 0 0 #00d4aa44; }
    50%       { box-shadow: 0 0 0 8px #00d4aa00; }
}
@keyframes fade-in-up {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
.animate-in { animation: fade-in-up 0.35s ease-out; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #090d1e; }
::-webkit-scrollbar-thumb { background: #1a2a50; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #4f9cf9; }

/* ── DataFrames ── */
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
[data-testid="stDataFrame"] > div { background: #0d1428 !important; }

/* ── Dividers ── */
hr { border-color: #1a2040 !important; margin: 18px 0 !important; }

/* ── Hide sidebar toggle button (removes keyboard_double_arrow_right text) ── */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"],
[data-testid*="collapsed"],
[data-testid*="Collapsed"] {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    position: absolute !important;
    left: -9999px !important;
}

/* ── Expanders ── */
div[data-testid="stExpander"] {
    background: #0d1428;
    border: 1px solid #1a2040 !important;
    border-radius: 12px !important;
}


/* ── Buttons ── */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    transition: all 0.2s !important;
    border: 1px solid #1a2040 !important;
    background: #0d1428 !important;
    color: #8892b0 !important;
}
.stButton > button:hover { border-color: #2a3a6a !important; color: #ccd6f6 !important; }
button[kind="primary"], .stButton > button[data-testid*="primary"] {
    background: linear-gradient(135deg, #00c49a, #00a882) !important;
    border: none !important;
    color: #000 !important;
    box-shadow: 0 4px 18px #00d4aa30 !important;
}
button[kind="primary"]:hover { box-shadow: 0 6px 24px #00d4aa50 !important; transform: translateY(-1px) !important; }

/* ── Inputs ── */
[data-testid="stTextInput"] input {
    background: #0d1428 !important;
    border: 1px solid #1a2040 !important;
    border-radius: 10px !important;
    color: #e8eaf6 !important;
}
[data-testid="stTextInput"] input:focus { border-color: #4f9cf9 !important; box-shadow: 0 0 0 2px #4f9cf918 !important; }

/* ── Toggle ── */
[data-testid="stToggle"] span { background: #0d1428 !important; }

/* ── Alerts ── */
[data-testid="stAlert"] { border-radius: 12px !important; border-left-width: 3px !important; background: #0d1428 !important; }

/* ── Captions / small text ── */
[data-testid="stCaptionContainer"] p { color: #4a5580 !important; }

/* ── Info box ── */
[data-testid="stInfo"]    { background: #0d1a2e !important; border-color: #4f9cf9 !important; color: #8892b0 !important; }
[data-testid="stWarning"] { background: #1a120a !important; border-color: #f39c12 !important; }

</style>
""", unsafe_allow_html=True)


# ── Earnings calendar ─────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)   # refresh every hour
def fetch_earnings_dates(tickers: tuple) -> dict:
    """
    Check which tickers have earnings within the next 7 days.
    Returns {ticker: {"date": "YYYY-MM-DD", "days_away": N}} for those that do.
    Uses yfinance .calendar — free, no API key.
    """
    from datetime import date, timedelta
    alerts = {}
    today  = date.today()
    window = today + timedelta(days=7)

    for ticker in tickers:
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is None or cal.empty:
                continue
            # calendar is a DataFrame with date columns; earnings date is index or columns
            # Different yfinance versions return different shapes — handle both
            if hasattr(cal, "columns"):
                for col in cal.columns:
                    val = cal[col].iloc[0] if len(cal) > 0 else None
                    if val is None:
                        continue
                    try:
                        d = pd.to_datetime(val).date()
                        if today <= d <= window:
                            alerts[ticker] = {
                                "date":      d.strftime("%Y-%m-%d"),
                                "days_away": (d - today).days,
                            }
                            break
                    except Exception:
                        continue
            elif hasattr(cal, "index"):
                for idx_val in cal.index:
                    try:
                        d = pd.to_datetime(idx_val).date()
                        if today <= d <= window:
                            alerts[ticker] = {
                                "date":      d.strftime("%Y-%m-%d"),
                                "days_away": (d - today).days,
                            }
                            break
                    except Exception:
                        continue
        except Exception:
            continue

    return alerts


# ── Cached data fetchers ───────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def cached_run_analysis(ticker: str) -> dict:
    from fetch_company_overview import fetch_company_overview
    from fetch_fundamentals import fetch_fundamentals
    from fetch_news import fetch_news
    from fetch_technicals import fetch_technicals
    from fetch_risk_factors import fetch_risk_factors
    from fetch_opportunities import fetch_opportunities
    from decision_engine import make_decision

    overview      = fetch_company_overview(ticker)
    fundamentals  = fetch_fundamentals(ticker)
    news          = fetch_news(ticker, overview.get("name", ""))
    technicals    = fetch_technicals(ticker)
    risks         = fetch_risk_factors(ticker)
    opportunities = fetch_opportunities(ticker)
    decision      = make_decision(ticker)

    return dict(
        overview=overview, fundamentals=fundamentals, news=news,
        technicals=technicals, risks=risks, opportunities=opportunities,
        decision=decision,
    )


@st.cache_data(ttl=300, show_spinner=False)
def cached_price_history(ticker: str) -> pd.DataFrame:
    t = yf.Ticker(ticker)
    df = t.history(period="6mo", interval="1d")
    df.index = pd.to_datetime(df.index)
    return df


# ── Chart builder ──────────────────────────────────────────────────────────────

def build_chart(df: pd.DataFrame, technicals: dict) -> go.Figure:
    close = df["Close"]

    # SMAs on the 6-month slice
    sma20  = close.rolling(20).mean()
    sma50  = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    # RSI
    delta     = close.diff()
    gain      = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss      = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rs        = gain / loss.replace(0, float("nan"))
    rsi_series = 100 - (100 / (1 + rs))

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.03,
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        name="OHLC",
        increasing_line_color="#00d4aa",
        decreasing_line_color="#ef5350",
        increasing_fillcolor="#00d4aa",
        decreasing_fillcolor="#ef5350",
    ), row=1, col=1)

    # SMA overlays
    for sma, name, color in [
        (sma20,  "SMA 20",  "#f39c12"),
        (sma50,  "SMA 50",  "#3498db"),
        (sma200, "SMA 200", "#9b59b6"),
    ]:
        fig.add_trace(go.Scatter(
            x=df.index, y=sma, name=name,
            line=dict(color=color, width=1.5),
            mode="lines",
        ), row=1, col=1)

    # Support / Resistance
    ns = technicals.get("nearest_support")
    nr = technicals.get("nearest_resistance")
    if ns:
        fig.add_hline(y=ns, line_dash="dot", line_color="#2ecc71", line_width=1,
                      annotation_text=f"Support ${ns:.2f}",
                      annotation_position="bottom right",
                      annotation_font_color="#2ecc71",
                      row=1, col=1)
    if nr:
        fig.add_hline(y=nr, line_dash="dot", line_color="#e74c3c", line_width=1,
                      annotation_text=f"Resistance ${nr:.2f}",
                      annotation_position="top right",
                      annotation_font_color="#e74c3c",
                      row=1, col=1)

    # Bollinger Bands
    bb_upper = technicals.get("bb_upper")
    bb_lower = technicals.get("bb_lower")
    if bb_upper and bb_lower:
        # Only show the last value as a fill area using a static line
        # (full BB history would require re-computing — skip for simplicity)
        pass

    # RSI
    fig.add_trace(go.Scatter(
        x=df.index, y=rsi_series, name="RSI (14)",
        line=dict(color="#e67e22", width=1.5),
        mode="lines",
    ), row=2, col=1)

    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(231,76,60,0.08)",  line_width=0, row=2, col=1)
    fig.add_hrect(y0=0,  y1=30,  fillcolor="rgba(46,204,113,0.08)", line_width=0, row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(231,76,60,0.4)",  line_width=1, row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(46,204,113,0.4)", line_width=1, row=2, col=1)

    fig.update_layout(
        height=580,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(14,17,23,0.95)",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(size=11)),
        margin=dict(l=10, r=10, t=10, b=10),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Price (USD)", row=1, col=1,
                     gridcolor="rgba(255,255,255,0.04)", tickprefix="$")
    fig.update_yaxes(title_text="RSI", row=2, col=1,
                     range=[0, 100], gridcolor="rgba(255,255,255,0.04)")
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.04)", showspikes=True)

    return fig


# ── Render helpers ─────────────────────────────────────────────────────────────

def render_header(ticker, overview, decision):
    verdict = decision["verdict"]
    rec     = decision["recommendation"]
    price   = decision.get("current_price", 0)
    conf    = decision["confidence_pct"]
    score   = decision["final_score"]

    VCOL = {"Bullish": "green", "Neutral": "orange", "Bearish": "red"}
    vcol = VCOL.get(verdict, "gray")

    c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1, 1])
    with c1:
        st.markdown(f"## {overview.get('name', ticker)}")
        st.caption(
            f"**{overview.get('sector','N/A')}** › {overview.get('industry','N/A')} · "
            f"{overview.get('exchange','N/A')} · {overview.get('country','N/A')}"
        )
    c2.metric("Price",      f"${price:,.2f}")
    c3.metric("Score",      f"{score:+.3f}")
    c4.metric("Confidence", f"{conf}%")
    with c5:
        st.markdown(
            f"<div style='text-align:center; padding-top:4px;'>"
            f"<span style='color:{'#00d4aa' if rec=='Buy' else '#ef5350' if rec=='Sell' else '#f39c12'};"
            f"font-size:1.6rem; font-weight:900;'>{rec}</span><br/>"
            f"<span style='color:{'#00d4aa' if verdict=='Bullish' else '#ef5350' if verdict=='Bearish' else '#f39c12'};"
            f"font-size:0.85rem;'>{verdict}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_score_cards(data):
    bd = data["decision"]["score_breakdown"]
    modules = [
        ("Fundamentals", bd["fundamentals"]["adjusted"], data["fundamentals"]["rating"],     "25%"),
        ("News",         bd["news"]["adjusted"],         data["news"]["sentiment"],           "20%"),
        ("Technical",    bd["technicals"]["adjusted"],   data["technicals"]["trend"].get("long_term","?") + " Trend", "30%"),
        ("Risk",         bd["risk"]["adjusted"],         data["risks"]["risk_level"],         "15%"),
        ("Opportunity",  bd["opportunities"]["adjusted"],data["opportunities"]["opportunity_level"], "10%"),
    ]
    cols = st.columns(5)
    for col, (name, score, label, weight) in zip(cols, modules):
        with col:
            st.metric(
                label=f"{name} ({weight})",
                value=f"{score:+.2f}",
                delta=label,
            )


def render_technicals_table(technicals):
    t = technicals
    trend = t.get("trend", {})
    rsi   = t.get("rsi")
    macd  = t.get("macd", 0) or 0
    sig   = t.get("macd_signal", 0) or 0

    rows = [
        ("RSI (14)",      f"{rsi:.1f}" if rsi else "N/A",
                          "Oversold" if rsi and rsi < 30 else "Overbought" if rsi and rsi > 70 else "Neutral"),
        ("MACD",          f"{macd:.4f}",   "Bullish" if macd > sig else "Bearish"),
        ("MACD Signal",   f"{sig:.4f}",    ""),
        ("SMA 20",        f"${t.get('sma20') or 'N/A'}", ""),
        ("SMA 50",        f"${t.get('sma50') or 'N/A'}", ""),
        ("SMA 200",       f"${t.get('sma200') or 'N/A'}", ""),
        ("Bollinger High",f"${t.get('bb_upper') or 'N/A'}", ""),
        ("Bollinger Low", f"${t.get('bb_lower') or 'N/A'}", ""),
        ("Support",       f"${t.get('nearest_support') or 'N/A'}",    "Key Level"),
        ("Resistance",    f"${t.get('nearest_resistance') or 'N/A'}", "Key Level"),
        ("Vol Ratio",     f"{t.get('volume_ratio') or 'N/A'}x",       "vs 20-day avg"),
        ("Trend Short",   trend.get("short_term", "N/A"),  ""),
        ("Trend Long",    trend.get("long_term", "N/A"),   ""),
        ("MA Cross",      trend.get("ma_cross", "N/A"),    ""),
        ("Entry Zone",    f"${t.get('entry_zone_low','?'):.2f} – ${t.get('entry_zone_high','?'):.2f}", "Suggested entry"),
        ("Stop Loss",     f"${t.get('stop_loss','?'):.2f}",   "Exit on loss"),
        ("Target",        f"${t.get('target_price','?'):.2f}", "Take profit"),
    ]
    df = pd.DataFrame(rows, columns=["Indicator", "Value", "Signal"])
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        height=530,
        column_config={
            "Indicator": st.column_config.TextColumn("Indicator", help="Name of the technical indicator or price level"),
            "Value":     st.column_config.TextColumn("Value",     help="Current calculated value for this indicator"),
            "Signal":    st.column_config.TextColumn("Signal",    help="What this indicator is currently saying about price direction"),
        },
    )


def render_news(news):
    sentiment  = news.get("sentiment", "Neutral")
    sent_score = news.get("sentiment_score", 0)
    total      = news.get("total_articles", 0)
    key_events = news.get("key_events", [])
    positives  = news.get("top_positive_headlines", [])
    negatives  = news.get("top_negative_headlines", [])
    articles   = news.get("articles", [])

    SCOL = {"Bullish": "#00d4aa", "Bearish": "#ef5350", "Neutral": "#f39c12"}
    color = SCOL.get(sentiment, "gray")

    st.markdown(
        f"<span style='color:{color}; font-weight:700; font-size:1.1rem;'>"
        f"{sentiment}</span> &nbsp; Score: <code>{sent_score:+.3f}</code> &nbsp;|&nbsp; "
        f"{total} articles analyzed",
        unsafe_allow_html=True,
    )

    if key_events:
        st.markdown("**Key Events:** " + "  ".join(f"`{e}`" for e in key_events))

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Positive Headlines**")
        for h in positives:
            st.markdown(f"<span style='color:#00d4aa'>+</span> {h}", unsafe_allow_html=True)
    with col2:
        st.markdown("**Negative Headlines**")
        for h in negatives:
            st.markdown(f"<span style='color:#ef5350'>-</span> {h}", unsafe_allow_html=True)

    with st.expander(f"All {total} articles"):
        for a in articles[:20]:
            score = a.get("vader_score", 0)
            col = "#00d4aa" if score > 0.05 else "#ef5350" if score < -0.05 else "#aaa"
            st.markdown(
                f"<a href='{a.get('url','#')}' target='_blank' "
                f"style='color:{col}; text-decoration:none;'>{a.get('title','')}</a>"
                f" &nbsp;<span style='color:#666; font-size:0.8rem;'>"
                f"{a.get('source','')} · {a.get('date','')} · score: {score:+.3f}</span>",
                unsafe_allow_html=True,
            )


def render_risk_opportunity(risks, opportunities):
    col1, col2 = st.columns(2)
    with col1:
        level = risks.get("risk_level", "?")
        lcol  = "#ef5350" if level == "High" else "#f39c12" if level == "Moderate" else "#00d4aa"
        st.markdown(f"**Risk Level:** <span style='color:{lcol}'>{level}</span>",
                    unsafe_allow_html=True)
        for r in risks.get("reasoning", []):
            st.markdown(f"<span style='color:#ef5350'>⚠</span> {r}", unsafe_allow_html=True)
    with col2:
        level = opportunities.get("opportunity_level", "?")
        lcol  = "#00d4aa" if level == "High" else "#f39c12" if level == "Moderate" else "#aaa"
        st.markdown(f"**Opportunity Level:** <span style='color:{lcol}'>{level}</span>",
                    unsafe_allow_html=True)
        for o in opportunities.get("reasoning", []):
            st.markdown(f"<span style='color:#00d4aa'>+</span> {o}", unsafe_allow_html=True)


def render_verdict(decision):
    rec    = decision["recommendation"]
    verdict= decision["verdict"]
    score  = decision["final_score"]
    conf   = decision["confidence_pct"]
    timing = decision.get("timing", "")

    REC_CSS = {
        "Buy":  "verdict-buy",
        "Sell": "verdict-sell",
        "Wait": "verdict-wait",
    }
    REC_COLOR = {"Buy": "#00d4aa", "Sell": "#ef5350", "Wait": "#f39c12"}
    color = REC_COLOR.get(rec, "#aaa")

    st.markdown(
        f"<div class='{REC_CSS.get(rec, '')}' style='margin: 12px 0;'>"
        f"<div class='big-rec' style='color:{color}'>{rec}</div>"
        f"<div style='color:#ccc; margin-top:4px;'>{verdict} &nbsp;|&nbsp; "
        f"Score: {score:+.3f} &nbsp;|&nbsp; Confidence: {conf}%</div>"
        f"<div style='color:#888; font-size:0.9rem; margin-top:8px;'>{timing}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    ez_low  = decision.get("entry_zone_low")
    ez_high = decision.get("entry_zone_high")
    sl      = decision.get("stop_loss")
    tp      = decision.get("target_price")

    ez_str = f"${ez_low:.2f} – ${ez_high:.2f}" if ez_low and ez_high else "N/A"
    sl_str = f"${sl:.2f}" if sl else "N/A"
    tp_str = f"${tp:.2f}" if tp else "N/A"

    c1.metric("Entry Zone",   ez_str)
    c2.metric("Stop Loss",    sl_str)
    c3.metric("Target Price", tp_str)


# ── Tab 2: My Trades ───────────────────────────────────────────────────────────

def render_trades_tab():
    st.header("My Trades")
    st.caption(
        "Record trades via CLI: `python tools/record_trade.py TICKER PRICE Buy`  "
        "and close via: `python tools/record_outcome.py TRADE_ID EXIT_PRICE`"
    )
    st.info(
        "SQLite is ephemeral on Streamlit Community Cloud — trade history resets "
        "on each new deployment. For persistence, run the app locally.",
        icon="ℹ",
    )

    db = db_path()
    if not db.exists():
        st.warning("Database not initialized yet. Analyze a stock first.")
        return

    conn = sqlite3.connect(db)
    try:
        trades_df = pd.read_sql_query(
            "SELECT id, ticker, entry_date, entry_price, exit_date, exit_price, "
            "pnl_pct, outcome, recommendation, confidence_pct, verdict, notes "
            "FROM trades ORDER BY entry_date DESC",
            conn
        )
    finally:
        conn.close()

    if trades_df.empty:
        st.info("No trades recorded yet.")
        return

    closed = trades_df[trades_df["outcome"].notna()]
    wins   = (closed["outcome"] == "win").sum()
    losses = (closed["outcome"] == "loss").sum()
    wr     = (wins / len(closed) * 100) if len(closed) > 0 else 0
    avg_pnl= closed["pnl_pct"].mean() if not closed.empty else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Trades",  len(trades_df))
    m2.metric("Closed",        len(closed))
    m3.metric("Wins",          int(wins))
    m4.metric("Win Rate",      f"{wr:.1f}%")
    m5.metric("Avg P&L",       f"{avg_pnl:.2f}%")

    if not closed.empty:
        # P&L bar chart
        fig = go.Figure(go.Bar(
            x=closed["ticker"] + " #" + closed["id"].astype(str),
            y=closed["pnl_pct"],
            marker_color=["#00d4aa" if v >= 0 else "#ef5350" for v in closed["pnl_pct"]],
            text=[f"{v:.1f}%" for v in closed["pnl_pct"]],
            textposition="outside",
        ))
        fig.add_hline(y=0, line_color="white", line_width=1)
        fig.update_layout(
            template="plotly_dark",
            height=250,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(14,17,23,0.95)",
            yaxis_title="P&L %",
            showlegend=False,
            margin=dict(l=10, r=10, t=10, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        trades_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "id":            st.column_config.NumberColumn("ID",          help="Trade ID — use this number with record_outcome.py to close the trade"),
            "ticker":        st.column_config.TextColumn(  "Ticker",      help="Stock symbol"),
            "entry_date":    st.column_config.TextColumn(  "Entry Date",  help="Date and time you entered the position"),
            "entry_price":   st.column_config.NumberColumn("Entry $",     format="$%.2f", help="Price at which you bought/shorted"),
            "exit_date":     st.column_config.TextColumn(  "Exit Date",   help="Date the position was closed (blank if still open)"),
            "exit_price":    st.column_config.NumberColumn("Exit $",      format="$%.2f", help="Price at which you closed the position"),
            "pnl_pct":       st.column_config.NumberColumn("P&L %",       format="%.2f%%",help="Percentage gain or loss: (exit - entry) / entry × 100"),
            "outcome":       st.column_config.TextColumn(  "Outcome",     help="win = P&L > +5% | loss = P&L < -5% | neutral = in between"),
            "recommendation":st.column_config.TextColumn(  "Algo Rec",    help="What the algorithm recommended when you entered"),
            "confidence_pct":st.column_config.NumberColumn("Confidence",  format="%d%%",  help="Algorithm's confidence at the time of the recommendation"),
            "verdict":       st.column_config.TextColumn(  "Verdict",     help="Bullish / Bearish / Neutral — the overall market bias when you entered"),
        }
    )


# ── Tab 3: Learning System ─────────────────────────────────────────────────────

def render_learning_tab():
    st.header("Learning System — Signal Weights")
    st.caption(
        "After closing trades via `record_outcome.py`, run `python tools/analyze_errors.py` "
        "and `python tools/adjust_weights.py` to update weights."
    )

    weights = load_weights()
    weights_clean = {k: v for k, v in weights.items() if k != "last_updated"}
    last_updated  = weights.get("last_updated", "Never")

    st.caption(f"Last updated: {last_updated}")

    weights_df = pd.DataFrame(
        [(k, v) for k, v in weights_clean.items()],
        columns=["Signal", "Weight"]
    ).sort_values("Weight", ascending=False)

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Current Weights")
        st.dataframe(
            weights_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Signal": st.column_config.TextColumn("Signal", help="Technical signal tracked by the learning system (RSI, MA crossovers, MACD, etc.)"),
                "Weight": st.column_config.ProgressColumn(
                    "Weight", min_value=0.2, max_value=2.0, format="%.3f",
                    help="Learning weight: 1.0 = default, >1.0 = this signal has been accurate, <1.0 = this signal has been unreliable. Range: 0.2 – 2.0"
                ),
            }
        )

    with col2:
        db = db_path()
        if not db.exists():
            st.info("No database yet. Run an analysis first.")
            return

        conn = sqlite3.connect(db)
        try:
            hist_df = pd.read_sql_query(
                "SELECT signal_type, weight, accuracy_pct, sample_size, recorded_at "
                "FROM weight_history ORDER BY recorded_at ASC",
                conn
            )
        finally:
            conn.close()

        if hist_df.empty:
            st.info(
                "No weight history yet. Close some trades with `record_outcome.py` "
                "then run `adjust_weights.py`."
            )
            return

        hist_df["recorded_at"] = pd.to_datetime(hist_df["recorded_at"])

        # Weight evolution chart
        st.subheader("Weight History")
        fig = go.Figure()
        for sig in hist_df["signal_type"].unique():
            s = hist_df[hist_df["signal_type"] == sig]
            fig.add_trace(go.Scatter(
                x=s["recorded_at"], y=s["weight"],
                name=sig, mode="lines+markers", marker=dict(size=6),
            ))
        fig.add_hline(y=1.0, line_dash="dash", line_color="rgba(255,255,255,0.3)",
                      annotation_text="Default (1.0)", annotation_font_color="#888")
        fig.update_layout(
            template="plotly_dark", height=280,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(14,17,23,0.95)",
            yaxis_title="Weight", xaxis_title="Date",
            hovermode="x unified",
            legend=dict(orientation="h", font=dict(size=10)),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Signal accuracy bar chart
        st.subheader("Signal Accuracy (Latest)")
        latest = (
            hist_df.sort_values("recorded_at")
            .groupby("signal_type")
            .last()
            .reset_index()
        )
        fig2 = go.Figure(go.Bar(
            x=latest["signal_type"],
            y=latest["accuracy_pct"],
            text=[f"{v:.0f}%" for v in latest["accuracy_pct"]],
            textposition="outside",
            marker_color=[
                "#00d4aa" if v >= 60 else "#f39c12" if v >= 45 else "#ef5350"
                for v in latest["accuracy_pct"]
            ],
        ))
        fig2.add_hline(y=50, line_dash="dash", line_color="rgba(255,255,0,0.4)",
                       annotation_text="50% baseline")
        fig2.update_layout(
            template="plotly_dark", height=280,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(14,17,23,0.95)",
            yaxis_title="Accuracy %", yaxis_range=[0, 110],
            xaxis_tickangle=-35,
            showlegend=False,
            margin=dict(l=10, r=10, t=10, b=80),
        )
        st.plotly_chart(fig2, use_container_width=True)

        with st.expander("Raw accuracy table"):
            st.dataframe(latest[["signal_type","accuracy_pct","sample_size","weight"]],
                         hide_index=True, use_container_width=True)


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    # ── Logo / brand ───────────────────────────────────────────────────────────
    st.markdown(
        "<div style='padding:4px 0 20px;text-align:center;'>"
        "<div style='display:inline-block;"
        "font-size:1.55rem;font-weight:900;letter-spacing:1px;"
        "color:#f5a623;"
        "-webkit-text-stroke:2px #c47d0a;"
        "text-shadow:0 2px 0 #7a4d00,0 4px 8px #00000088,0 0 20px #f5a62340;"
        "font-family:Impact,\"Arial Black\",sans-serif !important;"
        "line-height:1;'>STOCKMANIA</div>"
        "<div style='font-size:0.62rem;color:#4a5580;letter-spacing:1.5px;"
        "text-transform:uppercase;margin-top:4px;'>Trading Intelligence</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Market status ───────────────────────────────────────────────────────────
    mkt = get_market_status()
    if mkt["is_open"]:
        msg_part = mkt['message'].split('—')[1].strip() if '—' in mkt['message'] else ''
        st.markdown(
            "<div style='background:linear-gradient(135deg,#0a2018,#061410);"
            "border:1px solid #00d4aa35;border-radius:10px;"
            "padding:10px 14px;margin-bottom:16px;'>"
            "<div style='display:flex;align-items:center;gap:8px;'>"
            "<span style='color:#00d4aa;font-size:0.7rem;animation:pulse-green 2s infinite;'>●</span>"
            "<span style='color:#00d4aa;font-weight:700;font-size:0.88rem;'>NYSE ABIERTO</span>"
            "</div>"
            f"<div style='color:#4a5580;font-size:0.73rem;margin-top:3px;'>{msg_part}</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        label = {"pre_market": "PRE-MARKET", "post_market": "CERRADO",
                 "weekend": "FIN DE SEMANA", "holiday": "FERIADO"}.get(mkt["status"], "CERRADO")
        msg_part = mkt['message'].split('—')[1].strip() if '—' in mkt['message'] else ''
        st.markdown(
            "<div style='background:#090d1e;border:1px solid #1a2040;"
            "border-radius:10px;padding:10px 14px;margin-bottom:16px;'>"
            "<div style='display:flex;align-items:center;gap:8px;'>"
            "<span style='color:#2a3a6a;font-size:0.7rem;'>○</span>"
            f"<span style='color:#4a5580;font-weight:700;font-size:0.88rem;'>{label}</span>"
            "</div>"
            f"<div style='color:#2a3a5a;font-size:0.73rem;margin-top:3px;'>{msg_part}</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    # ── Auto-refresh ────────────────────────────────────────────────────────────
    auto_refresh = st.toggle("Auto-refresh (5 min)", value=False)
    if auto_refresh:
        import time
        time.sleep(300)
        st.rerun()

    st.divider()

    # ── Data sources ────────────────────────────────────────────────────────────
    st.markdown(
        "<div style='font-size:0.68rem;color:#2a3a5a;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;'>Fuentes</div>"
        "<div style='font-size:0.78rem;color:#2a3a5a;line-height:1.9;'>"
        "📊 Yahoo Finance<br/>📰 Google News RSS<br/>🧠 VADER Sentiment<br/>📈 CNN Fear & Greed"
        "</div>"
        "<div style='margin-top:10px;font-size:0.68rem;color:#1e2840;'>Sin API keys · 100% gratis</div>",
        unsafe_allow_html=True,
    )


# ── Main layout ────────────────────────────────────────────────────────────────

tab0, tab1, tab2, tab3, tab4 = st.tabs(
    ["🏠 Home", "🔍 Scanner", "📊 Análisis", "💼 Trades", "🧠 Learning"]
)

# ── Tab 1: Market Scanner ─────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)   # thin wrapper; real cache is file-based (15 min)
def cached_scan(force: bool) -> dict:
    return scan_market(force=force, top_n=10)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_fear_greed() -> dict:
    try:
        return fetch_fear_greed()
    except Exception:
        return {"score": 50.0, "rating": "Neutral", "color": "#aaa",
                "prev_close": 50.0, "source": "unavailable",
                "bias": {"signal": "neutral", "note": "", "score_adj": 0.0}}


@st.cache_data(ttl=120, show_spinner=False)
def cached_daily_picks(scan_data_ts: str, scan_data: dict) -> dict:
    """scan_data_ts is the cached_at string — changes when scan updates."""
    return generate_daily_picks(scan_data)


def _rec_badge(rec: str) -> str:
    color = {"Buy": "#00d4aa", "Sell": "#ef5350", "Wait": "#f39c12"}.get(rec, "#aaa")
    return (
        f"<span style='background:{color}22;border:1px solid {color};"
        f"border-radius:4px;padding:2px 8px;color:{color};"
        f"font-weight:700;font-size:0.85rem;'>{rec}</span>"
    )


def _sev_badge(sev: str) -> str:
    color = {"high": "#ef5350", "medium": "#f39c12", "low": "#aaa"}.get(sev, "#aaa")
    return (
        f"<span style='color:{color};font-weight:700;font-size:0.8rem;'>"
        f"[{sev.upper()}]</span>"
    )


def _pnl_color(pnl: float) -> str:
    if pnl >= WIN_THRESHOLD_DISPLAY:
        return "#00d4aa"
    if pnl <= LOSS_THRESHOLD_DISPLAY:
        return "#ef5350"
    return "#00d4aa" if pnl > 0 else "#ef5350" if pnl < 0 else "#aaa"

WIN_THRESHOLD_DISPLAY  =  5.0
LOSS_THRESHOLD_DISPLAY = -3.0


_SIGNAL_REASONS = {
    "rsi_oversold":         "RSI below 30 — stock is oversold and historically bounces from this zone",
    "rsi_overbought":       "RSI above 70 — strong momentum, but watch for exhaustion",
    "golden_cross":         "SMA 20 crossed above SMA 50 — classic bullish trend change signal",
    "death_cross":          "SMA 20 crossed below SMA 50 — bearish trend signal",
    "above_both_mas":       "Price is above both SMA 20 and SMA 50 — uptrend confirmed",
    "below_both_mas":       "Price is below both moving averages — downtrend in place",
    "strong_momentum_up":   "5-day momentum is strongly positive — buyers are in control",
    "strong_momentum_down": "5-day momentum is strongly negative — sellers dominating",
    "volume_confirms_up":   "Price rise confirmed by above-average volume — institutional accumulation likely",
    "volume_confirms_down": "Price drop confirmed by above-average volume — distribution / selling pressure",
}


def _render_buy_reason(r: dict):
    """Inline detail panel explaining why the algo flagged this as a Buy."""
    rec    = r.get("recommendation", "Buy")
    score  = r.get("score", 0)
    conf   = r.get("confidence_pct", 0)
    rsi    = r.get("rsi", 50)
    vr     = r.get("volume_ratio", 1)
    chg1d  = r.get("change_1d_pct", 0)
    chg5d  = r.get("change_5d_pct", 0)
    signals = r.get("signals", {})
    manip   = r.get("manipulation_flags", [])
    price   = r.get("current_price", 0)
    sector  = r.get("sector", "")

    color = "#00d4aa" if rec == "Buy" else "#ef5350"

    # ── Score & Confidence bar ────────────────────────────────────────────────
    col_s, col_c, col_p = st.columns(3)
    col_s.metric("Algo Score",  f"{score:+.3f}", help="Combined signal score — closer to +1.0 = stronger buy")
    col_c.metric("Confidence",  f"{conf}%",      help="How confident the algo is in this call")
    col_p.metric("Price",       f"${price:.2f}", delta=f"{chg1d:+.1f}% today")

    st.divider()

    # ── Why it triggered ─────────────────────────────────────────────────────
    if signals:
        st.markdown("**Signals that fired:**")
        for sig_key in signals:
            reason = _SIGNAL_REASONS.get(sig_key, sig_key.replace("_", " ").title())
            bullet_color = color
            st.markdown(
                f"<span style='color:{bullet_color};font-weight:700;'>✔</span> "
                f"<strong>{sig_key.replace('_',' ').title()}</strong> — "
                f"<span style='color:#bbb;font-size:0.9rem;'>{reason}</span>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No specific signal details available.")

    st.divider()

    # ── Technical context ─────────────────────────────────────────────────────
    col_r, col_v, col_m = st.columns(3)
    rsi_label = "Oversold ← buy zone" if rsi < 30 else "Overbought" if rsi > 70 else "Neutral"
    rsi_color  = "#00d4aa" if rsi < 30 else "#ef5350" if rsi > 70 else "#f39c12"
    col_r.markdown(
        f"**RSI (14):** <span style='color:{rsi_color};font-weight:700;'>{rsi:.0f}</span> "
        f"<span style='color:#888;font-size:0.8rem;'>— {rsi_label}</span>",
        unsafe_allow_html=True,
    )

    vr_color = "#00d4aa" if vr >= 2 else "#f39c12" if vr >= 1.2 else "#888"
    col_v.markdown(
        f"**Volume:** <span style='color:{vr_color};font-weight:700;'>{vr:.1f}x</span> "
        f"<span style='color:#888;font-size:0.8rem;'>vs 20-day avg</span>",
        unsafe_allow_html=True,
    )

    chg5_color = "#00d4aa" if chg5d > 0 else "#ef5350"
    col_m.markdown(
        f"**5-day move:** <span style='color:{chg5_color};font-weight:700;'>{chg5d:+.1f}%</span> "
        f"<span style='color:#888;font-size:0.8rem;'>weekly momentum</span>",
        unsafe_allow_html=True,
    )

    # ── Manipulation warnings ─────────────────────────────────────────────────
    if manip:
        med_high = [f for f in manip if f.get("severity") in ("high", "medium")]
        if med_high:
            st.markdown("**⚠ Caution flags:**")
            for f in med_high:
                sev_col = "#ef5350" if f["severity"] == "high" else "#f39c12"
                st.markdown(
                    f"<span style='color:{sev_col};font-size:0.85rem;'>[{f['severity'].upper()}] {f['detail']}</span>",
                    unsafe_allow_html=True,
                )

    st.caption(f"Sector: {sector} · Data via Yahoo Finance")


def _status_badge(status: str) -> str:
    cfg = {
        "active":     ("#f39c12", "ACTIVE"),
        "target_hit": ("#00d4aa", "TARGET HIT"),
        "stop_hit":   ("#ef5350", "STOP HIT"),
        "closed":     ("#888",    "CLOSED"),
    }.get(status, ("#888", status.upper()))
    return (
        f"<span style='background:{cfg[0]}22;border:1px solid {cfg[0]};"
        f"border-radius:4px;padding:1px 7px;color:{cfg[0]};"
        f"font-size:0.75rem;font-weight:700;'>{cfg[1]}</span>"
    )


def render_conviction_picks(picks: list, market_is_open: bool, earnings_map: dict = {}):
    """Render the Top 5 High-Conviction section — large glassmorphism cards."""
    st.markdown(
        "<div class='section-header'>★ Top 5 Conviction Picks</div>",
        unsafe_allow_html=True,
    )
    st.caption("Score ≥ 0.40 · Confianza ≥ 62% · Múltiples señales · Sin flags de manipulación")

    if not picks:
        st.info("Sin picks de alta convicción por ahora. El algoritmo está siendo cauteloso.")
        return

    # Row 1: up to 3 picks
    row1 = picks[:3]
    row2 = picks[3:5]

    for row in [row1, row2]:
        if not row:
            continue
        cols = st.columns(len(row))
        for col, p in zip(cols, row):
            rec     = p["recommendation"]
            pnl     = p.get("pnl_pct", 0.0)
            score   = p.get("current_score", p["score"])
            conf    = p.get("confidence_pct", 0)
            status  = p.get("status", "active")
            color   = "#00d4aa" if rec == "Buy" else "#ef5350"
            pnl_col = _pnl_color(pnl)
            ticker  = p["ticker"]
            earn    = earnings_map.get(ticker)
            signals = p.get("signals", [])[:3]
            sigs_str = " · ".join(s.replace("_"," ") for s in signals) if signals else "—"
            card_cls = "conviction-card" if rec == "Buy" else "conviction-card-sell"

            earn_html = ""
            if earn:
                earn_html = (
                    f"<div style='margin-top:10px;background:#f39c1210;border:1px solid #f39c1244;"
                    f"border-radius:8px;padding:5px 10px;font-size:0.75rem;color:#f39c12;'>"
                    f"⚠ Earnings en {earn['days_away']} día(s) — {earn['date']}</div>"
                )

            not_open_html = ""
            if not market_is_open and status == "active":
                not_open_html = (
                    f"<div style='margin-top:8px;font-size:0.72rem;color:#4a5580;'>"
                    f"Planifica para la próxima apertura</div>"
                )

            with col:
                st.markdown(
                    f"<div class='{card_cls} animate-in'>"
                    # Header row
                    f"<div style='display:flex;justify-content:space-between;align-items:flex-start;'>"
                    f"  <div>"
                    f"    <div style='font-size:1.8rem;font-weight:900;color:{color};letter-spacing:1.5px;'>{ticker}</div>"
                    f"    <div style='font-size:0.78rem;color:#4a5580;margin-top:1px;'>{p.get('sector','')}</div>"
                    f"  </div>"
                    f"  <div style='text-align:right;'>"
                    f"    <div style='background:{color}20;border:1px solid {color}55;color:{color};"
                    f"         border-radius:8px;padding:3px 12px;font-weight:800;font-size:0.88rem;'>{rec}</div>"
                    f"    <div style='margin-top:6px;'>{_status_badge(status)}</div>"
                    f"  </div>"
                    f"</div>"
                    # Price & P&L
                    f"<div style='margin-top:14px;padding-top:12px;border-top:1px solid #1a2040;display:flex;justify-content:space-between;align-items:flex-end;'>"
                    f"  <div>"
                    f"    <div style='font-size:0.7rem;color:#4a5580;text-transform:uppercase;letter-spacing:0.7px;'>Precio</div>"
                    f"    <div style='font-size:1.4rem;font-weight:800;color:#ccd6f6;'>${p.get('current_price',0):.2f}</div>"
                    f"  </div>"
                    f"  <div style='text-align:right;'>"
                    f"    <div style='font-size:0.7rem;color:#4a5580;text-transform:uppercase;letter-spacing:0.7px;'>P&L hoy</div>"
                    f"    <div style='font-size:1.4rem;font-weight:900;color:{pnl_col};'>{pnl:+.2f}%</div>"
                    f"  </div>"
                    f"</div>"
                    # Score bar
                    f"<div style='margin-top:12px;'>"
                    f"  <div style='display:flex;justify-content:space-between;margin-bottom:4px;'>"
                    f"    <span style='font-size:0.7rem;color:#4a5580;'>Score {score:+.3f}</span>"
                    f"    <span style='font-size:0.7rem;color:#4a5580;'>Confianza {conf}%</span>"
                    f"  </div>"
                    f"  <div style='background:#1a2040;border-radius:4px;height:4px;overflow:hidden;'>"
                    f"    <div style='background:{color};height:4px;border-radius:4px;"
                    f"         width:{min(100,int(conf))}%;transition:width 0.6s;'></div>"
                    f"  </div>"
                    f"</div>"
                    # Signals
                    f"<div style='margin-top:10px;font-size:0.72rem;color:#4a5580;'>{sigs_str}</div>"
                    f"{earn_html}{not_open_html}"
                    f"</div>",
                    unsafe_allow_html=True,
                )


def render_daily_watchlist(picks: list, market_is_open: bool):
    """Render the Daily Top 10 tracking table."""
    active  = [p for p in picks if p.get("status") == "active"]
    closed  = [p for p in picks if p.get("status") != "active"]

    wins_today   = sum(1 for p in closed if p.get("outcome") == "win")
    losses_today = sum(1 for p in closed if p.get("outcome") == "loss")

    col_t, col_w, col_l = st.columns(3)
    col_t.metric("Tracking",      f"{len(active)} active")
    col_w.metric("Wins today",    f"{wins_today}",   delta=f"+{wins_today}" if wins_today else None)
    col_l.metric("Stops hit",     f"{losses_today}", delta=f"-{losses_today}" if losses_today else None,
                 delta_color="inverse")

    if not picks:
        st.info("Daily watchlist is empty. Run a scan first.")
        return

    # Build display rows
    rows = []
    for p in picks:
        rows.append({
            "Ticker":      p["ticker"],
            "Sector":      p.get("sector", ""),
            "Rec":         p["recommendation"],
            "Score":       p.get("current_score", p["score"]),
            "Confidence":  p.get("confidence_pct", 0),
            "Entry $":     p.get("entry_price", 0),
            "Now $":       p.get("current_price", 0),
            "P&L %":       p.get("pnl_pct", 0.0),
            "RSI":         p.get("rsi"),
            "Vol":         p.get("volume_ratio"),
            "Status":      p.get("status", "active"),
            "Signals":     ", ".join(s.replace("_", " ") for s in p.get("signals", [])[:3]),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Ticker":     st.column_config.TextColumn(  "Ticker",   help="Stock ticker symbol"),
            "Sector":     st.column_config.TextColumn(  "Sector",   help="Market sector"),
            "Rec":        st.column_config.TextColumn(  "Rec",      help="Buy or Sell recommendation for this pick"),
            "Score":      st.column_config.NumberColumn("Score",    format="%.3f",   help="Current combined score: +1.0 = max bullish, -1.0 = max bearish"),
            "Confidence": st.column_config.NumberColumn("Conf %",   format="%d%%",   help="Algorithm's confidence in the recommendation (0-100%)"),
            "Entry $":    st.column_config.NumberColumn("Entry $",  format="$%.2f",  help="Price when this stock was added to the watchlist today"),
            "Now $":      st.column_config.NumberColumn("Now $",    format="$%.2f",  help="Latest market price"),
            "P&L %":      st.column_config.NumberColumn("P&L %",   format="%+.2f%%",help="Unrealized gain/loss since this pick was added. Target: +5% | Stop: -3%"),
            "RSI":        st.column_config.NumberColumn("RSI",      format="%.0f",   help="Relative Strength Index: <30 oversold, >70 overbought"),
            "Vol":        st.column_config.NumberColumn("Vol x",    format="%.1fx",  help="Volume ratio vs 20-day average"),
            "Status":     st.column_config.TextColumn(  "Status",   help="active = being tracked | target_hit = reached +5% | stop_hit = dropped -3%"),
            "Signals":    st.column_config.TextColumn(  "Signals",  help="Technical signals that triggered this pick (RSI, MA cross, momentum, volume)"),
        },
    )


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_projection_data(tickers: tuple) -> dict:
    """Batch-download 3-month OHLCV for projection charts."""
    if not tickers:
        return {}
    try:
        raw = yf.download(
            list(tickers), period="3mo", interval="1d",
            group_by="ticker", auto_adjust=True, progress=False,
        )
        out = {}
        for t in tickers:
            try:
                hist = raw[t].dropna(how="all") if len(tickers) > 1 else raw
                if hist is not None and len(hist) >= 10:
                    out[t] = hist
            except Exception:
                pass
        return out
    except Exception:
        return {}


def _build_projection_chart(ticker: str, hist: pd.DataFrame, pick: dict) -> go.Figure:
    """
    Candlestick + SMA + forward projection fan for a single conviction pick.
    Shows last 45 days of actual data + 15-day projection cone.
    """
    import numpy as np

    hist = hist.iloc[-45:]          # last 45 trading days
    close  = hist["Close"]
    proj_days = 15

    # SMAs
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(min(50, len(close))).mean()

    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi   = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))

    # ATR (14-day true range)
    high, low = hist["High"], hist["Low"]
    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low  - close.shift()).abs()], axis=1).max(axis=1)
    atr14 = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else float(tr.mean())

    # Projection: linear extrapolation of SMA20 slope + volatility cone
    last_price = float(close.iloc[-1])
    last_sma20 = float(sma20.iloc[-1])
    sma20_5d_ago = float(sma20.iloc[-5]) if len(sma20) >= 5 else last_sma20
    daily_drift  = (last_sma20 - sma20_5d_ago) / 5   # price/day slope

    last_date = hist.index[-1]
    proj_dates = pd.bdate_range(start=last_date, periods=proj_days + 1)[1:]  # business days

    proj_center  = [last_price + daily_drift * i for i in range(1, proj_days + 1)]
    proj_upper   = [c + atr14 * (i ** 0.55) * 1.4 for i, c in enumerate(proj_center, 1)]
    proj_lower   = [c - atr14 * (i ** 0.55) * 1.4 for i, c in enumerate(proj_center, 1)]

    # Key price levels from pick
    rec    = pick.get("recommendation", "Buy")
    entry  = pick.get("entry_price", last_price)
    target = entry * 1.05           # +5% target (win threshold)
    stop   = entry * 0.97           # -3% stop (loss threshold)
    color_main = "#00d4aa" if rec == "Buy" else "#ef5350"

    # ── Build figure ──────────────────────────────────────────────────────────
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.73, 0.27],
        vertical_spacing=0.03,
    )

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        name="OHLC",
        increasing_line_color="#00d4aa", decreasing_line_color="#ef5350",
        increasing_fillcolor="#00d4aa", decreasing_fillcolor="#ef5350",
        showlegend=False,
    ), row=1, col=1)

    # SMA overlays
    for sma, name, color in [(sma20, "SMA 20", "#f39c12"), (sma50, "SMA 50", "#3498db")]:
        fig.add_trace(go.Scatter(
            x=hist.index, y=sma, name=name,
            line=dict(color=color, width=1.4, dash="solid"),
            mode="lines", opacity=0.8,
        ), row=1, col=1)

    # Projection upper/lower fill (cone)
    fig.add_trace(go.Scatter(
        x=list(proj_dates) + list(proj_dates[::-1]),
        y=proj_upper + proj_lower[::-1],
        fill="toself",
        fillcolor="rgba(147,112,219,0.12)",
        line=dict(color="rgba(0,0,0,0)"),
        name="Projection range",
        showlegend=True,
        hoverinfo="skip",
    ), row=1, col=1)

    # Projection center line
    fig.add_trace(go.Scatter(
        x=proj_dates, y=proj_center,
        name="Projected path",
        line=dict(color="#9370db", width=2, dash="dot"),
        mode="lines",
    ), row=1, col=1)

    # Entry price line
    fig.add_hline(y=entry, line_dash="dash", line_color="#f39c12", line_width=1.5,
                  annotation_text=f"Entry ${entry:.2f}",
                  annotation_position="right", annotation_font_color="#f39c12",
                  row=1, col=1)

    # Target line (+5%)
    fig.add_hline(y=target, line_dash="dot", line_color="#00d4aa", line_width=1.5,
                  annotation_text=f"Target +5% ${target:.2f}",
                  annotation_position="right", annotation_font_color="#00d4aa",
                  row=1, col=1)

    # Stop loss line (-3%)
    fig.add_hline(y=stop, line_dash="dot", line_color="#ef5350", line_width=1.5,
                  annotation_text=f"Stop -3% ${stop:.2f}",
                  annotation_position="right", annotation_font_color="#ef5350",
                  row=1, col=1)

    # Target zone shading (entry → target)
    if rec == "Buy":
        fig.add_hrect(y0=entry, y1=target,
                      fillcolor="rgba(0,212,170,0.05)", line_width=0, row=1, col=1)
        fig.add_hrect(y0=stop, y1=entry,
                      fillcolor="rgba(239,83,80,0.05)", line_width=0, row=1, col=1)
    else:
        fig.add_hrect(y0=target, y1=entry,
                      fillcolor="rgba(0,212,170,0.05)", line_width=0, row=1, col=1)
        fig.add_hrect(y0=entry, y1=stop,
                      fillcolor="rgba(239,83,80,0.05)", line_width=0, row=1, col=1)

    # RSI
    fig.add_trace(go.Scatter(
        x=hist.index, y=rsi, name="RSI (14)",
        line=dict(color="#e67e22", width=1.5),
        mode="lines", showlegend=False,
    ), row=2, col=1)
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(231,76,60,0.08)", line_width=0, row=2, col=1)
    fig.add_hrect(y0=0,  y1=30,  fillcolor="rgba(46,204,113,0.08)", line_width=0, row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(231,76,60,0.35)", line_width=1, row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(46,204,113,0.35)", line_width=1, row=2, col=1)

    conf = pick.get("confidence_pct", 0)
    score = pick.get("score", 0)
    fig.update_layout(
        title=dict(
            text=(f"<b>{ticker}</b> — {rec} &nbsp;|&nbsp; Score {score:+.3f} &nbsp;|&nbsp; "
                  f"Confidence {conf}%  &nbsp;"
                  f"<span style='color:{color_main};'>{'▲' if rec=='Buy' else '▼'}</span>"),
            font=dict(size=15, color="#e0e0e0"),
            x=0, pad=dict(l=0),
        ),
        height=500,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,12,18,0.97)",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=120, t=48, b=10),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Price (USD)", row=1, col=1,
                     gridcolor="rgba(255,255,255,0.04)", tickprefix="$", tickfont=dict(size=11))
    fig.update_yaxes(title_text="RSI", row=2, col=1,
                     range=[0, 100], gridcolor="rgba(255,255,255,0.04)", tickfont=dict(size=11))
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.03)", showspikes=True, spikesnap="cursor")

    return fig


def render_projections_section(conviction_picks: list):
    """
    Chart section: candlestick + projection cone for the top conviction picks.
    Shows past 45 days + 15-day forward projection fan.
    """
    if not conviction_picks:
        return

    st.markdown("<div class='section-header'>📈 Price Projections — Top Conviction Picks</div>",
                unsafe_allow_html=True)
    st.caption(
        "Past 45 days of actual price data + 15-day forward projection based on recent momentum and volatility. "
        "The purple cone shows the expected price range. "
        "Green/red zones show the target (+5%) and stop (-3%) levels."
    )

    tickers = tuple(p["ticker"] for p in conviction_picks[:3])
    hist_map = _fetch_projection_data(tickers)

    if not hist_map:
        st.warning("Could not load price data for projections.")
        return

    # One chart per tab (or stacked if only 1-2)
    available = [(t, p) for t, p in zip(tickers, conviction_picks) if t in hist_map]
    if not available:
        return

    if len(available) == 1:
        t, p = available[0]
        fig = _build_projection_chart(t, hist_map[t], p)
        st.plotly_chart(fig, use_container_width=True)
    else:
        tab_labels = [f"{t} {'▲' if p['recommendation']=='Buy' else '▼'}" for t, p in available]
        tabs = st.tabs(tab_labels)
        for tab, (t, p) in zip(tabs, available):
            with tab:
                fig = _build_projection_chart(t, hist_map[t], p)
                st.plotly_chart(fig, use_container_width=True)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Entry",      f"${p.get('entry_price',0):.2f}")
                c2.metric("Target +5%", f"${p.get('entry_price',0)*1.05:.2f}")
                c3.metric("Stop -3%",   f"${p.get('entry_price',0)*0.97:.2f}")
                c4.metric("Score",      f"{p.get('score',0):+.3f}")


def _explosive_potential(r: dict) -> int:
    """
    Score 0-9 indicating likelihood of a large single-day move.
    Returns 0 if the stock doesn't meet the baseline volume requirement.
    """
    vr     = r.get("volume_ratio", 0) or 0
    rsi    = r.get("rsi", 50) or 50
    chg1d  = abs(r.get("change_1d_pct", 0) or 0)
    score  = abs(r.get("score", 0) or 0)
    manip  = r.get("manipulation_flags", [])

    # Must have at least elevated volume to qualify
    if vr < 1.5:
        return 0

    pts = 0
    # Volume score (0-3)
    if vr >= 4.0:   pts += 3
    elif vr >= 2.5: pts += 2
    elif vr >= 1.5: pts += 1

    # RSI at extreme (0-3)
    if rsi <= 22 or rsi >= 78:   pts += 3
    elif rsi <= 28 or rsi >= 72: pts += 2
    elif rsi <= 33 or rsi >= 67: pts += 1

    # Already moving today (0-2)
    if chg1d >= 3.5:   pts += 2
    elif chg1d >= 1.5: pts += 1

    # Strong algo signal (0-1)
    if score >= 0.45: pts += 1

    # Penalize high-severity manipulation flags
    if any(f.get("severity") == "high" for f in manip):
        pts = max(0, pts - 2)

    return pts


def render_explosive_movers(scan_data: dict):
    """
    Table of stocks with high potential for a large single-day move.
    Only rendered when at least one stock clears the threshold (score >= 5).
    """
    all_results = scan_data.get("all_results", [])
    if not all_results:
        return

    THRESHOLD = 5
    candidates = []
    for r in all_results:
        ep = _explosive_potential(r)
        if ep >= THRESHOLD:
            candidates.append({**r, "_ep": ep})

    if not candidates:
        return  # nothing qualifies — table stays hidden

    candidates.sort(key=lambda x: x["_ep"], reverse=True)

    st.markdown(
        "<div class='section-header' style='background:linear-gradient(90deg,#3d100018,transparent);"
        "border-left-color:#ef5350;'>⚡ Explosive Move Candidates</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Stocks showing elevated volume + extreme RSI or strong intraday momentum — "
        "high probability of a large single-day move. Not a guarantee; use with caution."
    )

    rows = []
    for c in candidates:
        ep  = c["_ep"]
        vr  = c.get("volume_ratio", 0) or 0
        rsi = c.get("rsi", 50) or 50
        sig_list = ", ".join(k.replace("_", " ") for k in list(c.get("signals", {}).keys())[:3])
        rows.append({
            "Ticker":    c["ticker"],
            "Sector":    c.get("sector", ""),
            "Rec":       c["recommendation"],
            "Price":     c["current_price"],
            "1d %":      c.get("change_1d_pct", 0),
            "Vol x":     vr,
            "RSI":       rsi,
            "Score":     c.get("score", 0),
            "Potential": ep,
            "Signals":   sig_list,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Ticker":   st.column_config.TextColumn(  "Ticker",    help="Stock symbol"),
            "Sector":   st.column_config.TextColumn(  "Sector"),
            "Rec":      st.column_config.TextColumn(  "Rec",       help="Buy / Sell direction the algo favors"),
            "Price":    st.column_config.NumberColumn("Price",     format="$%.2f"),
            "1d %":     st.column_config.NumberColumn("1d %",      format="%+.1f%%", help="Price change today"),
            "Vol x":    st.column_config.NumberColumn("Vol x",     format="%.1fx",   help="Volume vs 20-day average — >2x means something is happening"),
            "RSI":      st.column_config.NumberColumn("RSI",       format="%.0f",    help="<30 oversold / >70 overbought"),
            "Score":    st.column_config.NumberColumn("Score",     format="%+.3f",   help="Combined algo score"),
            "Potential":st.column_config.ProgressColumn(
                "Explosive Potential", min_value=0, max_value=9, format="%d/9",
                help="Internal score (5-9) — higher = more signals pointing to a big move today",
            ),
            "Signals":  st.column_config.TextColumn(  "Signals",   help="Technical triggers"),
        },
    )
    st.divider()


def build_fg_gauge(score: float, rating: str, color: str) -> go.Figure:
    """Circular gauge (speedometer) for the Fear & Greed Index."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={
            "font": {"size": 36, "color": color, "family": "Inter"},
            "suffix": "",
        },
        gauge={
            "axis": {
                "range": [0, 100],
                "tickvals": [0, 25, 45, 55, 75, 100],
                "ticktext": ["", "Fear", "", "", "Greed", ""],
                "tickfont": {"size": 10, "color": "#4a5580"},
                "tickcolor": "#1a2040",
                "tickwidth": 1,
            },
            "bar": {"color": color, "thickness": 0.22},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": [
                {"range": [0,  25], "color": "rgba(239,83,80,0.09)"},
                {"range": [25, 45], "color": "rgba(243,156,18,0.07)"},
                {"range": [45, 55], "color": "rgba(74,85,128,0.06)"},
                {"range": [55, 75], "color": "rgba(0,212,170,0.06)"},
                {"range": [75, 100],"color": "rgba(0,212,170,0.12)"},
            ],
            "threshold": {
                "line": {"color": color, "width": 3},
                "thickness": 0.85,
                "value": score,
            },
        },
        title={
            "text": f"<b>{rating}</b>",
            "font": {"size": 13, "color": color, "family": "Inter"},
            "align": "center",
        },
        domain={"x": [0, 1], "y": [0, 1]},
    ))
    fig.update_layout(
        height=200,
        margin=dict(l=20, r=20, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter"},
    )
    return fig


def render_home_tab():
    """Home dashboard — overview of everything at a glance."""
    from daily_picks import load_daily_picks

    mkt   = get_market_status()
    fg    = cached_fear_greed()
    picks = load_daily_picks()

    # ── Page title ─────────────────────────────────────────────────────────────
    now_et = mkt.get("now_et")
    now_str = now_et.strftime("%A, %B %d · %I:%M %p ET") if now_et else ""
    status_html = (
        "<span class='market-open'>● NYSE OPEN</span>"
        if mkt["is_open"] else
        f"<span class='market-closed'>○ {mkt['status'].replace('_',' ').upper()}</span>"
    )
    # ── STOCKMANIA logo — centered ─────────────────────────────────────────────
    st.markdown(
        "<div style='text-align:center;padding:6px 0 14px;'>"
        "<span style='"
        "font-size:2.8rem;font-weight:900;letter-spacing:2px;"
        "color:#f5a623;"
        "-webkit-text-stroke:2px #b36c00;"
        "text-shadow:0 3px 0 #7a4d00,0 6px 18px #00000099;"
        "font-family:Impact,Arial Black,sans-serif;"
        "line-height:1;'>STOCKMANIA</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Page header (date + market status) ────────────────────────────────────
    st.markdown(
        f"<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;'>"
        f"<div style='color:#4a5580;font-size:0.82rem;'>{now_str}</div>"
        f"<div>{status_html}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Top row: F&G Gauge + DOW + Quick stats ─────────────────────────────────
    col_fg, col_dow, col_stats = st.columns([2, 2, 3])

    with col_fg:
        fg_score  = fg.get("score", 50)
        fg_rating = fg.get("rating", "Neutral")
        fg_color  = fg.get("color", "#aaa")
        st.markdown(
            f"<div style='background:linear-gradient(145deg,#0d1428,#090d1e);"
            f"border:1px solid #1a2040;border-radius:16px;padding:16px;text-align:center;'>"
            f"<div style='font-size:0.7rem;color:#4a5580;letter-spacing:0.8px;text-transform:uppercase;margin-bottom:4px;'>Fear & Greed Index</div>",
            unsafe_allow_html=True,
        )
        fig_gauge = build_fg_gauge(fg_score, fg_rating, fg_color)
        st.plotly_chart(fig_gauge, use_container_width=True, config={"displayModeBar": False})

        prev  = fg.get("prev_close", fg_score)
        delta = fg_score - prev
        d_col = "#00d4aa" if delta >= 0 else "#ef5350"
        st.markdown(
            f"<div style='text-align:center;margin-top:-12px;'>"
            f"<span style='color:#4a5580;font-size:0.75rem;'>vs ayer: </span>"
            f"<span style='color:{d_col};font-weight:700;font-size:0.82rem;'>{delta:+.1f}</span>"
            f"<span style='color:#4a5580;font-size:0.72rem;'> · {fg.get('source','')[:20]}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_dow:
        # Load DOW context from last scan cache or compute fresh
        try:
            from market_scanner import get_dow_context
            dow = get_dow_context()
        except Exception:
            dow = {}

        dow_name = dow.get("name", "—")
        dow_bias = dow.get("bias", "neutral")
        dow_note = dow.get("note", "")
        dow_adj  = dow.get("adj", 0)
        bc = {"bullish": "#00d4aa", "bearish": "#ef5350", "neutral": "#4f9cf9"}.get(dow_bias, "#aaa")

        bias_note = fg.get("bias", {}).get("note", "")
        sig_cfg   = {
            "contrarian_buy":  ("COMPRAR DIP", "#00d4aa"),
            "caution":         ("SELECTIVO",   "#f39c12"),
            "neutral":         ("NEUTRAL",      "#4f9cf9"),
            "caution_greed":   ("AJUSTAR STOPS","#f39c12"),
            "contrarian_sell": ("REDUCIR EXPO", "#ef5350"),
        }.get(fg.get("bias", {}).get("signal","neutral"), ("NEUTRAL","#4f9cf9"))

        st.markdown(
            f"<div style='background:linear-gradient(145deg,#0d1428,#090d1e);"
            f"border:1px solid #1a2040;border-radius:16px;padding:20px;height:100%;'>"
            f"<div style='font-size:0.7rem;color:#4a5580;letter-spacing:0.8px;text-transform:uppercase;'>Día de semana</div>"
            f"<div style='font-size:1.4rem;font-weight:800;color:{bc};margin:8px 0 4px;'>{dow_name}</div>"
            f"<div style='font-size:0.78rem;color:#6b7399;margin-bottom:14px;'>{dow_note[:70]}...</div>"
            f"<div style='font-size:0.7rem;color:#4a5580;letter-spacing:0.8px;text-transform:uppercase;'>Señal de mercado</div>"
            f"<div style='font-size:1.1rem;font-weight:800;color:{sig_cfg[1]};margin:6px 0 4px;'>{sig_cfg[0]}</div>"
            f"<div style='font-size:0.75rem;color:#6b7399;'>{bias_note[:70]}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_stats:
        today = picks.get("date", "")
        wins_today   = picks.get("wins_today", 0)
        losses_today = picks.get("losses_today", 0)
        conviction   = picks.get("top_5_conviction", [])
        top10        = picks.get("daily_top_10", [])
        active_picks = [p for p in top10 if p.get("status") == "active"]
        closed_picks = picks.get("closed_picks", [])

        avg_pnl = 0.0
        if active_picks:
            avg_pnl = sum(p.get("pnl_pct", 0) for p in active_picks) / len(active_picks)

        r1c1, r1c2 = st.columns(2)
        r2c1, r2c2 = st.columns(2)

        pnl_col = "#00d4aa" if avg_pnl >= 0 else "#ef5350"
        r1c1.markdown(
            f"<div class='stat-card stat-card-blue'>"
            f"<div style='font-size:0.68rem;color:#4a5580;text-transform:uppercase;letter-spacing:0.7px;'>Picks activos</div>"
            f"<div style='font-size:1.8rem;font-weight:900;color:#4f9cf9;margin:6px 0;'>{len(active_picks)}</div>"
            f"<div style='font-size:0.75rem;color:#6b7399;'>de {len(top10)} en watchlist</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        r1c2.markdown(
            f"<div class='stat-card stat-card-green'>"
            f"<div style='font-size:0.68rem;color:#4a5580;text-transform:uppercase;letter-spacing:0.7px;'>P&L promedio</div>"
            f"<div style='font-size:1.8rem;font-weight:900;color:{pnl_col};margin:6px 0;'>{avg_pnl:+.1f}%</div>"
            f"<div style='font-size:0.75rem;color:#6b7399;'>picks activos hoy</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        r2c1.markdown(
            f"<div class='stat-card stat-card-green'>"
            f"<div style='font-size:0.68rem;color:#4a5580;text-transform:uppercase;letter-spacing:0.7px;'>Wins hoy</div>"
            f"<div style='font-size:1.8rem;font-weight:900;color:#00d4aa;margin:6px 0;'>{wins_today}</div>"
            f"<div style='font-size:0.75rem;color:#6b7399;'>picks cerrados ✓</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        r2c2.markdown(
            f"<div class='stat-card stat-card-red'>"
            f"<div style='font-size:0.68rem;color:#4a5580;text-transform:uppercase;letter-spacing:0.7px;'>Stops hit</div>"
            f"<div style='font-size:1.8rem;font-weight:900;color:#ef5350;margin:6px 0;'>{losses_today}</div>"
            f"<div style='font-size:0.75rem;color:#6b7399;'>stops activados hoy</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Top conviction picks preview ───────────────────────────────────────────
    if conviction:
        st.markdown(
            "<div class='section-header'>★ Top Conviction — Vista Rápida</div>",
            unsafe_allow_html=True,
        )
        cols = st.columns(min(len(conviction), 3))
        for col, p in zip(cols, conviction[:3]):
            rec    = p["recommendation"]
            color  = "#00d4aa" if rec == "Buy" else "#ef5350"
            pnl    = p.get("pnl_pct", 0)
            pnlcol = "#00d4aa" if pnl >= 0 else "#ef5350"
            score  = p.get("score", 0)
            status = p.get("status", "active")
            card_cls = "conviction-card" if rec == "Buy" else "conviction-card-sell"
            with col:
                st.markdown(
                    f"<div class='{card_cls} animate-in'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:flex-start;'>"
                    f"<div>"
                    f"<div style='font-size:1.5rem;font-weight:900;color:{color};letter-spacing:1px;'>{p['ticker']}</div>"
                    f"<div style='font-size:0.8rem;color:#4a5580;margin-top:2px;'>{p.get('sector','')}</div>"
                    f"</div>"
                    f"<div style='text-align:right;'>"
                    f"<div style='font-size:0.78rem;background:{color}22;border:1px solid {color}55;color:{color};"
                    f"border-radius:6px;padding:2px 8px;font-weight:700;'>{rec}</div>"
                    f"<div style='color:#4a5580;font-size:0.72rem;margin-top:4px;'>{_status_badge(status)}</div>"
                    f"</div>"
                    f"</div>"
                    f"<div style='margin-top:14px;padding-top:12px;border-top:1px solid #1a2040;'>"
                    f"<div style='font-size:1.2rem;font-weight:700;color:#ccd6f6;'>${p.get('current_price',0):.2f}</div>"
                    f"<div style='font-size:1.0rem;font-weight:800;color:{pnlcol};'>{pnl:+.2f}%</div>"
                    f"<div style='font-size:0.75rem;color:#4a5580;margin-top:6px;'>Score {score:+.3f} · {p.get('confidence_pct',0)}% conf</div>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ── Recent closed picks ────────────────────────────────────────────────────
    closed = picks.get("closed_picks", [])
    if closed:
        st.markdown(
            "<div class='section-header'>Picks cerrados hoy</div>",
            unsafe_allow_html=True,
        )
        for p in closed[-5:]:
            outcome_col = "#00d4aa" if p.get("outcome") == "win" else "#ef5350"
            icon = "✓" if p.get("outcome") == "win" else "✗"
            st.markdown(
                f"<div class='pick-card' style='display:flex;justify-content:space-between;align-items:center;'>"
                f"<div>"
                f"<span style='color:{outcome_col};font-weight:800;font-size:1rem;'>{icon}</span>"
                f" <strong style='color:#ccd6f6;'>{p['ticker']}</strong>"
                f" <span style='color:#4a5580;font-size:0.8rem;'>{p['recommendation']} · Entrada ${p.get('entry_price',0):.2f}</span>"
                f"</div>"
                f"<div style='color:{outcome_col};font-weight:800;font-size:1.0rem;'>{p.get('pnl_pct',0):+.2f}%</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
    elif not conviction:
        st.info("Corre un scan primero para ver los picks del día.")

    st.divider()
    st.caption(f"Data: Yahoo Finance · Google News RSS · CNN Fear & Greed · {now_str}")


def render_scanner_tab():
    mkt = get_market_status()

    # Header — market clock
    col_title, col_clock = st.columns([3, 1])
    with col_title:
        st.header("Market Scanner")
        st.caption(
            f"Scans {sum(len(v) for v in WATCHLIST.values())} tickers across "
            f"{len(WATCHLIST)} sectors · cache refreshes every 15 min"
        )
    with col_clock:
        now_str = mkt["now_et"].strftime("%I:%M %p ET") if mkt.get("now_et") else ""
        if mkt["is_open"]:
            st.markdown(
                f"<div style='text-align:right;padding-top:18px;'>"
                f"<span style='color:#00d4aa;font-size:1.1rem;font-weight:700;'>● OPEN</span><br/>"
                f"<span style='color:#666;font-size:0.8rem;'>{now_str}</span></div>",
                unsafe_allow_html=True,
            )
        else:
            label = {"pre_market": "PRE-MARKET", "post_market": "CLOSED",
                     "weekend": "WEEKEND", "holiday": "HOLIDAY"}.get(mkt["status"], "CLOSED")
            st.markdown(
                f"<div style='text-align:right;padding-top:18px;'>"
                f"<span style='color:#888;font-size:1.1rem;font-weight:700;'>○ {label}</span><br/>"
                f"<span style='color:#555;font-size:0.8rem;'>{now_str}</span></div>",
                unsafe_allow_html=True,
            )

    # Market-closed warning
    if not mkt["is_open"]:
        st.warning(
            f"**{mkt['message']}**  — Recommendations below are for planning. "
            "Execute only when NYSE opens (9:30 AM ET, Mon–Fri).",
            icon="⏰",
        )

    # Scan controls
    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        force_scan = st.button("🔄 Scan Now", type="primary", use_container_width=True,
                               help="Force a fresh scan (ignores 15-min cache)")
    with col_info:
        st.caption("Click **Scan Now** to refresh · scanner runs automatically on first load")

    # Run scan
    with st.spinner("Scanning market… first run may take 30-60 sec"):
        try:
            # Clear cache if force
            if force_scan:
                cached_scan.clear()
            scan_data = cached_scan(force=False)
        except Exception as e:
            st.error(f"Scanner error: {e}")
            return

    if "error" in scan_data:
        st.error(f"Download failed: {scan_data['error']}")
        return

    cached_at = scan_data.get("cached_at", "")[:16].replace("T", " ")
    total = scan_data.get("total_scanned", 0)
    st.caption(f"Last scan: {cached_at} · {total} tickers evaluated")

    # ── Fear & Greed + Day-of-week banner ──────────────────────────────────────
    fg   = cached_fear_greed()
    dow  = scan_data.get("dow_context", {})

    col_fg, col_dow, col_fg2 = st.columns([2, 3, 2])

    with col_fg:
        fg_score  = fg.get("score", 50)
        fg_rating = fg.get("rating", "Neutral")
        fg_color  = fg.get("color", "#aaa")
        fg_prev   = fg.get("prev_close", fg_score)
        fg_delta  = fg_score - fg_prev
        st.markdown(
            f"<div style='background:#0e1117;border:1px solid {fg_color}33;"
            f"border-radius:10px;padding:10px 14px;'>"
            f"<div style='font-size:0.72rem;color:#666;letter-spacing:0.5px;'>FEAR & GREED INDEX</div>"
            f"<div style='font-size:1.6rem;font-weight:900;color:{fg_color};line-height:1.1;'>"
            f"{fg_score:.0f}<span style='font-size:0.9rem;font-weight:400;color:#888;'>/100</span></div>"
            f"<div style='color:{fg_color};font-size:0.85rem;font-weight:700;'>{fg_rating}</div>"
            f"<div style='color:#555;font-size:0.72rem;margin-top:2px;'>vs yesterday: "
            f"<span style='color:{'#00d4aa' if fg_delta >= 0 else '#ef5350'};'>{fg_delta:+.1f}</span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with col_dow:
        if dow:
            dow_name  = dow.get("name", "")
            dow_bias  = dow.get("bias", "neutral")
            dow_note  = dow.get("note", "")
            dow_adj   = dow.get("adj", 0)
            dow_bcol  = {"bullish": "#00d4aa", "bearish": "#ef5350", "neutral": "#f39c12"}.get(dow_bias, "#aaa")
            adj_str   = f"{dow_adj:+.0%}" if dow_adj != 0 else "neutral"
            st.markdown(
                f"<div style='background:#0e1117;border:1px solid {dow_bcol}33;"
                f"border-radius:10px;padding:10px 14px;height:100%;'>"
                f"<div style='font-size:0.72rem;color:#666;letter-spacing:0.5px;'>DAY-OF-WEEK EFFECT</div>"
                f"<div style='font-size:1.2rem;font-weight:900;color:{dow_bcol};'>"
                f"{dow_name} <span style='font-size:0.85rem;'>({adj_str} bias)</span></div>"
                f"<div style='color:#888;font-size:0.78rem;margin-top:3px;'>{dow_note}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    with col_fg2:
        bias      = fg.get("bias", {})
        bias_note = bias.get("note", "")
        bias_sig  = bias.get("signal", "neutral")
        sig_icons = {
            "contrarian_buy":  ("BUY DIP", "#00d4aa"),
            "caution":         ("SELECTIVE", "#f39c12"),
            "neutral":         ("NEUTRAL", "#aaa"),
            "caution_greed":   ("TIGHTEN STOPS", "#f39c12"),
            "contrarian_sell": ("REDUCE EXPOSURE", "#ef5350"),
        }
        sig_label, sig_color = sig_icons.get(bias_sig, ("NEUTRAL", "#aaa"))
        fg_source = fg.get("source", "")
        st.markdown(
            f"<div style='background:#0e1117;border:1px solid {sig_color}33;"
            f"border-radius:10px;padding:10px 14px;'>"
            f"<div style='font-size:0.72rem;color:#666;letter-spacing:0.5px;'>MARKET SIGNAL</div>"
            f"<div style='font-size:1.1rem;font-weight:900;color:{sig_color};'>{sig_label}</div>"
            f"<div style='color:#777;font-size:0.76rem;margin-top:3px;'>{bias_note}</div>"
            f"<div style='color:#444;font-size:0.68rem;margin-top:4px;'>{fg_source}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Daily Picks ────────────────────────────────────────────────────────────
    try:
        picks_data = cached_daily_picks(scan_data.get("cached_at", ""), scan_data)
        mkt_open   = scan_data.get("market_status", {}).get("is_open", False)

        conviction_picks = picks_data.get("top_5_conviction", [])

        # Check earnings for conviction picks
        if conviction_picks:
            conv_tickers = tuple(p["ticker"] for p in conviction_picks)
            earnings_map = fetch_earnings_dates(conv_tickers)
        else:
            earnings_map = {}

        render_conviction_picks(conviction_picks, mkt_open, earnings_map)
        st.divider()

        render_projections_section(conviction_picks)
        st.divider()

        # ── Daily Top 10 watchlist ─────────────────────────────────────────────
        generated_at = picks_data.get("generated_at", "")[:16].replace("T", " ")
        last_upd     = picks_data.get("last_updated", "")[:16].replace("T", " ")
        date_label   = picks_data.get("date", "today")
        st.subheader(f"Daily Watchlist — {date_label}")
        st.caption(
            f"Generated at {generated_at} · Last updated {last_upd} · "
            "Auto-refreshes every 15 min · Learns from wins/losses automatically"
        )
        render_daily_watchlist(
            picks_data.get("daily_top_10", []) + picks_data.get("closed_picks", []),
            mkt_open,
        )

        # Closed/auto-learned picks for today
        closed = picks_data.get("closed_picks", [])
        if closed:
            with st.expander(f"Closed picks today ({len(closed)})"):
                for p in closed:
                    outcome_col = "#00d4aa" if p.get("outcome") == "win" else "#ef5350"
                    st.markdown(
                        f"{_status_badge(p['status'])} &nbsp;"
                        f"**{p['ticker']}** {p['recommendation']} · "
                        f"Entry ${p.get('entry_price',0):.2f} → "
                        f"Exit ${p.get('current_price',0):.2f} · "
                        f"<span style='color:{outcome_col};font-weight:700;'>"
                        f"{p.get('pnl_pct',0):+.2f}%</span> · "
                        f"Signals: {', '.join(p.get('signals',[])[:3])}",
                        unsafe_allow_html=True,
                    )
    except Exception as e:
        st.warning(f"Could not load daily picks: {e}")

    st.divider()

    # ── Explosive move candidates (only shown when algo detects qualifying stocks) ──
    render_explosive_movers(scan_data)

    # ── Today's scanner results (buys / sells) ─────────────────────────────────
    st.subheader("Scanner — All Opportunities Today")

    # Fetch earnings for top buys/sells (non-blocking: empty dict if it fails)
    all_scan_tickers = tuple(
        r["ticker"] for r in scan_data.get("top_buys", [])[:5]
        + scan_data.get("top_sells", [])[:5]
    )
    try:
        scan_earnings = fetch_earnings_dates(all_scan_tickers) if all_scan_tickers else {}
    except Exception:
        scan_earnings = {}

    col_buy, col_sell = st.columns(2)

    with col_buy:
        st.subheader("Top Buys")
        buys = scan_data.get("top_buys", [])
        if not buys:
            st.info("No strong buy signals right now.")
        for r in buys[:5]:
            manip = r.get("manipulation_flags", [])
            has_alert = any(f["severity"] == "high" for f in manip)
            earn = scan_earnings.get(r["ticker"])
            with st.container():
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.markdown(
                        f"**{r['ticker']}** &nbsp; {_rec_badge('Buy')}"
                        + (" &nbsp;⚠" if has_alert else ""),
                        unsafe_allow_html=True,
                    )
                    signals_str = ", ".join(
                        k.replace("_", " ") for k in list(r.get("signals", {}).keys())[:3]
                    )
                    st.caption(f"{r.get('sector','—')} · {signals_str}")
                    if earn:
                        st.markdown(
                            f"<span style='color:#f39c12;font-size:0.78rem;'>"
                            f"⚠ Earnings en {earn['days_away']} día(s) — {earn['date']} · alto riesgo de gap</span>",
                            unsafe_allow_html=True,
                        )
                with c2:
                    st.markdown(
                        f"<div style='text-align:right;'>"
                        f"<div style='color:#00d4aa;font-weight:700;font-size:1.1rem;'>${r['current_price']:.2f}</div>"
                        f"<div style='color:#{'00d4aa' if r['change_1d_pct'] >= 0 else 'ef5350'};font-size:0.85rem;'>"
                        f"{r['change_1d_pct']:+.1f}% today</div>"
                        f"<div style='color:#888;font-size:0.78rem;'>RSI {r['rsi']:.0f} · vol {r['volume_ratio']:.1f}x</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                if has_alert:
                    for f in manip:
                        if f["severity"] == "high":
                            st.markdown(
                                f"<span style='color:#f39c12;font-size:0.78rem;'>⚠ {f['detail']}</span>",
                                unsafe_allow_html=True,
                            )
                _reason_key = f"show_reason_{r['ticker']}"
                if st.button(
                    f"{'▼' if st.session_state.get(_reason_key) else '▶'}  Ver razon de compra",
                    key=f"btn_{_reason_key}",
                    use_container_width=True,
                ):
                    st.session_state[_reason_key] = not st.session_state.get(_reason_key, False)
                if st.session_state.get(_reason_key, False):
                    _render_buy_reason(r)
            st.divider()

    with col_sell:
        st.subheader("Top Sells / Short")
        sells = scan_data.get("top_sells", [])
        if not sells:
            st.info("No strong sell signals right now.")
        for r in sells[:5]:
            manip = r.get("manipulation_flags", [])
            has_alert = any(f["severity"] == "high" for f in manip)
            with st.container():
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.markdown(
                        f"**{r['ticker']}** &nbsp; {_rec_badge('Sell')}"
                        + (" &nbsp;⚠" if has_alert else ""),
                        unsafe_allow_html=True,
                    )
                    signals_str = ", ".join(
                        k.replace("_", " ") for k in list(r.get("signals", {}).keys())[:3]
                    )
                    st.caption(f"{r.get('sector','—')} · {signals_str}")
                with c2:
                    st.markdown(
                        f"<div style='text-align:right;'>"
                        f"<div style='color:#ef5350;font-weight:700;font-size:1.1rem;'>${r['current_price']:.2f}</div>"
                        f"<div style='color:#{'00d4aa' if r['change_1d_pct'] >= 0 else 'ef5350'};font-size:0.85rem;'>"
                        f"{r['change_1d_pct']:+.1f}% today</div>"
                        f"<div style='color:#888;font-size:0.78rem;'>RSI {r['rsi']:.0f} · vol {r['volume_ratio']:.1f}x</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                if has_alert:
                    for f in manip:
                        if f["severity"] == "high":
                            st.markdown(
                                f"<span style='color:#f39c12;font-size:0.78rem;'>⚠ {f['detail']}</span>",
                                unsafe_allow_html=True,
                            )
            st.divider()

    # ── Manipulation alerts ────────────────────────────────────────────────────
    alerts = scan_data.get("manipulation_alerts", [])
    if alerts:
        with st.expander(f"⚠ Manipulation / Anomaly Alerts ({len(alerts)})", expanded=len(alerts) > 0):
            for a in alerts:
                sev_col = {"high": "#ef5350", "medium": "#f39c12", "low": "#aaa"}.get(a["severity"], "#aaa")
                st.markdown(
                    f"{_sev_badge(a['severity'])} &nbsp;"
                    f"<strong>{a['ticker']}</strong> — "
                    f"<span style='color:#ccc;'>{a['detail']}</span>",
                    unsafe_allow_html=True,
                )

    # ── Full results table ─────────────────────────────────────────────────────
    all_results = scan_data.get("all_results", [])
    if all_results:
        with st.expander(f"Full Ranking — All {len(all_results)} tickers"):
            df = pd.DataFrame([{
                "Ticker":      r["ticker"],
                "Sector":      r.get("sector", ""),
                "Rec":         r["recommendation"],
                "Score":       r["score"],
                "RSI":         r["rsi"],
                "Price":       r["current_price"],
                "1d %":        r["change_1d_pct"],
                "5d %":        r["change_5d_pct"],
                "Vol Ratio":   r.get("volume_ratio"),
                "Alerts":      len(r.get("manipulation_flags", [])),
            } for r in all_results])

            st.dataframe(
                df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Ticker":    st.column_config.TextColumn(   "Ticker",  help="Stock ticker symbol (e.g. AAPL, NVDA)"),
                    "Sector":    st.column_config.TextColumn(   "Sector",  help="Market sector this company belongs to"),
                    "Rec":       st.column_config.TextColumn(   "Rec",     help="Buy, Sell, or Wait — based on combined score"),
                    "Score":     st.column_config.NumberColumn( "Score",   format="%.3f",  help="Combined signal score: +1.0 = very bullish, -1.0 = very bearish. |Score| > 0.4 = strong conviction"),
                    "RSI":       st.column_config.NumberColumn( "RSI",     format="%.0f",  help="Relative Strength Index (14-period). <30 = oversold (buy zone), >70 = overbought (sell zone)"),
                    "Price":     st.column_config.NumberColumn( "Price",   format="$%.2f", help="Current market price in USD"),
                    "1d %":      st.column_config.NumberColumn( "1d %",    format="%.1f%%",help="Price change today vs yesterday's close"),
                    "5d %":      st.column_config.NumberColumn( "5d %",    format="%.1f%%",help="Price change over the last 5 trading days (weekly momentum)"),
                    "Vol Ratio": st.column_config.NumberColumn( "Vol x",   format="%.1fx", help="Today's volume vs 20-day average. >2x = elevated activity; >5x = unusual — check for manipulation"),
                    "Alerts":    st.column_config.NumberColumn( "Alerts",  format="%d",    help="Number of manipulation / anomaly flags detected (volume spike, gap, short squeeze, etc.)"),
                },
            )


with tab0:
    render_home_tab()

with tab1:
    render_scanner_tab()

with tab2:
    st.markdown(
        "<div class='section-header' style='margin-top:0;'>📊 Análisis de Acción</div>",
        unsafe_allow_html=True,
    )
    col_inp, col_btn = st.columns([3, 1])
    with col_inp:
        ticker_input = st.text_input(
            "ticker", value=st.session_state.get("last_ticker_input", "AAPL"),
            max_chars=10, placeholder="AAPL · TSLA · NVDA · MSFT...",
            label_visibility="collapsed",
        ).upper().strip()
        st.session_state.last_ticker_input = ticker_input
    with col_btn:
        analyze_btn = st.button("Analizar →", type="primary", use_container_width=True)

    st.divider()

    if "last_ticker" not in st.session_state:
        st.session_state.last_ticker = None

    should_run = analyze_btn or (
        st.session_state.last_ticker == ticker_input and ticker_input is not None
    )

    if not should_run:
        st.markdown(
            "<div style='text-align:center;margin-top:60px;'>"
            "<div style='font-size:3.5rem;'>📊</div>"
            "<div style='font-size:1.2rem;color:#4a5580;margin-top:12px;'>Ingresa un ticker arriba y presiona Analizar</div>"
            "<div style='font-size:0.85rem;color:#2a3a5a;margin-top:8px;'>Ej: AAPL · TSLA · NVDA · MSFT · AMZN</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.session_state.last_ticker = ticker_input
        with st.spinner(f"Analizando {ticker_input}... puede tomar ~20 seg la primera vez"):
            try:
                data     = cached_run_analysis(ticker_input)
                df_price = cached_price_history(ticker_input)
            except SystemExit:
                st.error(f"Ticker '{ticker_input}' no encontrado. Verifica el símbolo.")
                st.stop()
            except Exception as e:
                st.error(f"Error en análisis: {e}")
                st.stop()

        render_header(ticker_input, data["overview"], data["decision"])
        st.divider()

        desc = data["overview"].get("description", "")
        if desc and desc != "No description available.":
            with st.expander("Descripción de la empresa", expanded=False):
                st.write(desc)

        if not df_price.empty:
            st.plotly_chart(build_chart(df_price, data["technicals"]),
                            use_container_width=True)
        else:
            st.warning("Historial de precios no disponible.")

        st.divider()
        st.subheader("Scores por módulo")
        render_score_cards(data)
        st.divider()

        col_tech, col_news = st.columns([1, 1])
        with col_tech:
            st.subheader("Indicadores Técnicos")
            render_technicals_table(data["technicals"])
        with col_news:
            st.subheader("Noticias y Sentimiento")
            render_news(data["news"])

        st.divider()
        st.subheader("Riesgo y Oportunidad")
        render_risk_opportunity(data["risks"], data["opportunities"])
        st.divider()

        st.subheader("Veredicto Final")
        render_verdict(data["decision"])

        key_events = data["decision"].get("key_events", [])
        if key_events:
            st.markdown("**Eventos detectados:** " +
                        "  ".join(f"`{e}`" for e in key_events))

        st.divider()
        st.caption(
            f"Cache 5 min · Último análisis: {data['decision'].get('run_date','N/A')} · "
            f"Yahoo Finance + Google News RSS"
        )

with tab3:
    render_trades_tab()

with tab4:
    render_learning_tab()
