"""
Model B — XGBoost Regressor predicting next-day return % (target_return_pct).
Evaluated via 5-fold walk-forward validation (TimeSeriesSplit).
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

from config.settings import TRAINING
from models.model_utils import save_candidate, promote_candidate
from training.validation import create_walk_forward_splits

logger = logging.getLogger(__name__)

MODEL_NAME = "return_regressor"

MODEL_PARAMS = dict(
    n_estimators=300,
    max_depth=4,
    learning_rate=0.03,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=0.1,
    reg_lambda=1.0,
    objective="reg:squarederror",
    random_state=42,
)


def walk_forward_evaluate(X: pd.DataFrame, y: pd.Series, n_splits: int = None) -> list[dict]:
    splits = create_walk_forward_splits(X, n_splits=n_splits)

    fold_results = []
    for fold_idx, (train_idx, test_idx) in enumerate(splits):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        model = XGBRegressor(**MODEL_PARAMS)
        model.fit(X_train, y_train)
        preds = model.predict(X_test)

        mae = float(mean_absolute_error(y_test, preds))
        rmse = float(np.sqrt(mean_squared_error(y_test, preds)))
        r2 = float(r2_score(y_test, preds))
        dir_acc = float(np.mean(np.sign(preds) == np.sign(y_test)))

        fold_results.append({
            "fold": fold_idx,
            "train_size": len(train_idx),
            "test_size": len(test_idx),
            "mae": round(mae, 5),
            "rmse": round(rmse, 5),
            "r2": round(r2, 5),
            "directional_accuracy": round(dir_acc, 4),
        })
        logger.info("Fold %d: MAE=%.5f RMSE=%.5f R2=%.5f DirAcc=%.4f", fold_idx, mae, rmse, r2, dir_acc)

    return fold_results


def train_regressor_model(X: pd.DataFrame, y: pd.Series, feature_columns: list[str], auto_promote: bool = True) -> tuple:
    """Trains final regressor model, computes walk-forward metrics, and saves to registry."""
    fold_metrics = walk_forward_evaluate(X, y)

    avg_metrics = {
        "avg_mae": round(float(np.mean([f["mae"] for f in fold_metrics])), 5),
        "avg_rmse": round(float(np.mean([f["rmse"] for f in fold_metrics])), 5),
        "avg_r2": round(float(np.mean([f["r2"] for f in fold_metrics])), 5),
        "avg_directional_accuracy": round(float(np.mean([f["directional_accuracy"] for f in fold_metrics])), 4),
        "fold_details": fold_metrics,
    }

    # Train final model on full dataset
    model = XGBRegressor(**MODEL_PARAMS)
    model.fit(X, y)

    version_dir, version_tag = save_candidate(model, MODEL_NAME, avg_metrics, feature_columns)

    if auto_promote:
        promote_candidate(MODEL_NAME, version_tag)

    return model, avg_metrics, version_dir, version_tag