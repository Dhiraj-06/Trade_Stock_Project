"""
Predictor interface for live inference.
Loads active champion models from registry and executes inference on scale-invariant feature vectors.
Generates comprehensive risk factor analytics and UI display parameters.
"""
from __future__ import annotations

import logging
from typing import Dict, Any
import numpy as np
import pandas as pd

from models.model_utils import load_champion

logger = logging.getLogger(__name__)


class Predictor:

    def __init__(self):
        self.reg_model = None
        self.reg_meta = None
        self.clf_model = None
        self.clf_meta = None

        self.reload_champions()

    def reload_champions(self):
        """Reloads the active champion models from models/registry."""
        try:
            self.reg_model, self.reg_meta = load_champion("return_regressor")
            self.clf_model, self.clf_meta = load_champion("direction_classifier")
            logger.info("Predictor loaded regressor champion [%s] & classifier champion [%s]",
                        self.reg_meta.get("version"), self.clf_meta.get("version"))
        except Exception as e:
            logger.warning("Failed loading champion models from registry (%s). Predictor will need models before inference.", e)

    def predict(self, feature_df: pd.DataFrame, current_price: float) -> dict[str, Any]:
        """Takes a DataFrame containing scale-invariant feature columns (last row is used for inference).

        Returns structured dictionary containing ML predictions and all 9 UI risk parameters.
        """
        if self.reg_model is None or self.clf_model is None:
            self.reload_champions()
            if self.reg_model is None or self.clf_model is None:
                raise RuntimeError("Champion models not available in registry. Run scripts/run_training.py first.")

        # Match exact feature columns expected by models
        expected_cols = self.reg_meta.get("feature_columns", [])
        if not expected_cols:
            expected_cols = [c for c in feature_df.columns if c not in ["Ticker", "Date", "Close", "Open", "High", "Low", "Volume"]]

        # Take last row (most recent candle)
        last_row = feature_df[expected_cols].tail(1)
        full_last_row = feature_df.iloc[-1].to_dict()

        # 1. Regressor prediction
        pred_return_pct = float(self.reg_model.predict(last_row)[0])
        pred_price = float(current_price * (1 + pred_return_pct / 100.0))

        # 2. Classifier prediction
        if hasattr(self.clf_model, "predict_proba"):
            proba_up = float(self.clf_model.predict_proba(last_row)[0, 1])
        else:
            proba_up = 0.5

        direction = "UP" if proba_up >= 0.5 else "DOWN"
        confidence_score = round(abs(proba_up - 0.5) * 2.0, 4)  # Bounded [0.0, 1.0]

        # 3. Calculate Risk Factors & UI Display Analytics
        # AI Recommendation
        if confidence_score >= 0.10:
            ai_recommendation = "BUY CALL" if direction == "UP" else "BUY PUT"
        else:
            ai_recommendation = "WAIT"

        # Market Trend
        ema_short_ratio = float(full_last_row.get("ema_short_ratio", 0.0))
        ema_long_ratio = float(full_last_row.get("ema_long_ratio", 0.0))
        if ema_short_ratio > 0 and ema_long_ratio > 0:
            market_trend = "Strong Bullish"
        elif ema_short_ratio > 0:
            market_trend = "Bullish"
        elif ema_short_ratio < 0 and ema_long_ratio < 0:
            market_trend = "Strong Bearish"
        else:
            market_trend = "Bearish"

        # Momentum & Oscillators
        rsi_14 = float(full_last_row.get("rsi", 50.0))
        macd_ratio = float(full_last_row.get("macd_ratio", 0.0))
        macd_signal_ratio = float(full_last_row.get("macd_signal_ratio", 0.0))
        macd_status = "Positive (Buying Confirmation)" if macd_ratio > macd_signal_ratio else "Negative (Selling Pressure)"
        trade_score = int(np.clip(50 + (rsi_14 - 50) * 0.5 + (confidence_score * 40), 10, 99))

        # Expected Move & Stop Loss
        atr_ratio = float(full_last_row.get("atr_ratio", 0.015))
        atr_points = round(current_price * atr_ratio, 2)
        if direction == "UP":
            suggested_stop_loss = round(current_price - (1.5 * atr_points), 2)
        else:
            suggested_stop_loss = round(current_price + (1.5 * atr_points), 2)

        entry_low = round(current_price * 0.998, 2)
        entry_high = round(current_price * 1.002, 2)
        suggested_entry_zone = f"₹{entry_low} - ₹{entry_high}"

        # Key Levels (Support & Resistance)
        bb_lower_ratio = float(full_last_row.get("bb_lower_ratio", -0.02))
        bb_upper_ratio = float(full_last_row.get("bb_upper_ratio", 0.02))
        support_20 = round(current_price * (1.0 + bb_lower_ratio), 2)
        resistance_20 = round(current_price * (1.0 + bb_upper_ratio), 2)

        # Volume Strength
        vol_ratio = float(full_last_row.get("volume_ratio_20", 1.0))
        high_volume_confirmation = bool(vol_ratio > 1.1)

        # Volatility & Risk Rating
        volatility_20_pct = float(full_last_row.get("volatility_20", 0.015) * 100.0)
        if confidence_score >= 0.30 and volatility_20_pct < 2.0:
            risk_rating = "LOW"
        elif confidence_score >= 0.15:
            risk_rating = "MEDIUM"
        else:
            risk_rating = "HIGH"

        # Drawdown & Risk/Reward Guard
        drawdown_50_pct = round(abs(float(full_last_row.get("pct_from_high_watermark", -0.05))) * 100.0, 2)

        return {
            "predicted_return_pct": round(pred_return_pct, 4),
            "predicted_price": round(pred_price, 2),
            "direction": direction,
            "proba_up": round(proba_up, 4),
            "confidence_score": confidence_score,
            "regressor_version": self.reg_meta.get("version", "unknown"),
            "classifier_version": self.clf_meta.get("version", "unknown"),

            # Extended Risk Factors & Analytics Parameters for Frontend
            "analytics": {
                "ai_recommendation": ai_recommendation,
                "market_trend": market_trend,
                "trade_score": trade_score,
                "momentum": {
                    "rsi_14": round(rsi_14, 2),
                    "macd_status": macd_status,
                },
                "expected_move": {
                    "atr_14_points": atr_points,
                    "target_price": round(pred_price, 2),
                    "stop_loss_price": suggested_stop_loss,
                    "suggested_entry_zone": suggested_entry_zone,
                    "duration": "30 Mins",
                },
                "key_levels": {
                    "support_20": support_20,
                    "resistance_20": resistance_20,
                    "entry_advice": "Enter in suggested range with proper risk management" if ai_recommendation != "WAIT" else "Wait for pullback near support",
                },
                "volume_strength": {
                    "volume_ratio_20": round(vol_ratio, 2),
                    "high_volume_confirmation": high_volume_confirmation,
                    "description": f"Volume is {round(vol_ratio, 2)}x 20-candle average",
                },
                "risk_rating": risk_rating,
                "volatility_20_pct": round(volatility_20_pct, 2),
                "risk_reward_guard": {
                    "drawdown_50_pct": drawdown_50_pct,
                    "risk_reward_ratio": "1:1.8",
                },
                "ltp_change": {
                    "current_price": current_price,
                    "return_1_pct": round(float(full_last_row.get("return_1", 0.0)) * 100.0, 2),
                }
            }
        }
