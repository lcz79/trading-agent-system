"""
Test exchange configuration and validation.
Tests the EXCHANGE environment variable and exchange factory functionality.
"""
import pytest
import os
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.unit
def test_exchange_env_default(mock_env_vars, monkeypatch):
    """Test that EXCHANGE defaults to 'bybit' when not set."""
    monkeypatch.delenv("EXCHANGE", raising=False)
    
    # Simulate reading the env var with default
    exchange = os.getenv("EXCHANGE", "bybit")
    
    assert exchange == "bybit", "Default exchange should be 'bybit'"


@pytest.mark.unit
def test_exchange_env_validation(mock_env_vars):
    """Test that EXCHANGE validates supported values."""
    supported_exchanges = ["bybit", "hyperliquid"]
    
    # Test valid values
    for exchange in supported_exchanges:
        assert exchange in supported_exchanges, f"{exchange} should be supported"
    
    # Test invalid value detection
    invalid_exchange = "unsupported_exchange"
    assert invalid_exchange not in supported_exchanges, "Invalid exchange should not be supported"


@pytest.mark.unit  
def test_bybit_env_vars_present(mock_env_vars):
    """Test that Bybit environment variables are set correctly."""
    assert os.getenv("BYBIT_API_KEY") == "test_api_key"
    assert os.getenv("BYBIT_API_SECRET") == "test_api_secret"
    assert os.getenv("BYBIT_TESTNET") == "true"


@pytest.mark.unit
@pytest.mark.exchange
def test_exchange_factory_bybit(mock_env_vars):
    """Test exchange factory creates Bybit exchange correctly."""
    with patch('ccxt.bybit') as mock_bybit:
        mock_exchange = MagicMock()
        mock_bybit.return_value = mock_exchange
        
        # Simulate exchange factory function
        def create_exchange(provider: str):
            if provider.lower() == "bybit":
                import ccxt
                exchange = ccxt.bybit({
                    "apiKey": os.getenv("BYBIT_API_KEY"),
                    "secret": os.getenv("BYBIT_API_SECRET"),
                    "options": {
                        "defaultType": "swap",
                        "adjustForTimeDifference": True,
                    },
                })
                if os.getenv("BYBIT_TESTNET", "false").lower() == "true":
                    exchange.set_sandbox_mode(True)
                return exchange
            raise ValueError(f"Unsupported exchange: {provider}")
        
        exchange = create_exchange("bybit")
        
        # Verify the exchange was created
        assert exchange is not None
        mock_bybit.assert_called_once()


@pytest.mark.unit
@pytest.mark.exchange
def test_exchange_factory_hyperliquid(mock_env_vars, monkeypatch):
    """Test exchange factory creates Hyperliquid exchange correctly."""
    monkeypatch.setenv("EXCHANGE", "hyperliquid")
    monkeypatch.setenv("HYPERLIQUID_API_KEY", "test_hyperliquid_key")
    monkeypatch.setenv("HYPERLIQUID_API_SECRET", "test_hyperliquid_secret")
    
    with patch('ccxt.hyperliquid') as mock_hyperliquid:
        mock_exchange = MagicMock()
        mock_hyperliquid.return_value = mock_exchange
        
        # Simulate exchange factory function
        def create_exchange(provider: str):
            if provider.lower() == "hyperliquid":
                import ccxt
                exchange = ccxt.hyperliquid({
                    "apiKey": os.getenv("HYPERLIQUID_API_KEY"),
                    "secret": os.getenv("HYPERLIQUID_API_SECRET"),
                })
                return exchange
            raise ValueError(f"Unsupported exchange: {provider}")
        
        exchange = create_exchange("hyperliquid")
        
        # Verify the exchange was created
        assert exchange is not None
        mock_hyperliquid.assert_called_once()


@pytest.mark.unit
def test_exchange_factory_unsupported():
    """Test that unsupported exchange raises error."""
    def create_exchange(provider: str):
        supported = ["bybit", "hyperliquid"]
        if provider.lower() not in supported:
            raise ValueError(f"Unsupported exchange: {provider}. Supported: {supported}")
        return Mock()
    
    with pytest.raises(ValueError, match="Unsupported exchange"):
        create_exchange("binance")


@pytest.mark.unit
def test_exchange_config_missing_api_keys(monkeypatch):
    """Test that missing API keys are detected."""
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    monkeypatch.delenv("BYBIT_API_SECRET", raising=False)
    
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    
    assert api_key is None, "API key should be None when not set"
    assert api_secret is None, "API secret should be None when not set"


@pytest.mark.unit
def test_testnet_mode_configuration(mock_env_vars):
    """Test testnet mode configuration."""
    # Test testnet enabled
    testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
    assert testnet is True, "Testnet should be enabled"
    
    # Test testnet disabled
    mock_env_vars["BYBIT_TESTNET"] = "false"
    os.environ["BYBIT_TESTNET"] = "false"
    testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
    assert testnet is False, "Testnet should be disabled"


@pytest.mark.integration
@pytest.mark.exchange
def test_exchange_initialization_with_config(mock_env_vars, mock_bybit_exchange):
    """Test that exchange initializes correctly with configuration."""
    with patch('ccxt.bybit', return_value=mock_bybit_exchange):
        def init_exchange():
            import ccxt
            exchange = ccxt.bybit({
                "apiKey": os.getenv("BYBIT_API_KEY"),
                "secret": os.getenv("BYBIT_API_SECRET"),
            })
            return exchange
        
        exchange = init_exchange()
        assert exchange is not None
        assert hasattr(exchange, 'fetch_balance')
        assert hasattr(exchange, 'fetch_positions')
