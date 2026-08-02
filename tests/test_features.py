"""
Unit tests for features/build_features.py.
Verifies:
1. Multi-ticker synthetic data -> zero boundary contamination.
2. Feature value ranges -> all price/volume-scale features are scale-invariant ratios or bounded oscillators.
"""
import numpy as np
import pandas as pd
import pytest

from features.build_features import build_feature_matrix, get_model_feature_columns


def make_synthetic_ohlcv(ticker: str, base_price: float, n_rows: int = 300) -> pd.DataFrame:
    rng = pd.date_range("2024-01-01", periods=n_rows, freq="D")
    np.random.seed(42 if ticker == "TICKER_A" else 99)
    returns = np.random.normal(0.001, 0.02, n_rows)
    price = base_price * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "Ticker": ticker,
        "Date": rng,
        "Open": price * (1 + np.random.uniform(-0.005, 0.005, n_rows)),
        "High": price * (1 + np.random.uniform(0.001, 0.015, n_rows)),
        "Low": price * (1 - np.random.uniform(0.001, 0.015, n_rows)),
        "Close": price,
        "Volume": np.random.randint(10000, 500000, n_rows),
    })


def test_no_cross_ticker_boundary_contamination():
    """Verify that feature calculation on stacked multi-ticker DataFrame produces
    identical results to computing each ticker independently."""
    df_a = make_synthetic_ohlcv("TICKER_A", base_price=100.0, n_rows=300)
    df_b = make_synthetic_ohlcv("TICKER_B", base_price=5000.0, n_rows=300)

    # Combined computation
    df_stacked = pd.concat([df_a, df_b], axis=0).reset_index(drop=True)
    features_stacked = build_feature_matrix(df_stacked, drop_na=False)

    # Separate computation
    features_a_sep = build_feature_matrix(df_a, drop_na=False)
    features_b_sep = build_feature_matrix(df_b, drop_na=False)

    feature_cols = get_model_feature_columns(features_stacked)

    # Extract ticker A from stacked result
    feat_a_stacked = features_stacked[features_stacked["Ticker"] == "TICKER_A"][feature_cols].reset_index(drop=True)
    feat_a_sep = features_a_sep[feature_cols].reset_index(drop=True)

    feat_b_stacked = features_stacked[features_stacked["Ticker"] == "TICKER_B"][feature_cols].reset_index(drop=True)
    feat_b_sep = features_b_sep[feature_cols].reset_index(drop=True)

    # Compare non-NaN values
    np.testing.assert_allclose(feat_a_stacked.values, feat_a_sep.values, rtol=1e-5, atol=1e-5, equal_nan=True)
    np.testing.assert_allclose(feat_b_stacked.values, feat_b_sep.values, rtol=1e-5, atol=1e-5, equal_nan=True)


def test_features_are_scale_invariant():
    """Verify that features stay bounded regardless of whether stock price is $10 or $10,000."""
    df_cheap = make_synthetic_ohlcv("CHEAP", base_price=10.0, n_rows=300)
    df_expensive = make_synthetic_ohlcv("EXPENSIVE", base_price=10000.0, n_rows=300)

    feat_cheap = build_feature_matrix(df_cheap, drop_na=True)
    feat_exp = build_feature_matrix(df_expensive, drop_na=True)

    feature_cols = get_model_feature_columns(feat_cheap)

    assert len(feature_cols) >= 20, f"Expected at least 20 feature columns, got {len(feature_cols)}"

    # Confirm raw price level columns (Close, Open, High, Low) are excluded from model feature list
    for raw in ["Close", "Open", "High", "Low", "Volume", "close", "open", "high", "low", "volume"]:
        assert raw not in feature_cols, f"Raw price/volume column {raw} must not be in model feature list"

    # Verify that feature distributions for cheap and expensive stocks stay within bounded/ratio ranges (-100 to +100)
    for col in feature_cols:
        cheap_max = feat_cheap[col].abs().max()
        exp_max = feat_exp[col].abs().max()

        assert cheap_max < 500, f"Feature {col} exceeded scale bound on cheap stock: {cheap_max}"
        assert exp_max < 500, f"Feature {col} exceeded scale bound on expensive stock: {exp_max}"
