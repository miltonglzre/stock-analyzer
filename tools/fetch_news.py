"""
fetch_news.py — Fetch recent news and score sentiment with VADER.

Sources (in order of preference):
  1. yfinance ticker.news (fast, no key needed)
  2. Google News RSS via feedparser (broader coverage, no key needed)

Output: .tmp/{TICKER}_news.json

Usage:
    python tools/fetch_news.py AAPL
"""

import sys
import time
import requests
import feedparser
import yfinance as yf
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json, get_int

# VADER — download lexicon on first run if missing
try:
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    _sia = SentimentIntensityAnalyzer()
except LookupError:
    import nltk
    nltk.download("vader_lexicon", quiet=True)
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    _sia = SentimentIntensityAnalyzer()


# ── Key event detection ───────────────────────────────────────────────────────

_EVENT_KEYWORDS = {
    "earnings_beat":    ["beat", "beats", "exceeded", "surpassed", "top estimates"],
    "earnings_miss":    ["miss", "misses", "missed", "below estimates", "disappoints"],
    "acquisition":      ["acquires", "acquisition", "merger", "buyout", "takeover"],
    "lawsuit":          ["lawsuit", "sued", "litigation", "settlement", "sec probe"],
    "layoffs":          ["layoffs", "lay off", "cuts jobs", "workforce reduction"],
    "product_launch":   ["launches", "unveils", "new product", "release", "debut"],
    "guidance_raise":   ["raises guidance", "raised guidance", "outlook raised"],
    "guidance_cut":     ["cuts guidance", "lowers guidance", "outlook cut", "warns"],
    "insider_buy":      ["insider buy", "insiders buy", "executive buys"],
    "insider_sell":     ["insider sell", "insiders sell", "executive sells"],
    "analyst_upgrade":  ["upgrade", "upgraded", "overweight", "buy rating"],
    "analyst_downgrade":["downgrade", "downgraded", "underweight", "sell rating"],
}


def _detect_events(text: str) -> list[str]:
    text_lower = text.lower()
    events = []
    for event, keywords in _EVENT_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            events.append(event)
    return events


# ── VADER scoring ─────────────────────────────────────────────────────────────

def _score_text(text: str) -> float:
    """Return compound VADER score: -1.0 (very negative) to +1.0 (very positive)."""
    if not text or not text.strip():
        return 0.0
    return _sia.polarity_scores(text)["compound"]


# ── Fetchers ──────────────────────────────────────────────────────────────────

def _fetch_yfinance_news(ticker: str, max_items: int) -> list[dict]:
    try:
        t = yf.Ticker(ticker)
        raw = t.news or []
        items = []
        for article in raw[:max_items]:
            title = article.get("title", "")
            summary = article.get("summary", "") or ""
            pub_ts = article.get("providerPublishTime", 0)
            pub_date = datetime.fromtimestamp(pub_ts, tz=timezone.utc).strftime("%Y-%m-%d") if pub_ts else "unknown"
            combined = f"{title}. {summary}"
            score = _score_text(combined)
            items.append({
                "source":    article.get("publisher", "Yahoo Finance"),
                "title":     title,
                "summary":   summary[:300] if summary else "",
                "url":       article.get("link", ""),
                "date":      pub_date,
                "vader_score": round(score, 4),
                "events":    _detect_events(combined),
            })
        return items
    except Exception as e:
        print(f"[WARN] yfinance news failed: {e}")
        return []


def _fetch_google_rss_news(ticker: str, company_name: str, max_items: int) -> list[dict]:
    try:
        query = f"{ticker} stock {company_name}".replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "")
            summary = entry.get("summary", "") or ""
            pub = entry.get("published", "")
            try:
                # feedparser returns a time.struct_time in entry.published_parsed
                if entry.get("published_parsed"):
                    pub_date = datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")
                else:
                    pub_date = pub[:10] if len(pub) >= 10 else "unknown"
            except Exception:
                pub_date = "unknown"

            combined = f"{title}. {summary}"
            score = _score_text(combined)
            items.append({
                "source":    entry.get("source", {}).get("title", "Google News"),
                "title":     title,
                "summary":   "",
                "url":       entry.get("link", ""),
                "date":      pub_date,
                "vader_score": round(score, 4),
                "events":    _detect_events(combined),
            })
        return items
    except Exception as e:
        print(f"[WARN] Google RSS news failed: {e}")
        return []


# ── Aggregate sentiment ────────────────────────────────────────────────────────

def _aggregate_sentiment(items: list[dict]) -> tuple[str, float]:
    """
    Return (label, score) where:
      label  = 'Bullish' | 'Neutral' | 'Bearish'
      score  = -1.0 to +1.0
    """
    if not items:
        return ("Neutral", 0.0)
    scores = [i["vader_score"] for i in items]
    avg = sum(scores) / len(scores)
    avg = round(avg, 4)
    if avg >= 0.05:
        label = "Bullish"
    elif avg <= -0.05:
        label = "Bearish"
    else:
        label = "Neutral"
    return (label, avg)


def _all_events(items: list[dict]) -> list[str]:
    """Deduplicated list of all detected events across all articles."""
    seen = set()
    result = []
    for item in items:
        for e in item.get("events", []):
            if e not in seen:
                seen.add(e)
                result.append(e)
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_news(ticker: str, company_name: str = "") -> dict:
    max_items = get_int("MAX_NEWS_ITEMS", 20)

    print(f"  Fetching news from yfinance...")
    yf_items = _fetch_yfinance_news(ticker, max_items)

    remaining = max(0, max_items - len(yf_items))
    rss_items = []
    if remaining > 0:
        print(f"  Fetching news from Google RSS (up to {remaining} more)...")
        rss_items = _fetch_google_rss_news(ticker, company_name, remaining)

    # Deduplicate by title
    seen_titles = {i["title"].lower() for i in yf_items}
    for item in rss_items:
        if item["title"].lower() not in seen_titles:
            yf_items.append(item)
            seen_titles.add(item["title"].lower())

    all_items = yf_items[:max_items]
    sentiment_label, sentiment_score = _aggregate_sentiment(all_items)
    key_events = _all_events(all_items)

    # Top 3 most positive and top 3 most negative headlines
    sorted_items = sorted(all_items, key=lambda x: x["vader_score"], reverse=True)
    top_positive = [i["title"] for i in sorted_items[:3] if i["vader_score"] > 0]
    top_negative = [i["title"] for i in sorted_items[-3:] if i["vader_score"] < 0]
    top_negative.reverse()

    data = {
        "ticker":           ticker.upper(),
        "total_articles":   len(all_items),
        "sentiment":        sentiment_label,
        "sentiment_score":  sentiment_score,
        "key_events":       key_events,
        "top_positive_headlines": top_positive,
        "top_negative_headlines": top_negative,
        "articles":         all_items,
    }

    path = tmp_path(ticker, "news")
    save_json(path, data)
    print(f"[OK] News ({sentiment_label}, score={sentiment_score:.3f}, {len(all_items)} articles) saved -> {path}")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_news.py <TICKER>")
        sys.exit(1)
    fetch_news(sys.argv[1].upper())
