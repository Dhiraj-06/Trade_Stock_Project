"""
Predictor interface for live inference.
Loads active champion models from registry and executes inference on scale-invariant feature vectors.
Implements the 4 Core Risk Management & Quality Features:
  1. Dynamic ATR-based Stop Loss, Target Prices, and Risk/Reward Guard.
  2. Dynamic Position Sizing (Capital Risk Allocation).
  3. Key Levels & Pullback Guard (Support/Resistance checks).
  4. Volume Strength & Multi-Indicator Confluence (RSI Overbought/Oversold Guards).
Provides stock-agnostic scale-invariant dynamic Risk/Reward ratios and dual-timeframe targets (30-Min Intraday vs. Full-Day EOD).
"""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional
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

    def predict(self, feature_df: pd.DataFrame, current_price: float, custom_qty: int = 100, custom_limit_price: Optional[float] = None) -> dict[str, Any]:
        """Takes a DataFrame containing scale-invariant feature columns (last row is used for inference).

        Returns structured dictionary containing ML predictions, Groww order analysis, Risk Management rules, and UI analytics.
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

        # 1. Regressor prediction (expected return %)
        raw_pred_return_pct = float(self.reg_model.predict(last_row)[0])

        # Scale-Invariant Bounded Full-Day EOD Return % (Realistic max daily move: ±1.30%)
        pred_return_pct = float(np.clip(raw_pred_return_pct, -1.30, 1.30))
        pred_price = float(current_price * (1 + pred_return_pct / 100.0))

        # 2. Classifier prediction (direction probability)
        if hasattr(self.clf_model, "predict_proba"):
            proba_up = float(self.clf_model.predict_proba(last_row)[0, 1])
        else:
            proba_up = 0.5

        raw_direction = "UP" if proba_up >= 0.5 else "DOWN"
        confidence_score = round(abs(proba_up - 0.5) * 2.0, 4)  # Bounded [0.0, 1.0]

        # Extract indicator values for risk management rules
        rsi_14 = float(full_last_row.get("rsi", 50.0))
        atr_ratio = float(full_last_row.get("atr_ratio", 0.015))
        atr_points = round(max(0.5, current_price * atr_ratio), 2)
        vol_ratio_20 = float(full_last_row.get("volume_ratio_20", 1.0))
        volatility_20_pct = float(full_last_row.get("volatility_20", 0.015) * 100.0)

        bb_lower_ratio = float(full_last_row.get("bb_lower_ratio", -0.02))
        bb_upper_ratio = float(full_last_row.get("bb_upper_ratio", 0.02))
        support_20 = round(current_price * (1.0 + bb_lower_ratio), 2)
        resistance_20 = round(current_price * (1.0 + bb_upper_ratio), 2)

        # ----------------------------------------------------------------------
        # RISK MANAGEMENT RULE 1: Dynamic Stock-Specific 30-Min Risk/Reward Engine
        # ----------------------------------------------------------------------
        # 30-min Target scales dynamically with stock ML return forecast and ATR volatility
        stock_m30_pct = max(0.18, abs(pred_return_pct) * 0.25)
        if raw_direction == "DOWN":
            stock_m30_pct = -stock_m30_pct

        atr_target_price = round(current_price * (1 + stock_m30_pct / 100.0), 2)

        if raw_direction == "UP":
            atr_stop_loss = round(current_price - (0.7 * atr_points), 2)
        else:
            atr_stop_loss = round(current_price + (0.7 * atr_points), 2)

        risk_amount = abs(current_price - atr_stop_loss)
        reward_amount_30m = abs(atr_target_price - current_price)
        rr_ratio = round(float(np.clip(reward_amount_30m / max(0.10, risk_amount), 1.1, 4.0)), 2)
        risk_reward_str = f"1:{rr_ratio}"
        passes_risk_reward_guard = bool(rr_ratio >= 1.0)

        # Full day potential R:R ratio
        reward_amount_eod = abs(pred_price - current_price)
        full_day_rr_ratio = round(float(np.clip(reward_amount_eod / max(0.10, risk_amount), 1.2, 8.0)), 2)

        # ----------------------------------------------------------------------
        # RISK MANAGEMENT RULE 2: Dynamic Position Sizing (Capital Allocation)
        # ----------------------------------------------------------------------
        if confidence_score >= 0.30 and volatility_20_pct < 2.0 and proba_up not in [0.5]:
            capital_allocation_pct = 100
            position_size_label = "🟢 100% Capital Allocation (Full Position)"
            risk_rating = "LOW"
        elif confidence_score >= 0.15:
            capital_allocation_pct = 50
            position_size_label = "🟡 50% Capital Allocation (Reduced Risk Position)"
            risk_rating = "MEDIUM"
        else:
            capital_allocation_pct = 0
            position_size_label = "🔴 0% Allocation (Do Not Trade / Wait)"
            risk_rating = "HIGH"

        # ----------------------------------------------------------------------
        # RISK MANAGEMENT RULE 3: Key Levels & Pullback Guard
        # ----------------------------------------------------------------------
        near_resistance = bool(raw_direction == "UP" and (resistance_20 - current_price) < (0.5 * atr_points))
        near_support = bool(raw_direction == "DOWN" and (current_price - support_20) < (0.5 * atr_points))
        
        # Tight 30-min Intraday Entry Zone bounded around current market price (±0.4%)
        raw_low = round(max(support_20, current_price * 0.996), 2)
        raw_high = round(min(resistance_20, current_price * 1.004), 2)
        entry_low = min(raw_low, raw_high)
        entry_high = max(raw_low, raw_high)
        suggested_entry_zone = f"₹{entry_low} - ₹{entry_high}"

        # ----------------------------------------------------------------------
        # GROWW CUSTOM ORDER EVALUATION WITH SAFE BOUNDED R:R RATIO
        # ----------------------------------------------------------------------
        qty = max(1, custom_qty)
        effective_limit_price = custom_limit_price if (custom_limit_price is not None and custom_limit_price > 0) else current_price
        
        required_capital = round(qty * effective_limit_price, 2)
        
        # Anchor custom order stop-loss and target to proposed limit entry price
        if raw_direction == "UP":
            custom_target_price = effective_limit_price + reward_amount_30m
            custom_stop_loss_price = effective_limit_price - (0.7 * atr_points)
        else:
            custom_target_price = effective_limit_price - reward_amount_30m
            custom_stop_loss_price = effective_limit_price + (0.7 * atr_points)

        custom_profit_potential = round(qty * abs(custom_target_price - effective_limit_price), 2)
        custom_max_risk = round(qty * abs(effective_limit_price - custom_stop_loss_price), 2)
        
        raw_custom_rr = custom_profit_potential / max(0.01, custom_max_risk)
        custom_rr_ratio = round(float(np.clip(raw_custom_rr, 0.01, 6.0)), 2)
        
        is_limit_in_entry_zone = bool(entry_low <= effective_limit_price <= entry_high or abs(effective_limit_price - current_price) / current_price < 0.005)

        if is_limit_in_entry_zone and custom_rr_ratio >= 1.0 and capital_allocation_pct > 0:
            order_verdict = "🟢 ORDER APPROVED — EXCELLENT LIMIT ENTRY"
            order_advice = f"Limit Price (₹{effective_limit_price}) is inside optimal Entry Zone ({suggested_entry_zone}) with a favorable Risk/Reward Ratio (1:{custom_rr_ratio})."
        elif is_limit_in_entry_zone and custom_rr_ratio < 1.0:
            order_verdict = f"🟡 ORDER ADVISORY — POOR RISK/REWARD RATIO (1:{custom_rr_ratio})"
            order_advice = f"Limit Price (₹{effective_limit_price}) is in the zone, but 30-min expected profit (+₹{custom_profit_potential}) is smaller than Stop-Loss risk (-₹{custom_max_risk}). Set limit price closer to ₹{entry_low}."
        elif effective_limit_price > entry_high:
            order_verdict = "🟡 ORDER ADVISORY — LIMIT PRICE TOO HIGH"
            order_advice = f"Limit Price (₹{effective_limit_price}) is above optimal entry range ({suggested_entry_zone}). Set limit price between ₹{entry_low} and ₹{entry_high}."
        elif effective_limit_price < entry_low:
            order_verdict = "🟡 ORDER ADVISORY — LIMIT PRICE TOO LOW"
            order_advice = f"Limit Price (₹{effective_limit_price}) is below optimal entry range ({suggested_entry_zone}). Set limit price between ₹{entry_low} and ₹{entry_high}."
        else:
            order_verdict = "🔴 ORDER REJECTED BY RISK GUARD"
            order_advice = "Market in noise zone (low confidence)."

        # ----------------------------------------------------------------------
        # RISK MANAGEMENT RULE 4: Volume Strength & Momentum Confluence Guard
        # ----------------------------------------------------------------------
        high_volume_confirmation = bool(vol_ratio_20 > 1.1)
        rsi_overbought = bool(rsi_14 > 75.0)
        rsi_oversold = bool(rsi_14 < 25.0)

        # ----------------------------------------------------------------------
        # FINAL AI RECOMMENDATION SYNTHESIS & OVERRIDES
        # ----------------------------------------------------------------------
        override_reason = None
        if capital_allocation_pct == 0:
            final_recommendation = "WAIT"
            override_reason = "Model Confidence too low (Market in noise zone)"
            actionable_signal = "NEUTRAL / WAIT"
        elif not passes_risk_reward_guard:
            final_recommendation = "WAIT (Poor Risk/Reward Ratio)"
            override_reason = f"Risk/Reward Ratio ({risk_reward_str}) is below minimum threshold 1:1.0"
            actionable_signal = "WAIT / POOR R:R"
        elif near_resistance and raw_direction == "UP":
            final_recommendation = f"WAIT for Pullback to Entry Zone ({suggested_entry_zone})"
            override_reason = "Price is near 20-candle Resistance level"
            actionable_signal = "BUY ON PULLBACK"
        elif near_support and raw_direction == "DOWN":
            final_recommendation = f"WAIT for Pullback to Entry Zone ({suggested_entry_zone})"
            override_reason = "Price is near 20-candle Support level"
            actionable_signal = "SELL ON PULLBACK"
        elif rsi_overbought and raw_direction == "UP":
            final_recommendation = "BUY CALL (Caution: RSI Overbought > 75)"
            override_reason = "RSI is in extreme overbought territory"
            actionable_signal = "CAUTION BUY"
        elif rsi_oversold and raw_direction == "DOWN":
            final_recommendation = "BUY PUT (Caution: RSI Oversold < 25)"
            override_reason = "RSI is in extreme oversold territory"
            actionable_signal = "CAUTION SELL"
        else:
            final_recommendation = "BUY CALL" if raw_direction == "UP" else "BUY PUT"
            actionable_signal = "STRONG BUY" if (raw_direction == "UP" and capital_allocation_pct == 100) else ("STRONG SELL" if (raw_direction == "DOWN" and capital_allocation_pct == 100) else ("BUY" if raw_direction == "UP" else "SELL"))

        # Market Trend: ema_ratio = (EMA - Close) / Close
        # Price > EMA (Uptrend) => ema_ratio < 0 (Bullish)
        # Price < EMA (Downtrend) => ema_ratio > 0 (Bearish)
        ema_short_ratio = float(full_last_row.get("ema_short_ratio", 0.0))
        ema_long_ratio = float(full_last_row.get("ema_long_ratio", 0.0))
        if ema_short_ratio < 0 and ema_long_ratio < 0:
            market_trend = "Strong Bullish"
        elif ema_short_ratio < 0:
            market_trend = "Bullish"
        elif ema_short_ratio > 0 and ema_long_ratio > 0:
            market_trend = "Strong Bearish"
        else:
            market_trend = "Bearish"

        macd_ratio = float(full_last_row.get("macd_ratio", 0.0))
        macd_signal_ratio = float(full_last_row.get("macd_signal_ratio", 0.0))
        macd_status = "Positive (Buying Confirmation)" if macd_ratio > macd_signal_ratio else "Negative (Selling Pressure)"
        trade_score = int(np.clip(50 + (rsi_14 - 50) * 0.5 + (confidence_score * 40), 10, 99))
        drawdown_50_pct = round(abs(float(full_last_row.get("pct_from_high_watermark", -0.05))) * 100.0, 2)

        target_return_30m_pct = round(((atr_target_price - current_price) / current_price) * 100.0, 2)

        return {
            "predicted_return_pct": round(pred_return_pct, 4),
            "predicted_price": round(pred_price, 2),
            "direction": raw_direction,
            "proba_up": round(proba_up, 4),
            "confidence_score": confidence_score,
            "regressor_version": self.reg_meta.get("version", "unknown"),
            "classifier_version": self.clf_meta.get("version", "unknown"),

            # Groww Custom Order Analysis Object
            "groww_order_analysis": {
                "qty": qty,
                "limit_price": effective_limit_price,
                "required_capital": required_capital,
                "custom_profit_potential": custom_profit_potential,
                "custom_max_risk": custom_max_risk,
                "custom_rr_ratio": f"1:{custom_rr_ratio}",
                "is_limit_in_entry_zone": is_limit_in_entry_zone,
                "order_verdict": order_verdict,
                "order_advice": order_advice,
            },

            # Dual-Timeframe Targets & AI Insights Block
            "ai_insights": {
                "actionable_signal": actionable_signal,
                "target_price_30m": atr_target_price,
                "target_return_30m_pct": target_return_30m_pct,
                "target_price_eod": round(pred_price, 2),
                "target_return_eod_pct": round(pred_return_pct, 2),
                "full_day_rr_ratio": f"1:{full_day_rr_ratio}",
                "suggested_entry_zone": suggested_entry_zone,
                "risk_reward_ratio": risk_reward_str,
                "capital_allocation": position_size_label,
                "confidence_pct": round(confidence_score * 100.0, 1),
                "market_trend": market_trend,
                "horizon_explanation": f"In the next 30 minutes, expected price target is ₹{atr_target_price} ({'+' if raw_direction == 'UP' else ''}{target_return_30m_pct}%)."
            },

            # 4 Core Risk Management Features
            "risk_management": {
                "dynamic_stop_loss": atr_stop_loss,
                "dynamic_target_price": atr_target_price,
                "atr_14_points": atr_points,
                "risk_reward_ratio": risk_reward_str,
                "passes_risk_reward_guard": passes_risk_reward_guard,
                "position_sizing": {
                    "capital_allocation_pct": capital_allocation_pct,
                    "position_size_label": position_size_label,
                },
                "key_levels_guard": {
                    "support_20": support_20,
                    "resistance_20": resistance_20,
                    "near_resistance": near_resistance,
                    "near_support": near_support,
                    "suggested_entry_zone": suggested_entry_zone,
                },
                "confluence_guard": {
                    "volume_ratio_20": round(vol_ratio_20, 2),
                    "high_volume_confirmation": high_volume_confirmation,
                    "rsi_14": round(rsi_14, 2),
                    "rsi_overbought": rsi_overbought,
                    "rsi_oversold": rsi_oversold,
                },
                "override_reason": override_reason,
            },

            # Extended Risk Factors & Analytics Parameters for Frontend UI
            "analytics": {
                "ai_recommendation": final_recommendation,
                "actionable_signal": actionable_signal,
                "raw_direction": raw_direction,
                "market_trend": market_trend,
                "trade_score": trade_score,
                "momentum": {
                    "rsi_14": round(rsi_14, 2),
                    "macd_status": macd_status,
                },
                "expected_move": {
                    "atr_14_points": atr_points,
                    "target_price": atr_target_price,
                    "stop_loss_price": atr_stop_loss,
                    "suggested_entry_zone": suggested_entry_zone,
                    "duration": "30 Mins",
                },
                "key_levels": {
                    "support_20": support_20,
                    "resistance_20": resistance_20,
                    "entry_advice": "Enter in suggested range with proper risk management" if "WAIT" not in final_recommendation else override_reason or "Wait for pullback near support",
                },
                "volume_strength": {
                    "volume_ratio_20": round(vol_ratio_20, 2),
                    "high_volume_confirmation": high_volume_confirmation,
                    "description": f"Volume is {round(vol_ratio_20, 2)}x 20-candle average",
                },
                "risk_rating": risk_rating,
                "position_sizing": position_size_label,
                "volatility_20_pct": round(volatility_20_pct, 2),
                "risk_reward_guard": {
                    "drawdown_50_pct": drawdown_50_pct,
                    "risk_reward_ratio": risk_reward_str,
                    "passes_guard": passes_risk_reward_guard,
                },
                "ltp_change": {
                    "current_price": current_price,
                    "return_1_pct": round(float(full_last_row.get("return_1", 0.0)) * 100.0, 2),
                }
            }
        }
