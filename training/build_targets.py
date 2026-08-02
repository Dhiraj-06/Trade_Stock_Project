"""
Phase 2 — Target construction.

Builds the labels for the two-model architecture:
  1. `target_return_pct`   -> regression target (next-day % return)
  2. `target_up`           -> classification target (1 if up, 0 if down)

Everything else (predicted price, volatility, confidence, trend bucket,
BUY/HOLD/SELL) is DERIVED from these two model outputs in the Decision
Engine (inference/decision_engine.py, Phase 4) — not predicted directly.

NOTE: this assumes your existing spreadsheet already has Open/High/Low/Close
and your engineered indicator columns (SMA/EMA/RSI/MACD/ATR/etc). This script
only adds the target columns; it doesn't rebuild your existing features.
Once you upload your actual file I'll adjust column names to match exactly —
the ones below (Close, Ticker, Date) are my best guess from your screenshot.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_targets(
    df: pd.DataFrame,
    close_col: str = "Close",
    horizon: int = 1,          # 1 = next day, per your confirmation
) -> pd.DataFrame:
    """Adds target_return_pct and target_up. Must be run PER TICKER
    (never across a concatenated multi-ticker df) or you'll leak the
    last row of ticker A's future into ticker B's label."""
    df = df.copy()

    future_close = df[close_col].shift(-horizon)
    df["target_return_pct"] = (future_close - df[close_col]) / df[close_col] * 100
    df["target_up"] = (df["target_return_pct"] > 0).astype(int)

    # Trailing `horizon` rows have no future data -> drop them, don't fill.
    df = df.iloc[:-horizon] if horizon > 0 else df
    return df


def build_targets_per_ticker(df: pd.DataFrame, ticker_col: str = "Ticker",
                              close_col: str = "Close", horizon: int = 1) -> pd.DataFrame:
    """Safe version for a multi-ticker concatenated dataframe (like your
    screenshot, which had a Ticker column).

    NOTE: pandas' groupby().apply() can silently drop the grouping column
    from the result in some versions -- a nasty, quiet bug if unnoticed
    (you'd lose the Ticker column and never know which row belongs to which
    stock). We avoid groupby().apply() entirely and loop explicitly instead,
    which is slightly more verbose but impossible to get subtly wrong."""
    labeled_frames = []
    for ticker, group in df.groupby(ticker_col, sort=False):
        labeled = build_targets(group, close_col=close_col, horizon=horizon)
        labeled[ticker_col] = ticker  # re-assert explicitly, don't rely on groupby to preserve it
        labeled_frames.append(labeled)
    return pd.concat(labeled_frames, ignore_index=False).sort_index()


if __name__ == "__main__":
    # Smoke test with synthetic multi-ticker data
    rng = pd.date_range("2023-01-01", periods=300, freq="D")
    frames = []
    for ticker in ["WIPRO", "ADANIENT"]:
        price = 175 + np.cumsum(np.random.randn(300))
        frames.append(pd.DataFrame({"Ticker": ticker, "Date": rng, "Close": price}))
    raw = pd.concat(frames, ignore_index=True)

    labeled = build_targets_per_ticker(raw)
    print(labeled.groupby("Ticker")["target_up"].value_counts())
    print(labeled[["Ticker", "Date", "Close", "target_return_pct", "target_up"]].tail(8))