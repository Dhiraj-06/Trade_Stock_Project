"""
Walk-forward time-series cross-validation helper.
Strictly time-ordered (TimeSeriesSplit), zero future-to-past leakage.
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from config.settings import TRAINING

logger = logging.getLogger(__name__)


def create_walk_forward_splits(X: pd.DataFrame, n_splits: int = None, test_size: int = None):
    """Generates time-ordered walk-forward (train_idx, test_idx) pairs."""
    n_splits = n_splits or TRAINING.n_splits
    n_rows = len(X)

    max_test_size = n_rows // (n_splits + 1)
    test_sz = min(test_size or TRAINING.test_size_candles, max_test_size)

    if test_sz < 30:
        raise ValueError(
            f"Dataset size ({n_rows} rows) is too small for {n_splits}-fold walk-forward validation. "
            f"Need at least 30 samples per test fold."
        )

    tscv = TimeSeriesSplit(n_splits=n_splits, test_size=test_sz)
    return list(tscv.split(X))
