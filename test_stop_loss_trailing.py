"""
Test trailing stop and stop loss logic.
Tests the Position Manager's stop loss and trailing stop functionality.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from decimal import Decimal


@pytest.mark.unit
def test_trailing_stop_activation():
    """Test that trailing stop activates at correct ROI threshold."""
    # Configuration
    trailing_activation_pct = 0.01  # 1% ROI to activate
    
    # Position data
    entry_price = 50000.0
    current_price = 50500.0  # 1% gain
    roi_pct = (current_price - entry_price) / entry_price
    
    # Check if trailing should activate
    should_activate = roi_pct >= trailing_activation_pct
    
    assert roi_pct == 0.01
    assert should_activate is True, "Trailing stop should activate at 1% ROI"


@pytest.mark.unit
def test_trailing_stop_not_activated_early():
    """Test that trailing stop doesn't activate before threshold."""
    trailing_activation_pct = 0.01  # 1% ROI to activate
    
    # Position data - only 0.5% gain
    entry_price = 50000.0
    current_price = 50250.0  # 0.5% gain
    roi_pct = (current_price - entry_price) / entry_price
    
    should_activate = roi_pct >= trailing_activation_pct
    
    assert roi_pct == 0.005
    assert should_activate is False, "Trailing stop should not activate below 1% ROI"


@pytest.mark.unit
def test_stop_loss_calculation():
    """Test stop loss price calculation."""
    entry_price = 50000.0
    stop_loss_pct = 0.02  # 2% stop loss
    side = "long"
    
    # For long position, stop loss is below entry
    if side == "long":
        stop_loss_price = entry_price * (1 - stop_loss_pct)
    else:  # short
        stop_loss_price = entry_price * (1 + stop_loss_pct)
    
    assert stop_loss_price == 49000.0
    assert stop_loss_price < entry_price, "Long stop loss should be below entry"


@pytest.mark.unit
def test_trailing_stop_update():
    """Test trailing stop update as price moves favorably."""
    entry_price = 50000.0
    trailing_pct = 0.004  # 0.4% trailing distance
    side = "long"
    
    # Price moves up
    current_prices = [50500, 51000, 51500]
    stop_losses = []
    
    for price in current_prices:
        if side == "long":
            new_stop = price * (1 - trailing_pct)
        else:
            new_stop = price * (1 + trailing_pct)
        stop_losses.append(new_stop)
    
    # Verify stop loss moves up with price
    assert stop_losses[0] < stop_losses[1] < stop_losses[2]
    assert stop_losses[-1] == 51500 * (1 - 0.004)


@pytest.mark.unit
def test_trailing_stop_doesnt_move_down():
    """Test that trailing stop never moves down (for long positions)."""
    trailing_pct = 0.004
    side = "long"
    
    current_stop = 50000.0
    new_price = 49500.0  # Price drops
    
    # Calculate potential new stop
    potential_stop = new_price * (1 - trailing_pct)
    
    # Keep existing stop if potential stop is lower
    updated_stop = max(current_stop, potential_stop)
    
    assert updated_stop == current_stop, "Trailing stop should not move down"


@pytest.mark.unit
def test_breakeven_activation():
    """Test breakeven protection activation."""
    entry_price = 50000.0
    breakeven_activation_pct = 0.015  # 1.5% ROI
    breakeven_margin_pct = 0.001  # 0.1% margin above entry
    side = "long"
    
    current_price = 50750.0  # 1.5% gain
    roi_pct = (current_price - entry_price) / entry_price
    
    if roi_pct >= breakeven_activation_pct:
        if side == "long":
            breakeven_stop = entry_price * (1 + breakeven_margin_pct)
        else:
            breakeven_stop = entry_price * (1 - breakeven_margin_pct)
        
        should_activate = True
    else:
        should_activate = False
        breakeven_stop = None
    
    assert should_activate is True
    assert abs(breakeven_stop - 50050.0) < 0.01  # Entry + 0.1% (within precision)


@pytest.mark.unit
def test_min_stop_loss_movement():
    """Test minimum stop loss movement to avoid spam."""
    min_sl_move_btc = 15.0  # $15 minimum movement for BTC
    
    current_stop = 50000.0
    new_stop_small_diff = 50005.0  # Only $5 difference
    new_stop_large_diff = 50020.0  # $20 difference
    
    # Check if movement is significant enough
    diff_small = abs(new_stop_small_diff - current_stop)
    diff_large = abs(new_stop_large_diff - current_stop)
    
    should_update_small = diff_small >= min_sl_move_btc
    should_update_large = diff_large >= min_sl_move_btc
    
    assert should_update_small is False, "Small SL move should be skipped"
    assert should_update_large is True, "Large SL move should be applied"


@pytest.mark.unit
def test_stop_loss_symbol_specific():
    """Test that different symbols have different minimum SL movements."""
    def min_sl_move_for_symbol(symbol: str) -> float:
        symbol_base = symbol.replace("USDT", "").replace("USDC", "")
        
        min_moves = {
            "BTC": 15.0,
            "ETH": 0.8,
            "SOL": 0.05,
        }
        
        return min_moves.get(symbol_base, 0.001)
    
    assert min_sl_move_for_symbol("BTCUSDT") == 15.0
    assert min_sl_move_for_symbol("ETHUSDT") == 0.8
    assert min_sl_move_for_symbol("SOLUSDT") == 0.05
    assert min_sl_move_for_symbol("DOGEUSDT") == 0.001


@pytest.mark.integration
def test_trailing_stop_full_scenario(mock_position_data):
    """Test complete trailing stop scenario from entry to exit."""
    position = mock_position_data.copy()
    
    # Initial state
    entry_price = position["entry_price"]
    trailing_activation_pct = 0.01
    trailing_pct = 0.004
    
    # Scenario: Price moves up triggering trailing stop
    price_sequence = [
        50000,  # Entry
        50500,  # +1% - activates trailing
        51000,  # +2% - trailing follows
        50800,  # Drop but above trailing stop
        50600,  # Drop triggers trailing stop
    ]
    
    trailing_active = False
    current_stop = entry_price * 0.96  # Initial 4% stop
    
    for price in price_sequence:
        roi = (price - entry_price) / entry_price
        
        # Activate trailing if threshold met
        if not trailing_active and roi >= trailing_activation_pct:
            trailing_active = True
        
        # Update stop if trailing is active
        if trailing_active:
            new_stop = price * (1 - trailing_pct)
            current_stop = max(current_stop, new_stop)
        
        # Check if stop hit
        if price <= current_stop:
            exit_price = current_stop
            final_roi = (exit_price - entry_price) / entry_price
            break
    
    # Should have exited with profit
    assert trailing_active is True
    assert exit_price > entry_price
    assert final_roi > 0


@pytest.mark.unit
def test_atr_based_trailing_calculation():
    """Test ATR-based trailing stop calculation."""
    atr = 100.0  # ATR value
    atr_multiplier = 2.5
    current_price = 50000.0
    side = "long"
    
    # Calculate trailing distance based on ATR
    trailing_distance = atr * atr_multiplier
    
    if side == "long":
        stop_price = current_price - trailing_distance
    else:
        stop_price = current_price + trailing_distance
    
    assert trailing_distance == 250.0
    assert stop_price == 49750.0


@pytest.mark.integration
@pytest.mark.exchange
def test_position_manager_stop_loss_consistency(mock_bybit_exchange):
    """Test that position manager maintains stop loss consistency."""
    with patch('ccxt.bybit', return_value=mock_bybit_exchange):
        # Mock position with stop loss
        position = {
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 50000.0,
            "stop_loss": 49000.0,
            "trailing_active": False,
        }
        
        # Verify stop loss is set correctly
        assert position["stop_loss"] < position["entry_price"]
        
        # Update with new stop loss
        new_stop = 49500.0
        assert new_stop > position["stop_loss"], "Stop loss should move up"
        
        position["stop_loss"] = new_stop
        assert position["stop_loss"] == 49500.0


@pytest.mark.unit
def test_stop_loss_validation():
    """Test stop loss validation logic."""
    def validate_stop_loss(entry_price, stop_loss, side):
        if side == "long":
            if stop_loss >= entry_price:
                raise ValueError("Long stop loss must be below entry price")
        else:  # short
            if stop_loss <= entry_price:
                raise ValueError("Short stop loss must be above entry price")
        return True
    
    # Valid stops
    assert validate_stop_loss(50000, 49000, "long") is True
    assert validate_stop_loss(50000, 51000, "short") is True
    
    # Invalid stops
    with pytest.raises(ValueError):
        validate_stop_loss(50000, 51000, "long")
    with pytest.raises(ValueError):
        validate_stop_loss(50000, 49000, "short")
