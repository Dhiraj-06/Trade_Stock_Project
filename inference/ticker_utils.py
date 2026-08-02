"""
NIFTY 50 Ticker Validation & Alias Resolution Utility.

Ensures only valid NIFTY 50 constituents are processed by the ML service,
and resolves user input variations (e.g. "Tata Steel" -> "TATASTEEL", "Infosys" -> "INFY").
"""
from __future__ import annotations

NIFTY50_TICKERS = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJAJFINSV", "BAJFINANCE", "BEL", "BHARTIARTL", "BPCL", "BRITANNIA", "CIPLA",
    "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI",
    "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
    "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATASTEEL", "TCS", "TECHM", "TITAN",
    "ULTRACEMCO", "WIPRO"
}

# Alias mapping for user inputs
ALIAS_MAP = {
    "TATA STEEL": "TATASTEEL",
    "TATASTEEL": "TATASTEEL",
    "BAJAJ AUTO": "BAJAJ-AUTO",
    "BAJAJ-AUTO": "BAJAJ-AUTO",
    "BAJAJ FINANCE": "BAJFINANCE",
    "BAJ FINANCE": "BAJFINANCE",
    "BAJAJ FINSERV": "BAJAJFINSV",
    "BHARAT ELECTRONICS": "BEL",
    "BHARAT PETROLEUM": "BPCL",
    "AIRTEL": "BHARTIARTL",
    "BHARTI AIRTEL": "BHARTIARTL",
    "COAL INDIA": "COALINDIA",
    "DR REDDY": "DRREDDY",
    "DR REDDYS": "DRREDDY",
    "DR. REDDY": "DRREDDY",
    "EICHER MOTORS": "EICHERMOT",
    "EICHER": "EICHERMOT",
    "HCL TECH": "HCLTECH",
    "HCL TECHNOLOGIES": "HCLTECH",
    "HDFC BANK": "HDFCBANK",
    "HDFC LIFE": "HDFCLIFE",
    "HERO MOTOCORP": "HEROMOTOCO",
    "HERO HONDA": "HEROMOTOCO",
    "HINDUSTAN UNILEVER": "HINDUNILVR",
    "HUL": "HINDUNILVR",
    "ICICI BANK": "ICICIBANK",
    "INDUSIND BANK": "INDUSINDBK",
    "INFOSYS": "INFY",
    "INFY": "INFY",
    "JIO FINANCIAL": "JIOFIN",
    "JIOFIN": "JIOFIN",
    "JSW STEEL": "JSWSTEEL",
    "KOTAK BANK": "KOTAKBANK",
    "KOTAK MAHINDRA BANK": "KOTAKBANK",
    "LARSEN & TOUBRO": "LT",
    "LARSEN AND TOUBRO": "LT",
    "L&T": "LT",
    "LT": "LT",
    "MAHINDRA & MAHINDRA": "M&M",
    "MAHINDRA AND MAHINDRA": "M&M",
    "M&M": "M&M",
    "MARUTI SUZUKI": "MARUTI",
    "MARUTI": "MARUTI",
    "NESTLE INDIA": "NESTLEIND",
    "NESTLE": "NESTLEIND",
    "POWER GRID": "POWERGRID",
    "POWERGRID": "POWERGRID",
    "RELIANCE INDUSTRIES": "RELIANCE",
    "RIL": "RELIANCE",
    "SBI": "SBIN",
    "STATE BANK OF INDIA": "SBIN",
    "SBI LIFE": "SBILIFE",
    "SHRIRAM FINANCE": "SHRIRAMFIN",
    "SUN PHARMA": "SUNPHARMA",
    "SUN PHARMACEUTICALS": "SUNPHARMA",
    "TATA CONSUMER": "TATACONSUM",
    "TATA CONSUMER PRODUCTS": "TATACONSUM",
    "TATA MOTORS": "TATAMOTORS",
    "TECH MAHINDRA": "TECHM",
    "TECH M": "TECHM",
    "ULTRATECH CEMENT": "ULTRACEMCO",
    "ULTRA TECH CEMENT": "ULTRACEMCO",
    "WIPRO": "WIPRO",
    "APOLLO HOSPITALS": "APOLLOHOSP",
    "ASIAN PAINTS": "ASIANPAINT",
    "AXIS BANK": "AXISBANK",
}


def normalize_and_validate_ticker(ticker_input: str) -> str:
    """Normalizes ticker string and validates against the NIFTY 50 universe.

    Raises ValueError if ticker is not in NIFTY 50 universe.
    """
    if not ticker_input or not isinstance(ticker_input, str):
        raise ValueError("Ticker must be a non-empty string.")

    cleaned = ticker_input.strip().upper()
    cleaned = cleaned.replace("NSE:", "").replace("-EQ", "").strip()

    # 1. Direct match in canonical universe
    if cleaned in NIFTY50_TICKERS:
        return cleaned

    # 2. Match in alias map
    if cleaned in ALIAS_MAP:
        resolved = ALIAS_MAP[cleaned]
        if resolved in NIFTY50_TICKERS:
            return resolved

    # 3. Try removing spaces (e.g. "TATA STEEL" -> "TATASTEEL")
    no_spaces = cleaned.replace(" ", "")
    if no_spaces in NIFTY50_TICKERS:
        return no_spaces

    # 4. If not found in NIFTY 50 universe, raise explicit error
    sorted_universe = sorted(list(NIFTY50_TICKERS))
    raise ValueError(
        f"'{ticker_input}' is not a constituent of the NIFTY 50 universe. "
        f"The ML model is trained exclusively on NIFTY 50 stocks.\n"
        f"Supported NIFTY 50 tickers are: {', '.join(sorted_universe)}"
    )
