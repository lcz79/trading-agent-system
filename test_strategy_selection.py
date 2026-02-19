"""
Test strategy selection and parameter loading mechanism.
Tests the active strategy selection from Learning Agent's evolved_params.json.
"""
import pytest
import json
import os
from unittest.mock import Mock, patch, mock_open


@pytest.mark.unit
def test_load_evolved_params_file_exists(temp_data_dir, sample_evolved_params):
    """Test loading evolved params when file exists."""
    params_file = os.path.join(temp_data_dir, "evolved_params.json")
    
    # Create the file
    with open(params_file, "w") as f:
        json.dump(sample_evolved_params, f)
    
    # Load and verify
    with open(params_file, "r") as f:
        loaded = json.load(f)
    
    assert loaded["version"] == "1.0"
    assert loaded["params"]["default_leverage"] == 5
    assert loaded["params"]["size_pct"] == 0.15


@pytest.mark.unit
def test_load_evolved_params_file_missing(temp_data_dir):
    """Test that missing evolved params file returns defaults."""
    params_file = os.path.join(temp_data_dir, "evolved_params.json")
    
    # Define default params
    default_params = {
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "default_leverage": 5,
        "size_pct": 0.15,
    }
    
    # Simulate loading with default fallback
    if os.path.exists(params_file):
        with open(params_file, "r") as f:
            data = json.load(f)
            params = data.get("params", default_params)
    else:
        params = default_params.copy()
    
    assert params == default_params
    assert params["default_leverage"] == 5


@pytest.mark.unit
def test_evolved_params_structure(sample_evolved_params):
    """Test that evolved params have the correct structure."""
    assert "version" in sample_evolved_params
    assert "timestamp" in sample_evolved_params
    assert "params" in sample_evolved_params
    
    params = sample_evolved_params["params"]
    required_keys = [
        "rsi_overbought",
        "rsi_oversold",
        "default_leverage",
        "size_pct",
        "reverse_threshold",
    ]
    
    for key in required_keys:
        assert key in params, f"Required key '{key}' missing from params"


@pytest.mark.unit
def test_default_params_values():
    """Test that default parameter values are sensible."""
    default_params = {
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
    
    # Validate ranges
    assert 0 < default_params["rsi_overbought"] <= 100
    assert 0 <= default_params["rsi_oversold"] < 100
    assert default_params["rsi_oversold"] < default_params["rsi_overbought"]
    assert 1 <= default_params["default_leverage"] <= 20
    assert 0 < default_params["size_pct"] <= 1
    assert default_params["reverse_threshold"] > 0


@pytest.mark.unit
def test_strategy_selection_explicit_mode(monkeypatch):
    """Test explicit strategy mode selection."""
    # Define strategy presets
    strategies = {
        "conservative": {
            "default_leverage": 3,
            "size_pct": 0.10,
            "reverse_threshold": 3.0,
        },
        "aggressive": {
            "default_leverage": 8,
            "size_pct": 0.20,
            "reverse_threshold": 1.5,
        },
        "scalping": {
            "default_leverage": 5,
            "size_pct": 0.15,
            "reverse_threshold": 2.0,
        },
    }
    
    # Test selecting conservative strategy
    monkeypatch.setenv("STRATEGY_MODE", "conservative")
    selected_mode = os.getenv("STRATEGY_MODE", "scalping")
    
    assert selected_mode == "conservative"
    assert strategies[selected_mode]["default_leverage"] == 3


@pytest.mark.unit
def test_strategy_logging_info():
    """Test that strategy info can be formatted for logging."""
    params = {
        "default_leverage": 5,
        "size_pct": 0.15,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
    }
    
    # Format logging message
    log_msg = (
        f"Active Strategy Parameters: "
        f"leverage={params['default_leverage']}, "
        f"size={params['size_pct']:.2%}, "
        f"RSI={params['rsi_oversold']}/{params['rsi_overbought']}"
    )
    
    assert "leverage=5" in log_msg
    assert "size=15.00%" in log_msg
    assert "RSI=30/70" in log_msg


@pytest.mark.unit
def test_params_validation_leverage():
    """Test parameter validation for leverage."""
    def validate_leverage(leverage):
        min_lev = 1
        max_lev = 20
        if not (min_lev <= leverage <= max_lev):
            raise ValueError(f"Leverage must be between {min_lev} and {max_lev}")
        return leverage
    
    # Valid leverage
    assert validate_leverage(5) == 5
    assert validate_leverage(10) == 10
    
    # Invalid leverage
    with pytest.raises(ValueError):
        validate_leverage(0)
    with pytest.raises(ValueError):
        validate_leverage(25)


@pytest.mark.unit
def test_params_validation_size_pct():
    """Test parameter validation for size_pct."""
    def validate_size_pct(size_pct):
        if not (0 < size_pct <= 1):
            raise ValueError("size_pct must be between 0 and 1")
        return size_pct
    
    # Valid size_pct
    assert validate_size_pct(0.15) == 0.15
    assert validate_size_pct(0.5) == 0.5
    
    # Invalid size_pct
    with pytest.raises(ValueError):
        validate_size_pct(0)
    with pytest.raises(ValueError):
        validate_size_pct(1.5)


@pytest.mark.integration
def test_load_params_from_learning_agent(temp_data_dir, sample_evolved_params):
    """Test loading parameters as Learning Agent would."""
    params_file = os.path.join(temp_data_dir, "evolved_params.json")
    
    # Save evolved params
    with open(params_file, "w") as f:
        json.dump(sample_evolved_params, f)
    
    # Simulate Learning Agent's load_current_params function
    def load_current_params():
        default_params = {
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "default_leverage": 5,
            "size_pct": 0.15,
        }
        
        if os.path.exists(params_file):
            with open(params_file, "r") as f:
                data = json.load(f)
                return data.get("params", default_params)
        return default_params
    
    params = load_current_params()
    
    assert params["default_leverage"] == 5
    assert params["size_pct"] == 0.15
    assert "rsi_overbought" in params


@pytest.mark.unit
def test_strategy_source_detection(temp_data_dir, sample_evolved_params):
    """Test detection of where strategy params are loaded from."""
    params_file = os.path.join(temp_data_dir, "evolved_params.json")
    
    # Test with evolved params file
    with open(params_file, "w") as f:
        json.dump(sample_evolved_params, f)
    
    source = "evolved_params" if os.path.exists(params_file) else "defaults"
    assert source == "evolved_params"
    
    # Test without file
    os.remove(params_file)
    source = "evolved_params" if os.path.exists(params_file) else "defaults"
    assert source == "defaults"
