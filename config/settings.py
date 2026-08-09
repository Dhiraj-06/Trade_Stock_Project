"""
Central configuration reader for the ML service.
Loads config/settings.yaml and environment variables.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent.parent
YAML_PATH = BASE_DIR / "config" / "settings.yaml"

def _load_yaml_config() -> dict:
    if YAML_PATH.exists():
        with open(YAML_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    return {}

_raw_config = _load_yaml_config()

@dataclass
class FyersSettings:
    app_id: str = os.getenv("FYERS_APP_ID", "").strip()
    secret_key: str = os.getenv("FYERS_SECRET_KEY", "").strip()
    access_token: str = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
    refresh_token: str = os.getenv("FYERS_REFRESH_TOKEN", "").strip()
    redirect_url: str = _raw_config.get("fyers", {}).get("redirect_url", "http://127.0.0.1:8000/fyers/callback")
    token_store_path: Path = BASE_DIR / "data" / "live" / "fyers_tokens.json"
    pin: str = os.getenv("FYERS_PIN", "").strip()
    totp_key: str = os.getenv("FYERS_TOTP_KEY", "").strip()
    polling_interval: int = _raw_config.get("fyers", {}).get("polling_interval_seconds", 60)
    live_buffer_days: int = _raw_config.get("fyers", {}).get("live_buffer_days", 60)

    def reload(self):
        load_dotenv(override=True)
        self.app_id = os.getenv("FYERS_APP_ID", "").strip()
        self.secret_key = os.getenv("FYERS_SECRET_KEY", "").strip()
        self.access_token = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
        self.refresh_token = os.getenv("FYERS_REFRESH_TOKEN", "").strip()
        self.pin = os.getenv("FYERS_PIN", "").strip()
        self.totp_key = os.getenv("FYERS_TOTP_KEY", "").strip()

@dataclass
class DataSettings:
    raw_data_path: Path = BASE_DIR / _raw_config.get("data", {}).get("raw_data_path", "data/raw/NIFTY50_Preprocessed.csv")
    processed_dir: Path = BASE_DIR / _raw_config.get("data", {}).get("processed_dir", "data/processed")
    live_dir: Path = BASE_DIR / _raw_config.get("data", {}).get("live_dir", "data/live")
    ticker_col: str = _raw_config.get("data", {}).get("ticker_col", "Ticker")
    date_col: str = _raw_config.get("data", {}).get("date_col", "Date")
    close_col: str = _raw_config.get("data", {}).get("close_col", "Close")
    interval: str = _raw_config.get("data", {}).get("interval", "15m")

@dataclass
class FeatureSettings:
    rsi_period: int = _raw_config.get("features", {}).get("rsi_period", 14)
    ema_short: int = _raw_config.get("features", {}).get("ema_short", 9)
    ema_long: int = _raw_config.get("features", {}).get("ema_long", 21)
    macd_fast: int = _raw_config.get("features", {}).get("macd_fast", 12)
    macd_slow: int = _raw_config.get("features", {}).get("macd_slow", 26)
    macd_signal: int = _raw_config.get("features", {}).get("macd_signal", 9)
    bb_period: int = _raw_config.get("features", {}).get("bb_period", 20)
    bb_std: float = _raw_config.get("features", {}).get("bb_std", 2.0)
    atr_period: int = _raw_config.get("features", {}).get("atr_period", 14)
    adx_period: int = _raw_config.get("features", {}).get("adx_period", 14)
    lag_periods: list[int] = field(default_factory=lambda: _raw_config.get("features", {}).get("lag_periods", [1, 2, 3, 5, 10]))
    rolling_windows: list[int] = field(default_factory=lambda: _raw_config.get("features", {}).get("rolling_windows", [5, 10, 20]))

@dataclass
class TrainingSettings:
    horizon_candles: int = _raw_config.get("training", {}).get("horizon_candles", 2)
    n_splits: int = _raw_config.get("training", {}).get("n_splits", 5)
    test_size_candles: int = _raw_config.get("training", {}).get("test_size_candles", 500)
    model_registry_dir: Path = BASE_DIR / _raw_config.get("training", {}).get("model_registry_dir", "models/registry")
    min_score_improvement: float = _raw_config.get("training", {}).get("min_score_improvement", 0.005)
    retrain_schedule_cron: str = _raw_config.get("training", {}).get("retrain_schedule_cron", "0 18 * * 1-5")

@dataclass
class DriftSettings:
    window_size: int = _raw_config.get("drift", {}).get("window_size", 50)
    mae_degradation_threshold: float = _raw_config.get("drift", {}).get("mae_degradation_threshold", 0.20)
    directional_acc_threshold: float = _raw_config.get("drift", {}).get("directional_acc_threshold", 0.52)

FYERS = FyersSettings()
DATA = DataSettings()
FEATURES = FeatureSettings()
TRAINING = TrainingSettings()
DRIFT = DriftSettings()