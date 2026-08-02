"""
Versioned model persistence.

Every trained model is saved with a timestamp + a metadata.json sitting next
to it (metrics, feature list, training data range). This is what makes the
Phase 6 "auto-retrain safely" promotion logic possible later: the scheduler
can load metadata for the current production model and the newly trained
candidate, compare metrics, and only promote the candidate if it's actually
better -- without that metadata, "did the new model actually improve?" is
unanswerable.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from config.settings import TRAINING

logger = logging.getLogger(__name__)


def save_model(model: Any, model_name: str, metrics: dict, feature_columns: list[str],
               extra_meta: dict | None = None) -> Path:
    """Saves model + metadata.json into a timestamped folder under the registry.

    model_name examples: "return_regressor", "direction_classifier"
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version_dir = TRAINING.model_registry_dir / model_name / timestamp
    version_dir.mkdir(parents=True, exist_ok=True)

    model_path = version_dir / "model.joblib"
    joblib.dump(model, model_path)

    meta = {
        "model_name": model_name,
        "timestamp": timestamp,
        "metrics": metrics,
        "feature_columns": feature_columns,
        **(extra_meta or {}),
    }
    with open(version_dir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Saved %s -> %s | metrics=%s", model_name, model_path, metrics)
    return version_dir


def load_latest_model(model_name: str) -> tuple[Any, dict]:
    """Loads the most recently saved version of a given model."""
    base_dir = TRAINING.model_registry_dir / model_name
    if not base_dir.exists():
        raise FileNotFoundError(f"No models found for '{model_name}' in {base_dir}")

    versions = sorted([d for d in base_dir.iterdir() if d.is_dir()])
    if not versions:
        raise FileNotFoundError(f"No versioned runs found under {base_dir}")

    latest = versions[-1]
    model = joblib.load(latest / "model.joblib")
    with open(latest / "metadata.json") as f:
        meta = json.load(f)

    logger.info("Loaded %s from %s", model_name, latest)
    return model, meta


def list_versions(model_name: str) -> list[Path]:
    base_dir = TRAINING.model_registry_dir / model_name
    if not base_dir.exists():
        return []
    return sorted([d for d in base_dir.iterdir() if d.is_dir()])