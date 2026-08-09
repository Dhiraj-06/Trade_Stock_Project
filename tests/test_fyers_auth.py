"""
Unit and integration tests for FYERS Token Manager, Authentication State Machine, and Market Hours Engine.
"""
import pytest
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from services.fyers_auth import FyersTokenManager, FYERS_AUTHENTICATED, FYERS_REAUTH_REQUIRED
from services.fyers_market_data import get_market_status, MARKET_TZ
from api.app import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_market_hours_engine():
    # Test Saturday / Sunday -> CLOSED
    saturday = datetime(2026, 8, 8, 11, 0, tzinfo=MARKET_TZ)  # Sat
    assert get_market_status(saturday) == "CLOSED"

    # Test Monday pre-market (09:05 AM IST)
    mon_pre = datetime(2026, 8, 10, 9, 5, tzinfo=MARKET_TZ)  # Mon
    assert get_market_status(mon_pre) == "PRE_MARKET"

    # Test Monday market open (10:30 AM IST)
    mon_open = datetime(2026, 8, 10, 10, 30, tzinfo=MARKET_TZ)
    assert get_market_status(mon_open) == "OPEN"

    # Test Monday after hours (04:00 PM IST)
    mon_closed = datetime(2026, 8, 10, 16, 0, tzinfo=MARKET_TZ)
    assert get_market_status(mon_closed) == "CLOSED"


def test_token_manager_state_machine(tmp_path):
    store_file = tmp_path / "test_tokens.json"
    tm = FyersTokenManager()
    tm.token_store_path = store_file

    # Save valid tokens
    tm.save_tokens("test_access_token_123", "test_refresh_token_456", expires_in=3600)
    assert tm.is_access_token_valid() is True
    assert tm.status == FYERS_AUTHENTICATED

    # Verify status dictionary does NOT leak secret key or tokens
    info = tm.get_auth_status()
    assert "access_token" not in info
    assert "refresh_token" not in info
    assert "secret_key" not in info
    assert info["is_authenticated"] is True


def test_api_nifty50_market_endpoint():
    response = client.get("/api/market/nifty50")
    assert response.status_code == 200
    data = response.json()
    assert "symbol" in data
    assert "price" in data
    assert "change" in data
    assert "change_percent" in data
    assert "market_status" in data
    assert "auth_status" in data
