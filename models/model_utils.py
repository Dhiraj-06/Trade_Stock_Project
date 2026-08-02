"""
Versioned model registry and lifecycle management.
Handles model persistence, candidate evaluation, champion promotion, and rollback.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple

import joblib

from config.settings import TRAINING

logger = logging.getLogger(__name__)


def _get_registry_path(model_name: str) -> Path:
    base = TRAINING.model_registry_dir / model_name
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_candidate(
    model: Any,
    model_name: str,
    metrics: dict,
    feature_columns: list[str],
    extra_meta: dict | None = None
) -> Tuple[Path, str]:
    """Saves candidate model and metadata into a versioned folder.

    Returns (version_dir_path, version_tag).
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version_tag = f"v_{timestamp}"
    version_dir = _get_registry_path(model_name) / version_tag
    version_dir.mkdir(parents=True, exist_ok=True)

    model_path = version_dir / "model.joblib"
    joblib.dump(model, model_path)

    meta = {
        "model_name": model_name,
        "version": version_tag,
        "timestamp": timestamp,
        "metrics": metrics,
        "feature_columns": feature_columns,
        "is_champion": False,
        **(extra_meta or {}),
    }
    with open(version_dir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Saved candidate model %s [%s] -> %s", model_name, version_tag, version_dir)
    return version_dir, version_tag


def promote_candidate(model_name: str, version_tag: str) -> Path:
    """Promotes candidate version to be the current active champion."""
    base_dir = _get_registry_path(model_name)
    version_dir = base_dir / version_tag
    if not version_dir.exists():
        raise FileNotFoundError(f"Version {version_tag} not found under {base_dir}")

    champion_dir = base_dir / "champion"
    champion_dir.mkdir(parents=True, exist_ok=True)

    # Copy candidate files to champion folder
    for item in version_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, champion_dir / item.name)

    # Update metadata to reflect champion status
    meta_path = champion_dir / "metadata.json"
    if meta_path.exists():
        with open(meta_path, "r") as f:
            meta = json.load(f)
        meta["is_champion"] = True
        meta["promoted_at"] = datetime.now(timezone.utc).isoformat()
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    logger.info("PROMOTED candidate %s [%s] to champion at %s", model_name, version_tag, champion_dir)
    return champion_dir


def load_champion(model_name: str) -> Tuple[Any, dict]:
    """Loads current active champion model and its metadata.

    If no explicit champion exists yet, loads the latest version as default champion.
    """
    base_dir = _get_registry_path(model_name)
    champion_dir = base_dir / "champion"

    if champion_dir.exists() and (champion_dir / "model.joblib").exists():
        target_dir = champion_dir
    else:
        # Fallback to latest versioned directory
        versions = sorted([d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith("v_")])
        if not versions:
            raise FileNotFoundError(f"No trained model versions found for '{model_name}' in {base_dir}")
        target_dir = versions[-1]

    model = joblib.load(target_dir / "model.joblib")
    with open(target_dir / "metadata.json", "r") as f:
        meta = json.load(f)

    logger.info("Loaded champion %s from %s", model_name, target_dir)
    return model, meta


def list_versions(model_name: str) -> list[dict]:
    """Lists all versioned runs for a given model."""
    base_dir = _get_registry_path(model_name)
    versions = sorted([d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith("v_")])
    result = []
    for v_dir in versions:
        meta_file = v_dir / "metadata.json"
        if meta_file.exists():
            with open(meta_file, "r") as f:
                result.append(json.load(f))
    return result


def rollback(model_name: str, target_version: str | None = None) -> Path:
    """Rolls back champion model to specified target_version or previous version."""
    versions = list_versions(model_name)
    if not versions:
        raise RuntimeError(f"No versions available to rollback for {model_name}")

    if target_version:
        selected = target_version
    else:
        # Select second latest if available
        if len(versions) < 2:
            raise RuntimeError("Cannot rollback: only one version exists in registry.")
        selected = versions[-2]["version"]

    return promote_candidate(model_name, selected)
