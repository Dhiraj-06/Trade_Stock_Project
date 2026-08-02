"""
Technical indicators implemented in pure pandas/numpy so the ML service has
no dependency on ta-lib (which needs a compiled C library and is painful to
deploy in Docker). Every function takes/returns pandas Series or adds
columns to a DataFrame — pick whichever composition style you prefer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "macd_signal": signal_line, "macd_hist": hist})


def bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    std = close.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower)
    return pd.DataFrame({"bb_upper": upper, "bb_mid": mid, "bb_lower": lower,
                          "bb_width": width, "bb_pct_b": pct_b})


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = atr(high, low, close, period=1)  # raw TR, not smoothed yet
    atr_smooth = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_smooth
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (high + low + close) / 3
    return (typical_price * volume).cumsum() / volume.cumsum()


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    typical_price = (high + low + close) / 3
    sma_tp = typical_price.rolling(period).mean()
    mean_dev = typical_price.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (typical_price - sma_tp) / (0.015 * mean_dev)


def stochastic_oscillator(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14, smooth_k: int = 3) -> pd.DataFrame:
    lowest_low = low.rolling(period).min()
    highest_high = high.rolling(period).max()
    percent_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    percent_k_smooth = percent_k.rolling(smooth_k).mean()
    percent_d = percent_k_smooth.rolling(smooth_k).mean()
    return pd.DataFrame({"stoch_k": percent_k_smooth, "stoch_d": percent_d})