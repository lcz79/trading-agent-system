"""
Pytest configuration and shared fixtures for Trading Agent System tests.
"""
import pytest
import json
import os
from unittest.mock import Mock, MagicMock
from typing import Dict, Any


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Fixture to set common environment variables for testing."""
    test_env = {
        "BYBIT_API_KEY": "test_api_key",
        "BYBIT_API_SECRET": "test_api_secret",
        "BYBIT_TESTNET": "true",
        "EXCHANGE": "bybit",
        "DEEPSEEK_API_KEY": "test_deepseek_key",
        "OPENAI_API_KEY": "test_openai_key",
        "COINGECKO_API_KEY": "test_coingecko_key",
        "MIN_CONFIDENCE": "60",
        "LEVERAGE_SCALP": "5",
        "SIZE_PCT": "0.15",
        "MAX_LEVERAGE": "10",
        "ENABLE_TRAILING_STOP": "true",
        "SCAN_SYMBOLS": "BTCUSDT,ETHUSDT,SOLUSDT",
    }
    for key, value in test_env.items():
        monkeypatch.setenv(key, value)
    return test_env


@pytest.fixture
def mock_bybit_exchange():
    """Mock CCXT Bybit exchange for testing."""
    exchange = MagicMock()
    exchange.fetch_balance.return_value = {
        "USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0}
    }
    exchange.fetch_positions.return_value = []
    exchange.fetch_ticker.return_value = {
        "symbol": "BTC/USDT:USDT",
        "last": 50000.0,
        "bid": 49999.0,
        "ask": 50001.0,
    }
    exchange.set_sandbox_mode = Mock()
    exchange.create_order = Mock(return_value={"id": "test_order_123", "status": "open"})
    return exchange


@pytest.fixture
def mock_hyperliquid_exchange():
    """Mock CCXT Hyperliquid exchange for testing."""
    exchange = MagicMock()
    exchange.fetch_balance.return_value = {
        "USDT": {"free": 1000.0, "used": 0.0, "total": 1000.0}
    }
    exchange.fetch_positions.return_value = []
    exchange.fetch_ticker.return_value = {
        "symbol": "BTC/USDT",
        "last": 50000.0,
        "bid": 49999.0,
        "ask": 50001.0,
    }
    exchange.create_order = Mock(return_value={"id": "test_order_456", "status": "open"})
    return exchange


@pytest.fixture
def sample_evolved_params():
    """Sample evolved parameters for testing."""
    return {
        "version": "1.0",
        "timestamp": "2024-01-01T00:00:00Z",
        "params": {
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "default_leverage": 5,
            "size_pct": 0.15,
            "reverse_threshold": 2.0,
            "atr_multiplier_sl": 2.0,
            "atr_multiplier_tp": 3.0,
            "min_rsi_for_long": 40,
            "max_rsi_for_short": 60,
        }
    }


@pytest.fixture
def sample_trading_state():
    """Sample trading state for testing."""
    return {
        "open_positions": {},
        "order_intents": {},
        "cooldowns": {},
        "last_update": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_position_data():
    """Sample position data for testing."""
    return {
        "symbol": "BTCUSDT",
        "side": "long",
        "size": 0.1,
        "entry_price": 50000.0,
        "current_price": 51000.0,
        "leverage": 5,
        "unrealized_pnl": 100.0,
        "roi_pct": 0.02,
    }


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return str(data_dir)


@pytest.fixture
def mock_trading_state_file(temp_data_dir):
    """Create a temporary trading_state.json file."""
    state_file = os.path.join(temp_data_dir, "trading_state.json")
    initial_state = {
        "open_positions": {},
        "order_intents": {},
        "cooldowns": {},
    }
    with open(state_file, "w") as f:
        json.dump(initial_state, f)
    return state_file


@pytest.fixture
def mock_evolved_params_file(temp_data_dir, sample_evolved_params):
    """Create a temporary evolved_params.json file."""
    params_file = os.path.join(temp_data_dir, "evolved_params.json")
    with open(params_file, "w") as f:
        json.dump(sample_evolved_params, f)
    return params_file


def pytest_configure(config):
    """Configure pytest with custom settings."""
    # Register custom markers
    config.addinivalue_line(
        "markers", "unit: Unit tests that don't require external dependencies"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests that may require mocked services"
    )
    config.addinivalue_line(
        "markers", "exchange: Tests that require exchange connectivity"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take a long time to run"
    )
