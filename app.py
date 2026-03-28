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

# ── Page config (must be the FIRST Streamlit call) ────────────────────────────
st.set_page_config(
    page_title="Stock Analyzer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .verdict-buy  { background:#0d3d2e; border:1px solid #00d4aa;
                  border-radius:8px; padding:16px; text-align:center; }
  .verdict-sell { background:#3d0d0d; border:1px solid #ef5350;
                  border-radius:8px; padding:16px; text-align:center; }
  .verdict-wait { background:#3d2d00; border:1px solid #f39c12;
                  border-radius:8px; padding:16px; text-align:center; }
  .big-rec { font-size:2.4rem; font-weight:900; letter-spacing:2px; }
  div[data-testid="stMetricValue"] { font-size:1.2rem; }
</style>
""", unsafe_allow_html=True)


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
    st.dataframe(df, hide_index=True, use_container_width=True, height=530)


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
            "pnl_pct":       st.column_config.NumberColumn("P&L %",      format="%.2f%%"),
            "entry_price":   st.column_config.NumberColumn("Entry $",     format="$%.2f"),
            "exit_price":    st.column_config.NumberColumn("Exit $",      format="$%.2f"),
            "confidence_pct":st.column_config.NumberColumn("Confidence",  format="%d%%"),
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
                "Weight": st.column_config.ProgressColumn(
                    "Weight", min_value=0.2, max_value=2.0, format="%.3f"
                )
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
    st.markdown("## 📈 Stock Analyzer")
    st.divider()

    ticker_input = st.text_input(
        "Ticker Symbol", value="AAPL", max_chars=10,
        placeholder="e.g. AAPL, TSLA, NVDA"
    ).upper().strip()

    analyze_btn = st.button("Analyze", type="primary", use_container_width=True)

    st.divider()
    auto_refresh = st.toggle("Auto-refresh (5 min)", value=False)
    if auto_refresh:
        import time
        time.sleep(300)
        st.rerun()

    st.divider()
    st.caption("**Data sources**")
    st.caption("- Yahoo Finance (yfinance)")
    st.caption("- Google News RSS")
    st.caption("- VADER sentiment")
    st.divider()
    st.caption("No API keys required · 100% free")


# ── Main layout ────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["Analysis", "My Trades", "Learning System"])

with tab1:
    # Keep last analyzed ticker in session state for page refreshes
    if "last_ticker" not in st.session_state:
        st.session_state.last_ticker = None

    should_run = analyze_btn or (
        st.session_state.last_ticker == ticker_input and
        ticker_input is not None
    )

    if not should_run:
        st.markdown(
            "<div style='text-align:center; margin-top:80px; color:#555;'>"
            "<div style='font-size:4rem;'>📈</div>"
            "<div style='font-size:1.3rem; margin-top:12px;'>Enter a ticker and click Analyze</div>"
            "<div style='font-size:0.9rem; margin-top:8px;'>e.g. AAPL · TSLA · NVDA · MSFT · AMZN</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.session_state.last_ticker = ticker_input

        with st.spinner(f"Analyzing {ticker_input}... this may take ~20 seconds on first run"):
            try:
                data     = cached_run_analysis(ticker_input)
                df_price = cached_price_history(ticker_input)
            except SystemExit:
                st.error(f"Ticker '{ticker_input}' not found. Check the symbol and try again.")
                st.stop()
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                st.stop()

        # ── Header ────────────────────────────────────────────────────────────
        render_header(ticker_input, data["overview"], data["decision"])
        st.divider()

        # ── Description ───────────────────────────────────────────────────────
        desc = data["overview"].get("description", "")
        if desc and desc != "No description available.":
            with st.expander("Company Description", expanded=False):
                st.write(desc)

        # ── Chart ─────────────────────────────────────────────────────────────
        if not df_price.empty:
            st.plotly_chart(build_chart(df_price, data["technicals"]),
                            use_container_width=True)
        else:
            st.warning("Price history unavailable.")

        st.divider()

        # ── Score cards ───────────────────────────────────────────────────────
        st.subheader("Module Scores")
        render_score_cards(data)
        st.divider()

        # ── Technicals + News side by side ────────────────────────────────────
        col_tech, col_news = st.columns([1, 1])
        with col_tech:
            st.subheader("Technical Indicators")
            render_technicals_table(data["technicals"])
        with col_news:
            st.subheader("News & Sentiment")
            render_news(data["news"])

        st.divider()

        # ── Risk & Opportunity ────────────────────────────────────────────────
        st.subheader("Risk & Opportunity")
        render_risk_opportunity(data["risks"], data["opportunities"])
        st.divider()

        # ── Final Verdict ─────────────────────────────────────────────────────
        st.subheader("Final Verdict")
        render_verdict(data["decision"])

        # ── Key Events ────────────────────────────────────────────────────────
        key_events = data["decision"].get("key_events", [])
        if key_events:
            st.markdown("**Detected Market Events:** " +
                        "  ".join(f"`{e}`" for e in key_events))

        st.divider()
        st.caption(
            f"Analysis cached for 5 minutes · Last run: {data['decision'].get('run_date','N/A')} · "
            f"Data: Yahoo Finance + Google News RSS"
        )

with tab2:
    render_trades_tab()

with tab3:
    render_learning_tab()
