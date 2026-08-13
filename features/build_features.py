"""
Scale-invariant feature engineering pipeline.
Single source of truth used for BOTH historical training and live Fyers inference.

Guarantees:
1. Per-ticker grouping: rolling windows never cross ticker boundaries.
2. Scale-invariance: all features are ratios, percentage differences, or bounded oscillators.
   No raw price-scale or volume-scale columns leak into the feature matrix.
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from config.settings import FEATURES
from features import technical_indicators as ti

logger = logging.getLogger(__name__)

# List of raw or non-scale-invariant columns that must not be used as training features
EXCLUDED_PRICE_COLUMNS = {
    "open", "high", "low", "close", "adj close", "volume",
    "ema_short", "ema_long", "bb_upper", "bb_mid", "bb_lower",
    "macd", "macd_signal", "macd_hist", "atr", "vwap", "obv",
    "52w_high", "52w_low", "ticker", "date", "timestamp",
    "future_return_pct", "label", "target_return_pct", "target_up",
}


def _build_features_single_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """Builds technical, return, volatility, lag, and calendar features for a single ticker's OHLCV series."""
    df = df.copy()

    # Standardize lowercase column lookup
    c_col = "close" if "close" in df.columns else ("adj close" if "adj close" in df.columns else "Close")
    o_col = "open" if "open" in df.columns else "Open"
    h_col = "high" if "high" in df.columns else "High"
    l_col = "low" if "low" in df.columns else "Low"
    v_col = "volume" if "volume" in df.columns else "Volume"

    close = df[c_col]
    open_p = df[o_col]
    high = df[h_col]
    low = df[l_col]
    volume = df[v_col].astype(float)

    # 1. Bounded Oscillators & Indicators
    df["rsi"] = ti.rsi(close, FEATURES.rsi_period)
    df["adx"] = ti.adx(high, low, close, FEATURES.adx_period)
    df["cci"] = ti.cci(high, low, close)

    stoch_df = ti.stochastic_oscillator(high, low, close)
    df["stoch_k"] = stoch_df["stoch_k"]
    df["stoch_d"] = stoch_df["stoch_d"]

    # 2. Normalized Technical Ratios (Scale-Invariant)
    ema_s = ti.ema(close, FEATURES.ema_short)
    ema_l = ti.ema(close, FEATURES.ema_long)
    df["ema_short_ratio"] = (ema_s - close) / close
    df["ema_long_ratio"] = (ema_l - close) / close
    df["ema_crossover"] = (ema_s - ema_l) / ema_l

    macd_df = ti.macd(close, FEATURES.macd_fast, FEATURES.macd_slow, FEATURES.macd_signal)
    df["macd_ratio"] = macd_df["macd"] / close
    df["macd_signal_ratio"] = macd_df["macd_signal"] / close
    df["macd_hist_ratio"] = macd_df["macd_hist"] / close

    bb_df = ti.bollinger_bands(close, FEATURES.bb_period, FEATURES.bb_std)
    df["bb_upper_ratio"] = (bb_df["bb_upper"] - close) / close
    df["bb_lower_ratio"] = (close - bb_df["bb_lower"]) / close
    df["bb_width"] = bb_df["bb_width"]
    df["bb_pct_b"] = bb_df["bb_pct_b"]

    atr_val = ti.atr(high, low, close, FEATURES.atr_period)
    df["atr_ratio"] = atr_val / close

    vwap_val = ti.vwap(high, low, close, volume)
    df["vwap_ratio"] = (vwap_val - close) / close

    # 3. Return and Volatility Ratios
    df["return_1"] = close.pct_change()
    df["log_return_1"] = np.log(close / close.shift(1).replace(0, np.nan))
    df["volatility_20"] = df["log_return_1"].rolling(20).std()

    vol_mean_20 = volume.rolling(20).mean().replace(0, np.nan)
    df["volume_ratio_20"] = volume / vol_mean_20

    for w in FEATURES.rolling_windows:
        r_mean = close.rolling(w).mean()
        r_std = close.rolling(w).std()
        df[f"rolling_mean_{w}_ratio"] = (r_mean - close) / close
        df[f"rolling_std_{w}_ratio"] = r_std / close

    # Range relative to rolling max/min (52-week or 252 bars for daily)
    rolling_window_long = min(252, max(len(df) - 1, 20))
    high_long = close.rolling(rolling_window_long, min_periods=5).max()
    low_long = close.rolling(rolling_window_long, min_periods=5).min()
    df["pct_from_high_watermark"] = (close - high_long) / high_long.replace(0, np.nan)
    df["pct_from_low_watermark"] = (close - low_long) / low_long.replace(0, np.nan)

    # 4. Lag Features (Scale-Invariant)
    for lag in FEATURES.lag_periods:
        df[f"close_lag_{lag}_return"] = (close - close.shift(lag)) / close.shift(lag).replace(0, np.nan)
        df[f"return_lag_{lag}"] = df["return_1"].shift(lag)
        df[f"volume_ratio_lag_{lag}"] = df["volume_ratio_20"].shift(lag)

    # 5. Calendar Features
    if isinstance(df.index, pd.DatetimeIndex):
        df["day_of_week"] = df.index.dayofweek
        df["is_month_end"] = df.index.is_month_end.astype(int)
    elif "Date" in df.columns:
        date_series = pd.to_datetime(df["Date"], format="mixed", errors="coerce")
        df["day_of_week"] = date_series.dt.dayofweek.fillna(0).astype(int)
        df["is_month_end"] = date_series.dt.is_month_end.fillna(False).astype(int)

    return df


def build_feature_matrix(df: pd.DataFrame, ticker_col: str = "Ticker", drop_na: bool = True) -> pd.DataFrame:
    """Computes all scale-invariant technical features for single or multi-ticker DataFrames.

    Guarantees that rolling windows are computed PER TICKER and never cross ticker boundaries.
    """
    df = df.copy()

    # Determine if multi-ticker
    if ticker_col in df.columns and df[ticker_col].nunique() > 1:
        processed_groups = []
        for ticker, group in df.groupby(ticker_col, sort=False):
            feat_group = _build_features_single_ticker(group)
            feat_group[ticker_col] = ticker
            processed_groups.append(feat_group)
        result = pd.concat(processed_groups, axis=0)
    else:
        result = _build_features_single_ticker(df)

    if drop_na:
        result = result.dropna()

    return result


def get_model_feature_columns(df: pd.DataFrame) -> list[str]:
    """Returns list of numeric scale-invariant feature names suitable for ML model input."""
    feature_cols = []
    for c in df.columns:
        c_lower = str(c).lower()
        if c_lower not in EXCLUDED_PRICE_COLUMNS and pd.api.types.is_numeric_dtype(df[c]):
            feature_cols.append(c)
    return sorted(feature_cols)