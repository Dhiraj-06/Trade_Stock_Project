"""
FYERS Real-Time Market Data Service & Market Hours Engine.
Handles Indian Stock Market timezone logic (Asia/Kolkata), exponential backoff reconnection,
runtime token expiration recovery, and real-time NIFTY 50 data streaming for backend endpoints.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from typing import Dict, Any

from services.fyers_auth import get_token_manager, FYERS_AUTHENTICATED
from config.settings import FYERS

logger = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("Asia/Kolkata")


def get_market_status(now_dt: datetime | None = None) -> str:
    """Calculates Indian Equity Market status based on Asia/Kolkata timezone."""
    if now_dt is None:
        now_dt = datetime.now(MARKET_TZ)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=MARKET_TZ)
    else:
        now_dt = now_dt.astimezone(MARKET_TZ)

    # Saturday (5) & Sunday (6) are market holidays
    if now_dt.weekday() >= 5:
        return "CLOSED"

    t = now_dt.time()
    pre_start = dtime(9, 0)
    open_start = dtime(9, 15)
    market_close = dtime(15, 30)

    if pre_start <= t < open_start:
        return "PRE_MARKET"
    elif open_start <= t <= market_close:
        return "OPEN"
    else:
        return "CLOSED"


class FyersMarketDataManager:
    """Server-side market data connection manager with exponential backoff and runtime token recovery."""

    def __init__(self):
        self.token_manager = get_token_manager()
        self.fyers_model = None
        self.retry_count = 0
        self.max_backoff_seconds = 30
        self.last_quote_cache: Dict[str, Any] = {}

    def _init_fyers_model(self) -> bool:
        """Initializes or refreshes the underlying FYERS SDK model instance."""
        if not self.token_manager.is_access_token_valid():
            logger.info("[INFO] Access token invalid/expired. Attempting token refresh...")
            if not self.token_manager.refresh_access_token():
                self.fyers_model = None
                return False

        try:
            from fyers_apiv3 import fyersModel
            model = fyersModel.FyersModel(
                client_id=FYERS.app_id,
                is_async=False,
                token=self.token_manager.access_token,
                log_path=str(FYERS.token_store_path.parent)
            )
            self.fyers_model = model
            self.retry_count = 0
            logger.info("[INFO] FYERS Market Data Model initialized successfully.")
            return True
        except Exception as e:
            logger.error("[ERROR] Failed to initialize FYERS Model: %s", e)
            self.fyers_model = None
            return False

    def fetch_quote_with_retry(self, symbol: str = "NSE:NIFTY50-INDEX") -> Dict[str, Any]:
        """Fetches live market quote for symbol using exponential backoff on disconnects and automatic token refresh on expiry."""
        clean_symbol = symbol if ":" in symbol else f"NSE:{symbol}-EQ"

        if not self.fyers_model:
            if not self._init_fyers_model():
                return self._fallback_quote(clean_symbol)

        backoff = min(2 ** self.retry_count, self.max_backoff_seconds)
        try:
            res = self.fyers_model.quotes({"symbols": clean_symbol})

            # Check if response indicates token expiration at runtime
            if isinstance(res, dict) and res.get("s") == "error":
                code = res.get("code")
                msg = str(res.get("message", "")).lower()
                if code in [-14, 401, 403] or "token" in msg or "expired" in msg:
                    logger.warning("[WARNING] Token expired during runtime. Refreshing FYERS token...")
                    if self.token_manager.refresh_access_token():
                        self._init_fyers_model()
                        res = self.fyers_model.quotes({"symbols": clean_symbol})

            if isinstance(res, dict) and res.get("s") == "ok" and res.get("d"):
                v = res["d"][0]["v"]
                lp = float(v.get("lp", v.get("prev_close_price", 0.0)))
                prev_close = float(v.get("prev_close_price", lp))
                chg = float(v.get("ch", lp - prev_close))
                chg_pct = float(v.get("chp", (chg / prev_close * 100.0) if prev_close else 0.0))

                quote_data = {
                    "symbol": clean_symbol,
                    "price": round(lp, 2),
                    "change": round(chg, 2),
                    "change_percent": round(chg_pct, 2),
                    "open": float(v.get("open_price", lp)),
                    "high": float(v.get("high_price", lp)),
                    "low": float(v.get("low_price", lp)),
                    "volume": int(v.get("volume", 0)),
                    "timestamp": datetime.now(MARKET_TZ).isoformat(),
                    "market_status": get_market_status(),
                    "auth_status": self.token_manager.status,
                    "is_live_fyers": True
                }
                self.last_quote_cache[clean_symbol] = quote_data
                self.retry_count = 0
                return quote_data
            else:
                logger.warning("[WARNING] FYERS quote fetch returned non-ok: %s", res)
                self.retry_count += 1
                time.sleep(min(backoff, 2))
        except Exception as e:
            logger.error("[ERROR] FYERS connection failed during quote fetch: %s", e)
            self.retry_count += 1
            time.sleep(min(backoff, 2))

        return self._fallback_quote(clean_symbol)

    def _fallback_quote(self, symbol: str) -> Dict[str, Any]:
        """Provides graceful fallback quote using cached price or baseline data when market is closed or unauthenticated."""
        if symbol in self.last_quote_cache:
            cached = self.last_quote_cache[symbol].copy()
            cached["is_live_fyers"] = False
            cached["market_status"] = get_market_status()
            cached["auth_status"] = self.token_manager.status
            return cached

        base = 24570.65 if "NIFTY50" in symbol else 500.0
        return {
            "symbol": symbol,
            "price": base,
            "change": 0.0,
            "change_percent": 0.0,
            "timestamp": datetime.now(MARKET_TZ).isoformat(),
            "market_status": get_market_status(),
            "auth_status": self.token_manager.status,
            "is_live_fyers": False
        }

    def get_nifty50_summary(self) -> Dict[str, Any]:
        """Returns clean NIFTY 50 market data payload for backend REST API endpoints."""
        quote = self.fetch_quote_with_retry("NSE:NIFTY50-INDEX")
        return {
            "symbol": quote["symbol"],
            "price": quote["price"],
            "change": quote["change"],
            "change_percent": quote["change_percent"],
            "timestamp": quote["timestamp"],
            "market_status": quote["market_status"],
            "auth_status": quote["auth_status"],
            "is_live": quote.get("is_live_fyers", False)
        }


# Global Singleton Market Data Manager
_market_data_manager_instance: FyersMarketDataManager | None = None

def get_market_data_manager() -> FyersMarketDataManager:
    global _market_data_manager_instance
    if _market_data_manager_instance is None:
        _market_data_manager_instance = FyersMarketDataManager()
    return _market_data_manager_instance
