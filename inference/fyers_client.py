"""
Fyers API Client Wrapper & Rolling Live Candle Buffer.
Handles auth code flow, access token persistence, real-time quote fetching, historical candle fetching, and schema normalization.
Provides automatic daily detection and auto-deletion of expired 24h Fyers access tokens from .env file,
integrated with official FyersTokenManager for automatic refresh-token renewal.
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd

from config.settings import FYERS, DATA, BASE_DIR
from services.fyers_auth import get_token_manager, FYERS_AUTHENTICATED

logger = logging.getLogger(__name__)


def _save_env_key(key: str, value: str):
    """Saves or updates key=value in ml_service/.env file. If value is empty, removes key line."""
    env_path = BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()

    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            found = True
            if value.strip():
                new_lines.append(f"{key}={value.strip()}\n")
            # If value is empty, skip line to delete it
        else:
            new_lines.append(line)

    if not found and value.strip():
        new_lines.append(f"{key}={value.strip()}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    logger.info("Updated %s in .env file.", key)


def _is_token_expired_error(res: dict) -> bool:
    """Checks if a Fyers API response indicates an expired or invalid token error."""
    if not isinstance(res, dict):
        return False
    if res.get("s") == "error":
        msg = str(res.get("message", "")).lower()
        code = res.get("code")
        if code in [-14, 401, 403] or "token" in msg or "expired" in msg or "invalid" in msg or "auth" in msg:
            return True
    return False


class FyersLiveClient:
    """Wrapper around fyers_apiv3 library with automatic token validation and refresh-token renewal."""

    def __init__(self):
        self.live_dir = DATA.live_dir
        self.live_dir.mkdir(parents=True, exist_ok=True)
        self.is_authenticated = False
        self.fyers_model = None
        self.token_manager = get_token_manager()

        self.reload_and_init()

    def clear_expired_token(self):
        """Automatically removes expired FYERS_ACCESS_TOKEN from .env and resets client state."""
        _save_env_key("FYERS_ACCESS_TOKEN", "")
        self.access_token = ""
        self.is_authenticated = False
        self.fyers_model = None
        FYERS.reload()
        logger.warning("Fyers access token was expired/invalid. Automatically deleted FYERS_ACCESS_TOKEN from .env file.")

    def reload_and_init(self):
        FYERS.reload()
        self.app_id = FYERS.app_id
        self.secret_key = FYERS.secret_key

        # Verify or refresh token via TokenManager
        auth_status = self.token_manager.reload_and_verify()
        self.access_token = self.token_manager.access_token

        if self.app_id and self.access_token:
            try:
                from fyers_apiv3 import fyersModel
                model = fyersModel.FyersModel(
                    client_id=self.app_id,
                    is_async=False,
                    token=self.access_token,
                    log_path=str(DATA.live_dir)
                )

                # Validate token with test quote call
                res = model.quotes({"symbols": "NSE:WIPRO-EQ"})
                if _is_token_expired_error(res):
                    logger.warning("Stored Fyers access token is expired. Attempting token refresh...")
                    if self.token_manager.refresh_access_token():
                        self.access_token = self.token_manager.access_token
                        model = fyersModel.FyersModel(
                            client_id=self.app_id,
                            is_async=False,
                            token=self.access_token,
                            log_path=str(DATA.live_dir)
                        )
                        self.fyers_model = model
                        self.is_authenticated = True
                        logger.info("Fyers API live client refreshed & re-authenticated successfully!")
                        return
                    else:
                        self.clear_expired_token()
                else:
                    self.fyers_model = model
                    self.is_authenticated = True
                    logger.info("Fyers API live client authenticated & initialized successfully with App ID: %s", self.app_id)
            except Exception as e:
                logger.warning("Fyers API initialization check failed (%s). Auto-clearing token.", e)
                self.clear_expired_token()
        else:
            self.is_authenticated = False
            self.fyers_model = None

    def generate_auth_url(self) -> str:
        """Generates clean Fyers OAuth 2.0 login URL with valid state parameter."""
        if not self.app_id or not self.secret_key:
            raise ValueError("FYERS_APP_ID and FYERS_SECRET_KEY must be set in .env before generating login URL.")

        clean_app_id = self.app_id.strip()
        clean_redirect_uri = FYERS.redirect_url.strip()
        encoded_redirect = urllib.parse.quote_plus(clean_redirect_uri)
        return f"https://api-t1.fyers.in/api/v3/generate-authcode?client_id={clean_app_id}&redirect_uri={encoded_redirect}&response_type=code&state=fyers_auth"

    def exchange_code_for_token(self, auth_code: str) -> str:
        """Exchanges auth_code for access_token and refresh_token via FyersTokenManager."""
        token = self.token_manager.exchange_code_for_tokens(auth_code)
        self.reload_and_init()
        return token

    def save_access_token_directly(self, access_token: str):
        """Directly sets and saves FYERS_ACCESS_TOKEN to server-side store and .env."""
        self.token_manager.save_tokens(access_token)
        self.reload_and_init()

    def fetch_live_quote(self, symbol: str) -> dict:
        """Fetches latest real-time quote for symbol. Symbol format e.g. 'WIPRO' or 'NSE:WIPRO-EQ'."""
        clean_symbol = symbol.replace("NSE:", "").replace("-EQ", "")
        fyers_symbol = f"NSE:{clean_symbol}-EQ"

        if self.is_authenticated and self.fyers_model:
            try:
                response = self.fyers_model.quotes({"symbols": fyers_symbol})
                if _is_token_expired_error(response):
                    logger.warning("Fyers quote response indicated expired token for %s. Attempting refresh...", clean_symbol)
                    if self.token_manager.refresh_access_token():
                        self.reload_and_init()
                        response = self.fyers_model.quotes({"symbols": fyers_symbol})
                    else:
                        self.clear_expired_token()

                if response.get("s") == "ok" and response.get("d"):
                    quote_data = response["d"][0]["v"]
                    return {
                        "ticker": clean_symbol,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "open": float(quote_data.get("open_price", quote_data.get("cmd", {}).get("c", 0))),
                        "high": float(quote_data.get("high_price", quote_data.get("cmd", {}).get("h", 0))),
                        "low": float(quote_data.get("low_price", quote_data.get("cmd", {}).get("l", 0))),
                        "close": float(quote_data.get("lp", quote_data.get("prev_close_price", 0))),
                        "volume": int(quote_data.get("volume", 0)),
                        "is_live_fyers": True
                    }
                else:
                    logger.warning("Fyers quote response for %s returned non-ok: %s", clean_symbol, response)
            except Exception as e:
                logger.error("Fyers quote fetch error for %s: %s", symbol, e)

        # Mock fallback quote if offline or token expired
        return self._generate_mock_quote(clean_symbol)

    def _generate_mock_quote(self, ticker: str) -> dict:
        base_prices = {"WIPRO": 178.5, "RELIANCE": 2900.0, "TCS": 3800.0, "ADANIENT": 1840.0, "TATASTEEL": 160.0, "EICHERMOT": 7833.5}
        base = base_prices.get(ticker, 500.0)
        noise = float(np.random.normal(0, base * 0.005))
        current_price = max(1.0, round(base + noise, 2))

        return {
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "open": round(current_price * 0.998, 2),
            "high": round(current_price * 1.005, 2),
            "low": round(current_price * 0.995, 2),
            "close": current_price,
            "volume": int(np.random.randint(100000, 2000000)),
            "is_live_fyers": False
        }

    def fetch_historical_candles(self, ticker: str, days: int = 60) -> pd.DataFrame:
        """Fetches daily or intraday candles (based on DATA.interval) for rolling feature calculation."""
        clean_symbol = ticker.replace("NSE:", "").replace("-EQ", "")
        fyers_symbol = f"NSE:{clean_symbol}-EQ"

        res_map = {"15m": "15", "30m": "30", "5m": "5", "60m": "60", "1d": "D", "d": "D"}
        fyers_res = res_map.get(str(DATA.interval).lower(), "15")

        if self.is_authenticated and self.fyers_model:
            try:
                to_date = datetime.now(timezone.utc)
                from_date = to_date - timedelta(days=days)
                data = {
                    "symbol": fyers_symbol,
                    "resolution": fyers_res,
                    "date_format": "1",
                    "range_from": from_date.strftime("%Y-%m-%d"),
                    "range_to": to_date.strftime("%Y-%m-%d"),
                    "cont_flag": "1"
                }
                response = self.fyers_model.history(data=data)
                if _is_token_expired_error(response):
                    logger.warning("Fyers history response indicated expired token. Attempting refresh...")
                    if self.token_manager.refresh_access_token():
                        self.reload_and_init()
                        response = self.fyers_model.history(data=data)
                    else:
                        self.clear_expired_token()

                if response.get("s") == "ok" and response.get("candles"):
                    df = pd.DataFrame(response["candles"], columns=["epoch", "Open", "High", "Low", "Close", "Volume"])
                    date_fmt = "%Y-%m-%d %H:%M" if fyers_res != "D" else "%Y-%m-%d"
                    df["Date"] = pd.to_datetime(df["epoch"], unit="s").dt.strftime(date_fmt)
                    df["Ticker"] = clean_symbol
                    return df[["Ticker", "Date", "Open", "High", "Low", "Close", "Volume"]]
                else:
                    logger.warning("Fyers history response for %s returned non-ok: %s", clean_symbol, response)
            except Exception as e:
                logger.error("Error fetching Fyers history for %s: %s", ticker, e)

        # Load cached historical slice from raw preprocessed CSV if available
        return self._load_cached_slice(clean_symbol, days=days)

    def _load_cached_slice(self, ticker: str, days: int = 60) -> pd.DataFrame:
        if DATA.raw_data_path.exists():
            df = pd.read_csv(DATA.raw_data_path)
            sub = df[df["Ticker"] == ticker].tail(days)
            if not sub.empty:
                sub = sub[["Ticker", "Date", "Open", "High", "Low", "Close", "Volume"]].copy()
                return sub

        # Generate synthetic fallback candles if CSV not accessible
        rng = pd.date_range(end=datetime.now(timezone.utc), periods=days, freq=DATA.interval)
        np.random.seed(abs(hash(ticker)) % 100000)
        base = 100.0 + (abs(hash(ticker)) % 3000)
        price = base * np.exp(np.cumsum(np.random.normal(0, 0.015, days)))
        return pd.DataFrame({
            "Ticker": ticker,
            "Date": rng.strftime("%Y-%m-%d %H:%M"),
            "Open": price * 0.998,
            "High": price * 1.01,
            "Low": price * 0.99,
            "Close": price,
            "Volume": np.random.randint(10000, 500000, days)
        })

    def update_rolling_buffer(self, ticker: str) -> Path:
        """Pulls latest history & quote, updates local Parquet buffer in data/live/."""
        candles_df = self.fetch_historical_candles(ticker, days=FYERS.live_buffer_days)
        latest_quote = self.fetch_live_quote(ticker)

        date_fmt = "%Y-%m-%d %H:%M" if DATA.interval != "1d" else "%Y-%m-%d"
        quote_date = datetime.now(timezone.utc).strftime(date_fmt)

        if not candles_df.empty:
            candles_df["Date"] = pd.to_datetime(candles_df["Date"].astype(str), format="mixed", errors="coerce").dt.strftime(date_fmt).fillna(candles_df["Date"].astype(str))

        if candles_df.empty or candles_df.iloc[-1]["Date"] != quote_date:
            new_row = pd.DataFrame([{
                "Ticker": ticker,
                "Date": quote_date,
                "Open": latest_quote["open"],
                "High": latest_quote["high"],
                "Low": latest_quote["low"],
                "Close": latest_quote["close"],
                "Volume": latest_quote["volume"]
            }])
            candles_df = pd.concat([candles_df, new_row], ignore_index=True)
        else:
            # Update last bar
            candles_df.iloc[-1, candles_df.columns.get_loc("Close")] = latest_quote["close"]
            candles_df.iloc[-1, candles_df.columns.get_loc("High")] = max(candles_df.iloc[-1]["High"], latest_quote["high"])
            candles_df.iloc[-1, candles_df.columns.get_loc("Low")] = min(candles_df.iloc[-1]["Low"], latest_quote["low"])
            candles_df.iloc[-1, candles_df.columns.get_loc("Volume")] = latest_quote["volume"]

        out_path = self.live_dir / f"{ticker}_live.parquet"
        candles_df.to_parquet(out_path, index=False)
        return out_path
