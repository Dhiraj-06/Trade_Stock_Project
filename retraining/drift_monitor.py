"""
Drift Monitor & Realized Outcome Tracker.
Logs live model predictions alongside realized market outcomes to monitor degradation.
Triggers alert or retrain request when performance degrades past configured thresholds.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

from config.settings import DRIFT, DATA

logger = logging.getLogger(__name__)

DRIFT_LOG_FILE = DATA.processed_dir / "drift_log.csv"


def log_realized_outcome(
    ticker: str,
    prediction_timestamp: str,
    predicted_return_pct: float,
    predicted_direction: str,
    actual_return_pct: float,
    champion_version: str,
) -> pd.DataFrame:
    """Logs a single realized prediction outcome to drift tracking storage."""
    DATA.processed_dir.mkdir(parents=True, exist_ok=True)

    actual_direction = "UP" if actual_return_pct > 0 else "DOWN"
    return_error = abs(predicted_return_pct - actual_return_pct)
    direction_correct = 1 if predicted_direction == actual_direction else 0

    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "prediction_timestamp": prediction_timestamp,
        "predicted_return_pct": round(predicted_return_pct, 4),
        "actual_return_pct": round(actual_return_pct, 4),
        "return_error_mae": round(return_error, 4),
        "predicted_direction": predicted_direction,
        "actual_direction": actual_direction,
        "direction_correct": direction_correct,
        "champion_version": champion_version,
    }

    df_record = pd.DataFrame([record])

    if DRIFT_LOG_FILE.exists():
        df_record.to_csv(DRIFT_LOG_FILE, mode="a", header=False, index=False)
    else:
        df_record.to_csv(DRIFT_LOG_FILE, mode="w", header=True, index=False)

    logger.info("Logged realized outcome for %s: error=%.4f%% | dir_correct=%d", ticker, return_error, direction_correct)
    return df_record


def evaluate_drift_status() -> dict:
    """Evaluates rolling window drift metrics on recent realized predictions.

    Returns dict containing drift analysis and boolean `retrain_recommended`.
    """
    if not DRIFT_LOG_FILE.exists():
        return {
            "status": "insufficient_data",
            "samples_count": 0,
            "retrain_recommended": False,
            "message": "Drift log file does not exist yet."
        }

    df = pd.read_csv(DRIFT_LOG_FILE)
    if len(df) < 10:
        return {
            "status": "insufficient_data",
            "samples_count": len(df),
            "retrain_recommended": False,
            "message": f"Only {len(df)} samples logged; need at least 10 for drift evaluation."
        }

    recent = df.tail(DRIFT.window_size)
    rolling_mae = float(recent["return_error_mae"].mean())
    rolling_acc = float(recent["direction_correct"].mean())

    baseline_mae = 1.05  # Initial regressor walk-forward MAE baseline
    mae_degradation = (rolling_mae - baseline_mae) / baseline_mae

    retrain_recommended = False
    reasons = []

    if mae_degradation > DRIFT.mae_degradation_threshold:
        retrain_recommended = True
        reasons.append(f"MAE degraded by {mae_degradation:.1%} (threshold {DRIFT.mae_degradation_threshold:.1%})")

    if rolling_acc < DRIFT.directional_acc_threshold:
        retrain_recommended = True
        reasons.append(f"Directional accuracy dropped to {rolling_acc:.2%} (threshold {DRIFT.directional_acc_threshold:.2%})")

    status_msg = "HEALTHY" if not retrain_recommended else "DRIFT_DETECTED"
    logger.info("Drift evaluation: status=%s | MAE=%.4f | Acc=%.2%% | RetrainNeeded=%s",
                status_msg, rolling_mae, rolling_acc, retrain_recommended)

    return {
        "status": status_msg,
        "samples_count": len(recent),
        "rolling_mae": round(rolling_mae, 4),
        "rolling_accuracy": round(rolling_acc, 4),
        "retrain_recommended": retrain_recommended,
        "reasons": reasons
    }
