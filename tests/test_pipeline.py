"""
End-to-end pipeline smoke test.
Tests synthetic multi-ticker data -> data_prep -> training -> model registry -> predictor -> live prediction API.
Runs in seconds.
"""
import numpy as np
import pandas as pd
import pytest

from training.data_prep import prepare_training_data
from training.train_regressor import train_regressor_model
from training.train_classifier import train_classifier_model
from models.model_utils import load_champion
from inference.predictor import Predictor


def make_synthetic_dataset() -> pd.DataFrame:
    rng = pd.date_range("2024-01-01", periods=150, freq="D")
    dfs = []
    for ticker in ["WIPRO", "ADANIENT", "RELIANCE"]:
        np.random.seed(len(ticker))
        base = 100.0 if ticker == "WIPRO" else (1800.0 if ticker == "ADANIENT" else 2800.0)
        returns = np.random.normal(0.0005, 0.015, 150)
        price = base * np.exp(np.cumsum(returns))
        df = pd.DataFrame({
            "Ticker": ticker,
            "Date": rng,
            "Open": price * 0.998,
            "High": price * 1.01,
            "Low": price * 0.99,
            "Close": price,
            "Volume": np.random.randint(50000, 500000, 150),
        })
        dfs.append(df)
    return pd.concat(dfs, axis=0).reset_index(drop=True)


def test_end_to_end_pipeline():
    # 1. Data Prep
    df = make_synthetic_dataset()
    X, y_ret, y_dir, feature_cols, meta_df = prepare_training_data(df)

    assert len(X) > 100, f"Expected >100 prepared rows, got {len(X)}"
    assert len(feature_cols) >= 20, f"Expected >=20 feature columns, got {len(feature_cols)}"

    # 2. Train Regressor & Classifier
    reg_model, reg_metrics, _, reg_tag = train_regressor_model(X, y_ret, feature_cols, auto_promote=True)
    clf_model, clf_metrics, _, clf_tag = train_classifier_model(X, y_dir, feature_cols, auto_promote=True)

    assert reg_tag.startswith("v_")
    assert clf_tag.startswith("v_")

    # 3. Champion Loading
    loaded_reg, meta_reg = load_champion("return_regressor")
    loaded_clf, meta_clf = load_champion("direction_classifier")

    assert loaded_reg is not None
    assert loaded_clf is not None

    # 4. Predictor Inference
    predictor = Predictor()
    sample_features = X.tail(5)
    result = predictor.predict(sample_features, current_price=180.0)

    assert "predicted_return_pct" in result
    assert "predicted_price" in result
    assert result["direction"] in ["UP", "DOWN"]
    assert 0.0 <= result["confidence_score"] <= 1.0
