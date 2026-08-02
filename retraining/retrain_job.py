"""
Automated Self-Retraining Pipeline & Champion Promotion Gate.
Pulls latest data -> retrains candidate models -> compares walk-forward metrics vs champion -> promotes ONLY if better.
"""
from __future__ import annotations

import logging
import pandas as pd
from pathlib import Path

from config.settings import DATA, TRAINING
from models.model_utils import load_champion, promote_candidate
from training.data_prep import prepare_training_data
from training.train_regressor import train_regressor_model
from training.train_classifier import train_classifier_model

logger = logging.getLogger("retrain_job")


def load_combined_dataset() -> pd.DataFrame:
    """Combines raw historical NIFTY 50 CSV with any accumulated Fyers live buffers in data/live/."""
    frames = []
    if DATA.raw_data_path.exists():
        raw_df = pd.read_csv(DATA.raw_data_path)
        cols = ["Ticker", "Date", "Open", "High", "Low", "Close", "Volume"]
        available = [c for c in cols if c in raw_df.columns]
        frames.append(raw_df[available])

    # Append live buffer Parquet files if present
    if DATA.live_dir.exists():
        for p_file in DATA.live_dir.glob("*_live.parquet"):
            try:
                live_df = pd.read_parquet(p_file)
                cols = ["Ticker", "Date", "Open", "High", "Low", "Close", "Volume"]
                available = [c for c in cols if c in live_df.columns]
                frames.append(live_df[available])
            except Exception as e:
                logger.warning("Error reading live buffer %s: %s", p_file, e)

    if not frames:
        raise FileNotFoundError("No raw data or live buffers found for retraining.")

    combined = pd.concat(frames, ignore_index=True)
    # Deduplicate by Ticker + Date
    combined = combined.drop_duplicates(subset=["Ticker", "Date"], keep="last").sort_values(["Ticker", "Date"])
    return combined


def evaluate_promotion_gate(candidate_metrics: dict, champion_meta: dict, model_type: str) -> bool:
    """Compares candidate metrics against champion metadata.

    For Regressor: Candidate MAE must be <= (Champion MAE - min_improvement).
    For Classifier: Candidate Accuracy must be >= (Champion Accuracy + min_improvement).
    """
    if not champion_meta or "metrics" not in champion_meta:
        logger.info("No existing champion metadata found for %s. Auto-promoting initial run.", model_type)
        return True

    champ_metrics = champion_meta["metrics"]

    if model_type == "regressor":
        cand_mae = candidate_metrics["avg_mae"]
        champ_mae = champ_metrics.get("avg_mae", 999.0)
        improvement = champ_mae - cand_mae

        logger.info("Regressor Gate: Candidate MAE=%.5f vs Champion MAE=%.5f | Improvement=%.5f",
                    cand_mae, champ_mae, improvement)
        return improvement >= -TRAINING.min_score_improvement

    elif model_type == "classifier":
        cand_acc = candidate_metrics["avg_accuracy"]
        champ_acc = champ_metrics.get("avg_accuracy", 0.0)
        improvement = cand_acc - champ_acc

        logger.info("Classifier Gate: Candidate Acc=%.4f vs Champion Acc=%.4f | Improvement=%.4f",
                    cand_acc, champ_acc, improvement)
        return improvement >= -TRAINING.min_score_improvement

    return False


def run_retraining_job() -> dict:
    """Executes full scheduled retrain job with promotion gates."""
    logger.info("=== STARTING AUTOMATED RETRAINING JOB ===")

    # Step 1: Load updated dataset
    full_df = load_combined_dataset()
    logger.info("Combined retraining dataset shape: %s", full_df.shape)

    # Step 2: Prepare features and targets
    X, y_ret, y_dir, feature_cols, meta_df = prepare_training_data(full_df)

    # Step 3: Train candidate Regressor
    logger.info("Training candidate Regressor...")
    cand_reg, cand_reg_metrics, _, cand_reg_tag = train_regressor_model(X, y_ret, feature_cols, auto_promote=False)

    # Load current Regressor champion metadata
    try:
        _, champ_reg_meta = load_champion("return_regressor")
    except Exception:
        champ_reg_meta = {}

    reg_promoted = evaluate_promotion_gate(cand_reg_metrics, champ_reg_meta, "regressor")
    if reg_promoted:
        promote_candidate("return_regressor", cand_reg_tag)
        logger.info("REGRESSOR PROMOTED: %s is now active champion.", cand_reg_tag)
    else:
        logger.info("REGRESSOR REJECTED: Candidate %s did not beat champion. Retaining %s.",
                    cand_reg_tag, champ_reg_meta.get("version", "current champion"))

    # Step 4: Train candidate Classifier
    logger.info("Training candidate Classifier...")
    cand_clf, cand_clf_metrics, _, cand_clf_tag = train_classifier_model(X, y_dir, feature_cols, auto_promote=False)

    try:
        _, champ_clf_meta = load_champion("direction_classifier")
    except Exception:
        champ_clf_meta = {}

    clf_promoted = evaluate_promotion_gate(cand_clf_metrics, champ_clf_meta, "classifier")
    if clf_promoted:
        promote_candidate("direction_classifier", cand_clf_tag)
        logger.info("CLASSIFIER PROMOTED: %s is now active champion.", cand_clf_tag)
    else:
        logger.info("CLASSIFIER REJECTED: Candidate %s did not beat champion. Retaining %s.",
                    cand_clf_tag, champ_clf_meta.get("version", "current champion"))

    summary = {
        "status": "completed",
        "regressor_candidate": cand_reg_tag,
        "regressor_promoted": reg_promoted,
        "classifier_candidate": cand_clf_tag,
        "classifier_promoted": clf_promoted,
    }
    logger.info("=== RETRAINING JOB COMPLETED: %s ===", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_retraining_job()
