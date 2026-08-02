"""
Unit tests for inference/ticker_utils.py.
Verifies alias resolution (e.g. "Tata Steel" -> "TATASTEEL") and error handling for non-NIFTY50 tickers (e.g. "ZOMATO").
"""
import pytest
from inference.ticker_utils import normalize_and_validate_ticker


def test_valid_nifty50_ticker():
    assert normalize_and_validate_ticker("WIPRO") == "WIPRO"
    assert normalize_and_validate_ticker("wipro") == "WIPRO"
    assert normalize_and_validate_ticker("RELIANCE") == "RELIANCE"


def test_alias_resolution():
    assert normalize_and_validate_ticker("Tata Steel") == "TATASTEEL"
    assert normalize_and_validate_ticker("tata steel") == "TATASTEEL"
    assert normalize_and_validate_ticker("Infosys") == "INFY"
    assert normalize_and_validate_ticker("HDFC Bank") == "HDFCBANK"
    assert normalize_and_validate_ticker("Bajaj Auto") == "BAJAJ-AUTO"
    assert normalize_and_validate_ticker("M&M") == "M&M"
    assert normalize_and_validate_ticker("L&T") == "LT"


def test_invalid_non_nifty50_ticker():
    with pytest.raises(ValueError) as exc_info:
        normalize_and_validate_ticker("ZOMATO")
    assert "ZOMATO" in str(exc_info.value)
    assert "not a constituent of the NIFTY 50 universe" in str(exc_info.value)

    with pytest.raises(ValueError) as exc_info:
        normalize_and_validate_ticker("APPLE")
    assert "APPLE" in str(exc_info.value)
