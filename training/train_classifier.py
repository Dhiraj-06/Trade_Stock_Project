"""
Model C — XGBoost Classifier predicting next-day upward movement (target_up).
Evaluated via 5-fold walk-forward validation (TimeSeriesSplit).
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from xgboost import XGBClassifier

from config.settings import TRAINING
from models.model_utils import save_candidate, promote_candidate
from training.validation import create_walk_forward_splits

logger = logging.getLogger(__name__)

MODEL_NAME = "direction_classifier"

MODEL_PARAMS = dict(
    n_estimators=300,
    max_depth=4,
    learning_rate=0.03,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=0.1,
    reg_lambda=1.0,
    eval_metric="logloss",
    random_state=42,
)


def walk_forward_evaluate(X: pd.DataFrame, y: pd.Series, n_splits: int = None) -> list[dict]:
    splits = create_walk_forward_splits(X, n_splits=n_splits)

    fold_results = []
    for fold_idx, (train_idx, test_idx) in enumerate(splits):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        model = XGBClassifier(**MODEL_PARAMS)
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        proba = model.predict_proba(X_test)[:, 1]

        acc = float(accuracy_score(y_test, preds))
        prec = float(precision_score(y_test, preds, zero_division=0))
        rec = float(recall_score(y_test, preds, zero_division=0))
        f1 = float(f1_score(y_test, preds, zero_division=0))

        auc = float(roc_auc_score(y_test, proba)) if y_test.nunique() > 1 else None

        fold_results.append({
            "fold": fold_idx,
            "train_size": len(train_idx),
            "test_size": len(test_idx),
            "accuracy": round(acc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "roc_auc": round(auc, 4) if auc is not None else None,
        })
        logger.info("Fold %d: Acc=%.4f Prec=%.4f Rec=%.4f F1=%.4f AUC=%s",
                    fold_idx, acc, prec, rec, f1, auc)

    return fold_results


def train_classifier_model(X: pd.DataFrame, y: pd.Series, feature_columns: list[str], auto_promote: bool = True) -> tuple:
    """Trains final classifier model, computes walk-forward metrics, and saves to registry."""
    fold_metrics = walk_forward_evaluate(X, y)

    valid_aucs = [f["roc_auc"] for f in fold_metrics if f["roc_auc"] is not None]

    avg_metrics = {
        "avg_accuracy": round(float(np.mean([f["accuracy"] for f in fold_metrics])), 4),
        "avg_precision": round(float(np.mean([f["precision"] for f in fold_metrics])), 4),
        "avg_recall": round(float(np.mean([f["recall"] for f in fold_metrics])), 4),
        "avg_f1": round(float(np.mean([f["f1"] for f in fold_metrics])), 4),
        "avg_roc_auc": round(float(np.mean(valid_aucs)), 4) if valid_aucs else None,
        "fold_details": fold_metrics,
    }

    # Train final model on full dataset
    model = XGBClassifier(**MODEL_PARAMS)
    model.fit(X, y)

    version_dir, version_tag = save_candidate(model, MODEL_NAME, avg_metrics, feature_columns)

    if auto_promote:
        promote_candidate(MODEL_NAME, version_tag)

    return model, avg_metrics, version_dir, version_tag