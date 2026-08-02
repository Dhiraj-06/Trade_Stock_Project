"""
One-shot training execution script.
Ingests raw historical NIFTY 50 dataset -> scale-invariant features -> targets -> trains regressor & classifier -> saves to registry.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
import pandas as pd

# Add parent directory to sys.path if needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATA
from training.data_prep import prepare_training_data
from training.train_regressor import train_regressor_model
from training.train_classifier import train_classifier_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_training")


def run_full_training_pipeline(csv_path: Path | None = None) -> dict:
    csv_file = csv_path or DATA.raw_data_path

    if not csv_file.exists():
        raise FileNotFoundError(f"Historical dataset not found at {csv_file}")

    logger.info("Reading raw dataset from %s...", csv_file)
    raw_df = pd.read_csv(csv_file)
    logger.info("Loaded raw dataset shape: %s", raw_df.shape)

    # Discard pre-built indicator columns, keeping raw OHLCV + Ticker + Date
    raw_cols = ["Ticker", "Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    available_raw_cols = [c for c in raw_cols if c in raw_df.columns]
    raw_df = raw_df[available_raw_cols].copy()

    # Prepare features, targets, metadata
    X, y_ret, y_dir, feature_cols, meta_df = prepare_training_data(raw_df)

    logger.info("Starting Regressor Model B training...")
    reg_model, reg_metrics, reg_dir, reg_tag = train_regressor_model(X, y_ret, feature_cols, auto_promote=True)

    logger.info("Starting Classifier Model C training...")
    clf_model, clf_metrics, clf_dir, clf_tag = train_classifier_model(X, y_dir, feature_cols, auto_promote=True)

    print("\n" + "=" * 60)
    print("TRAINING PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Dataset Rows Processed: {len(X)}")
    print(f"Feature Columns Count : {len(feature_cols)}")
    print("-" * 60)
    print("REGRESSOR MODEL B METRICS (Walk-Forward CV):")
    print(f"  Version Tag        : {reg_tag}")
    print(f"  Avg MAE            : {reg_metrics['avg_mae']:.5f}%")
    print(f"  Avg RMSE           : {reg_metrics['avg_rmse']:.5f}%")
    print(f"  Avg R2 Score       : {reg_metrics['avg_r2']:.5f}")
    print(f"  Directional Acc    : {reg_metrics['avg_directional_accuracy']:.2%}")
    print("-" * 60)
    print("CLASSIFIER MODEL C METRICS (Walk-Forward CV):")
    print(f"  Version Tag        : {clf_tag}")
    print(f"  Avg Accuracy       : {clf_metrics['avg_accuracy']:.2%}")
    print(f"  Avg Precision      : {clf_metrics['avg_precision']:.2%}")
    print(f"  Avg Recall         : {clf_metrics['avg_recall']:.2%}")
    print(f"  Avg F1-Score       : {clf_metrics['avg_f1']:.4f}")
    print(f"  Avg ROC-AUC        : {clf_metrics.get('avg_roc_auc', 'N/A')}")
    print("=" * 60)

    return {
        "regressor_version": reg_tag,
        "classifier_version": clf_tag,
        "regressor_metrics": reg_metrics,
        "classifier_metrics": clf_metrics,
    }


if __name__ == "__main__":
    run_full_training_pipeline()
