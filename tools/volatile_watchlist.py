"""
volatile_watchlist.py — Curated universe of volatile/high-beta tickers.

These are stocks known for large intraday/multiday moves driven by news
catalysts, short squeezes, earnings surprises, or sector momentum.
Updated manually as needed.
"""

# ── Volatile ticker universe (~85 tickers) ─────────────────────────────────────

VOLATILE_TICKERS = [
    # Biotech / Pharma small-cap (FDA catalysts, clinical data, partnerships)
    "SAVA", "NVAX", "OCGN", "ACAD", "ARCT", "VXRT", "INO", "SRPT",
    "AGEN", "CRSP", "BEAM", "EDIT", "NTLA", "FATE", "IMVT", "DVAX",
    "SPRO", "IDYA", "KRYS", "URGN", "TPIC", "PRGO",

    # Small-cap tech / fintech / AI (earnings, partnerships, product launches)
    "RBLX", "HOOD", "SOFI", "AFRM", "UPST", "IONQ", "QBTS", "RGTI",
    "ARRY", "SPCE", "DM", "GFAI", "LIDR", "BFRG",

    # EV / clean energy small-cap (policy news, production updates)
    "RIVN", "LCID", "NKLA", "GOEV", "WKHS", "CHPT", "BLNK", "SOLO",
    "AYRO", "ZEV", "FFIE", "MULN",

    # Aerospace / defense small-cap (contracts, launches, partnerships)
    "RKLB", "ASTR", "ASTS", "LUNR", "LLAP", "ASTC", "MNTS", "BKSY",

    # Crypto-adjacent (BTC price correlation, mining news)
    "MSTR", "MARA", "RIOT", "CLSK", "HUT", "BTBT", "CIFR", "CORZ", "IREN",

    # High-short-interest / momentum (squeeze potential)
    "GME", "AMC", "KOSS", "SKLZ", "FUBO", "LMND", "PRPL", "NNDM",
    "FCEL", "PSFE", "PROG",

    # Speculative / high-beta large movers
    "PLTR", "CLOV", "SOFI", "OPEN", "BARK", "VZIO", "HYLN",
]

# Deduplicate while preserving order
_seen = set()
VOLATILE_TICKERS = [t for t in VOLATILE_TICKERS if not (_seen.add(t) or t in _seen)]

# ── Sector map (for display and coverage tracking) ─────────────────────────────

VOLATILE_SECTOR = {
    "SAVA": "Biotech", "NVAX": "Biotech", "OCGN": "Biotech", "ACAD": "Biotech",
    "ARCT": "Biotech", "VXRT": "Biotech", "INO": "Biotech", "SRPT": "Biotech",
    "AGEN": "Biotech", "CRSP": "Biotech", "BEAM": "Biotech", "EDIT": "Biotech",
    "NTLA": "Biotech", "FATE": "Biotech", "IMVT": "Biotech", "DVAX": "Biotech",
    "SPRO": "Biotech", "IDYA": "Biotech", "KRYS": "Biotech", "URGN": "Biotech",
    "TPIC": "Biotech", "PRGO": "Pharma",
    "RBLX": "Tech", "HOOD": "Fintech", "SOFI": "Fintech", "AFRM": "Fintech",
    "UPST": "Fintech", "IONQ": "Quantum", "QBTS": "Quantum", "RGTI": "Quantum",
    "ARRY": "Solar", "SPCE": "Aerospace", "DM": "3D Print", "GFAI": "AI",
    "LIDR": "LiDAR", "BFRG": "Biotech",
    "RIVN": "EV", "LCID": "EV", "NKLA": "EV", "GOEV": "EV", "WKHS": "EV",
    "CHPT": "EV Charging", "BLNK": "EV Charging", "SOLO": "EV",
    "AYRO": "EV", "ZEV": "EV", "FFIE": "EV", "MULN": "EV",
    "RKLB": "Aerospace", "ASTR": "Aerospace", "ASTS": "Aerospace",
    "LUNR": "Aerospace", "LLAP": "Aerospace", "ASTC": "Aerospace",
    "MNTS": "Aerospace", "BKSY": "Satellite",
    "MSTR": "Crypto", "MARA": "Crypto Mining", "RIOT": "Crypto Mining",
    "CLSK": "Crypto Mining", "HUT": "Crypto Mining", "BTBT": "Crypto Mining",
    "CIFR": "Crypto Mining", "CORZ": "Crypto Mining", "IREN": "Crypto Mining",
    "GME": "Retail", "AMC": "Entertainment", "KOSS": "Consumer",
    "SKLZ": "Gaming", "FUBO": "Streaming", "LMND": "Insurtech",
    "PRPL": "Consumer", "NNDM": "3D Print", "FCEL": "Fuel Cell",
    "PSFE": "Fintech", "PROG": "Biotech",
    "PLTR": "AI/Data", "CLOV": "Insurtech", "OPEN": "Proptech",
    "BARK": "Pet", "VZIO": "Consumer Tech", "HYLN": "EV",
}
