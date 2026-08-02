"""
Historical data ingestion via yfinance.

This module is deliberately separate from live data (Fyers) — historical
loading is a batch/offline concern, live data is a streaming/online concern.
Keeping them apart means the feature engineering code (features/build_features.py)
can be reused identically for both, as long as both loaders return the same
schema.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config.settings import DATA

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns Title-case columns; normalize to lowercase for the
    rest of the pipeline so it doesn't matter whether data came from
    yfinance or Fyers."""
    df = df.rename(columns={c: c.lower() for c in df.columns})
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Downloaded data missing required columns: {missing}")
    df.index.name = "timestamp"
    return df[REQUIRED_COLUMNS]


def fetch_historical(symbol: str, period: str | None = None, interval: str | None = None) -> pd.DataFrame:
    """Fetch historical OHLCV for a single symbol via yfinance.

    NOTE: yfinance intraday intervals (e.g. 15m) are only available for the
    last ~60 days from Yahoo. For a true 3-year *intraday* dataset you will
    need a paid/broker data source (Fyers historical API covers this) —
    yfinance's 3y depth is reliable at daily interval only. Plan accordingly:
    use yfinance daily data for the initial model, and backfill intraday
    history from Fyers once you have API access, rather than assuming
    yfinance gives you 3 years of 15m candles (it will silently truncate).
    """
    import yfinance as yf  # imported lazily so this module can be tested without the dep

    period = period or DATA.history_period
    interval = interval or DATA.interval

    logger.info("Fetching %s | period=%s interval=%s", symbol, period, interval)
    raw = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
    if raw.empty:
        raise RuntimeError(f"No data returned for {symbol}")

    # yfinance sometimes returns MultiIndex columns for single-symbol downloads
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    return _standardize_columns(raw)


def fetch_and_cache(symbol: str) -> Path:
    """Fetch + write raw parquet to disk, keyed by symbol. Idempotent."""
    DATA.raw_data_dir.mkdir(parents=True, exist_ok=True)
    df = fetch_historical(symbol)
    out_path = DATA.raw_data_dir / f"{symbol.replace('^', 'IDX_')}.parquet"
    df.to_parquet(out_path)
    logger.info("Cached %d rows -> %s", len(df), out_path)
    return out_path


def load_all_symbols() -> dict[str, pd.DataFrame]:
    """Fetch (or refresh) historical data for every configured symbol."""
    result = {}
    for symbol in DATA.symbols:
        path = fetch_and_cache(symbol)
        result[symbol] = pd.read_parquet(path)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = load_all_symbols()
    for sym, df in data.items():
        print(sym, df.shape, df.index.min(), "->", df.index.max())