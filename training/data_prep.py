"""
Data preparation for model training.
Combines raw OHLCV loading, per-ticker scale-invariant feature extraction (build_features.py),
and zero-leakage target construction.
"""
from __future__ import annotations

import logging
import pandas as pd

from config.settings import TRAINING
from features.build_features import build_feature_matrix, get_model_feature_columns
from training.build_targets import build_targets_per_ticker

logger = logging.getLogger(__name__)


def prepare_training_data(
    raw_df: pd.DataFrame,
    ticker_col: str = "Ticker",
    date_col: str = "Date",
    close_col: str = "Close",
    horizon: int | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.Series, list[str], pd.DataFrame]:
    """Prepares scale-invariant feature matrix X, regressor target y_return, classifier target y_direction.

    Parameters:
        raw_df: DataFrame containing at least Ticker, Date, Open, High, Low, Close, Volume.
        ticker_col: Name of ticker grouping column.
        date_col: Name of date timestamp column.
        close_col: Name of close price column.
        horizon: Prediction horizon in bars (defaults to TRAINING.horizon_candles).

    Returns:
        (X, y_return, y_direction, feature_columns, meta_df)
    """
    target_horizon = horizon if horizon is not None else TRAINING.horizon_candles
    logger.info("Building features for %d rows, ticker_col=%s, horizon=%d...", len(raw_df), ticker_col, target_horizon)

    # 1. Build scale-invariant technical feature matrix
    featured = build_feature_matrix(raw_df, ticker_col=ticker_col, drop_na=False)

    # 2. Build target columns per ticker safely (zero look-ahead leakage across ticker boundaries)
    if ticker_col in featured.columns and featured[ticker_col].nunique() > 1:
        labeled = build_targets_per_ticker(featured, ticker_col=ticker_col, close_col=close_col, horizon=target_horizon)
    else:
        from training.build_targets import build_targets
        labeled = build_targets(featured, close_col=close_col, horizon=target_horizon)

    # 3. Drop incomplete leading (warm-up) or trailing (label look-ahead) rows
    labeled = labeled.dropna(subset=["target_return_pct", "target_up"])

    feature_cols = get_model_feature_columns(labeled)

    # Extract X, targets, and metadata (Ticker, Date, Close)
    X = labeled[feature_cols].copy()
    y_return = labeled["target_return_pct"].copy()
    y_direction = labeled["target_up"].copy()

    meta_cols = [c for c in [ticker_col, date_col, close_col] if c in labeled.columns]
    meta_df = labeled[meta_cols].copy()

    logger.info("Data prep complete. X shape: %s | Features: %d | Horizon: %d bars", X.shape, len(feature_cols), target_horizon)
    return X, y_return, y_direction, feature_cols, meta_df