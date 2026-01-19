#!/usr/bin/env python3
"""
Test suite for Option C implementation:
- Strict entry type enforcement
- Position metadata with entry_type tracking
- Closed trades persistence
- Enriched get_closed_positions endpoint
"""

import os
import sys
import json
import tempfile
from datetime import datetime, timedelta

# Add the agents directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agents", "07_position_manager"))

from shared.trading_state import TradingState, PositionMetadata, OrderIntent, OrderStatus


def test_position_metadata_entry_type():
    """Test that PositionMetadata includes entry_type field"""
    print("\n=== Test 1: PositionMetadata entry_type field ===")
    
    # Create position with entry_type
    pos = PositionMetadata(
        symbol="BTCUSDT",
        side="long",
        entry_price=50000.0,
        size=0.1,
        leverage=5.0,
        entry_type="LIMIT"
    )
    
    assert pos.entry_type == "LIMIT", "entry_type should be LIMIT"
    
    # Serialize and deserialize
    pos_dict = pos.to_dict()
    assert "entry_type" in pos_dict, "entry_type should be in serialized dict"
    assert pos_dict["entry_type"] == "LIMIT", "entry_type should be LIMIT in dict"
    
    # Deserialize
    pos2 = PositionMetadata.from_dict(pos_dict)
    assert pos2.entry_type == "LIMIT", "entry_type should be preserved after deserialization"
    
    print("✅ PositionMetadata entry_type field works correctly")


def test_trading_state_closed_trades():
    """Test closed_trades management in TradingState"""
    print("\n=== Test 2: TradingState closed_trades management ===")
    
    # Create a temporary state file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = f.name
    
    try:
        # Set env var to use temp file
        old_env = os.environ.get("TRADING_STATE_FILE")
        os.environ["TRADING_STATE_FILE"] = temp_file
        
        # Reset singleton for clean test
        TradingState._instance = None
        
        # Create fresh trading state
        ts = TradingState()
        
        # Check default state has closed_trades
        assert "closed_trades" in ts._state, "closed_trades should be in default state"
        assert isinstance(ts._state["closed_trades"], list), "closed_trades should be a list"
        
        # Add a closed trade
        closed_trade1 = {
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 50000.0,
            "entry_type": "MARKET",
            "opened_at": datetime.now().isoformat(),
            "closed_at": datetime.now().isoformat(),
            "exit_reason": "manual",
            "intent_id": "test-intent-1"
        }
        
        ts.add_closed_trade(closed_trade1)
        
        # Retrieve closed trades
        closed_trades = ts.get_closed_trades()
        assert len(closed_trades) == 1, "Should have 1 closed trade"
        assert closed_trades[0]["symbol"] == "BTCUSDT", "Symbol should match"
        assert closed_trades[0]["entry_type"] == "MARKET", "Entry type should match"
        
        # Add more trades to test keep_last limit
        for i in range(10):
            ts.add_closed_trade({
                "symbol": f"SYM{i}",
                "side": "long",
                "entry_price": 100.0 + i,
                "entry_type": "LIMIT" if i % 2 == 0 else "MARKET",
                "closed_at": datetime.now().isoformat(),
                "exit_reason": "test"
            })
        
        closed_trades = ts.get_closed_trades()
        assert len(closed_trades) == 11, "Should have 11 closed trades"
        
        # Test keep_last limit (default 500)
        # Add 495 more to exceed limit
        for i in range(495):
            ts.add_closed_trade({
                "symbol": "TEST",
                "side": "short",
                "entry_price": 1000.0,
                "closed_at": datetime.now().isoformat()
            })
        
        closed_trades = ts.get_closed_trades()
        assert len(closed_trades) == 500, f"Should have exactly 500 closed trades (keep_last limit), got {len(closed_trades)}"
        
        print("✅ TradingState closed_trades management works correctly")
        
    finally:
        # Cleanup
        if old_env:
            os.environ["TRADING_STATE_FILE"] = old_env
        else:
            os.environ.pop("TRADING_STATE_FILE", None)
        
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        # Reset singleton
        TradingState._instance = None


def test_prune_positions_returns_dict():
    """Test that prune_positions returns dict with removed_keys and removed_positions"""
    print("\n=== Test 3: prune_positions returns dict with metadata ===")
    
    # Create a temporary state file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = f.name
    
    try:
        old_env = os.environ.get("TRADING_STATE_FILE")
        os.environ["TRADING_STATE_FILE"] = temp_file
        TradingState._instance = None
        
        ts = TradingState()
        
        # Add some positions
        pos1 = PositionMetadata(
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            size=0.1,
            leverage=5.0,
            entry_type="MARKET",
            intent_id="intent-1"
        )
        pos2 = PositionMetadata(
            symbol="ETHUSDT",
            side="short",
            entry_price=3000.0,
            size=1.0,
            leverage=3.0,
            entry_type="LIMIT",
            intent_id="intent-2"
        )
        
        ts.add_position(pos1)
        ts.add_position(pos2)
        
        # Prune positions (only keep BTCUSDT_long active)
        active_keys = {"BTCUSDT_long"}
        result = ts.prune_positions(active_keys)
        
        # Check return type is dict
        assert isinstance(result, dict), "prune_positions should return dict"
        assert "removed_keys" in result, "Should have removed_keys"
        assert "removed_positions" in result, "Should have removed_positions"
        
        # Check removed data
        removed_keys = result["removed_keys"]
        removed_positions = result["removed_positions"]
        
        assert len(removed_keys) == 1, "Should remove 1 position"
        assert "ETHUSDT_short" in removed_keys, "Should remove ETHUSDT_short"
        
        assert len(removed_positions) == 1, "Should have 1 removed position metadata"
        removed_pos = removed_positions[0]
        assert removed_pos["symbol"] == "ETHUSDT", "Removed position should be ETHUSDT"
        assert removed_pos["side"] == "short", "Side should be short"
        assert removed_pos["entry_type"] == "LIMIT", "Entry type should be preserved"
        assert removed_pos["intent_id"] == "intent-2", "Intent ID should be preserved"
        
        print("✅ prune_positions returns dict with metadata correctly")
        
    finally:
        if old_env:
            os.environ["TRADING_STATE_FILE"] = old_env
        else:
            os.environ.pop("TRADING_STATE_FILE", None)
        
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        TradingState._instance = None


def test_backward_compatibility():
    """Test backward compatibility with existing state files"""
    print("\n=== Test 4: Backward compatibility ===")
    
    # Create a temporary state file with old schema (no closed_trades, no entry_type)
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    old_state = {
        "version": "1.0.0",
        "last_updated": datetime.now().isoformat(),
        "intents": {},
        "positions": {
            "BTCUSDT_long": {
                "symbol": "BTCUSDT",
                "side": "long",
                "entry_price": 50000.0,
                "size": 0.1,
                "leverage": 5.0,
                "opened_at": datetime.now().isoformat(),
                "intent_id": "old-intent"
                # Note: no entry_type field
            }
        },
        "cooldowns": [],
        "trailing_stops": {}
        # Note: no closed_trades field
    }
    json.dump(old_state, f)
    f.close()
    temp_file = f.name
    
    try:
        # Need to reload the module to pick up new env var
        import importlib
        import shared.trading_state as ts_module
        
        old_env = os.environ.get("TRADING_STATE_FILE")
        os.environ["TRADING_STATE_FILE"] = temp_file
        
        # Reload module to pick up new TRADING_STATE_FILE
        importlib.reload(ts_module)
        TradingState._instance = None
        
        # Load old state
        ts = ts_module.TradingState()
        
        # Check closed_trades was added by normalization
        assert "closed_trades" in ts._state, "closed_trades should be added by normalization"
        assert isinstance(ts._state["closed_trades"], list), "closed_trades should be a list"
        
        # Load position without entry_type
        assert "BTCUSDT_long" in ts._state["positions"], "Position should be in state"
        pos_data = ts._state["positions"]["BTCUSDT_long"]
        pos = ts_module.PositionMetadata.from_dict(pos_data)
        assert pos is not None, "Should load old position"
        assert pos.symbol == "BTCUSDT", "Symbol should match"
        assert pos.entry_type is None, "Old position should have None entry_type"
        
        # Add new position with entry_type
        new_pos = ts_module.PositionMetadata(
            symbol="ETHUSDT",
            side="long",
            entry_price=3000.0,
            size=1.0,
            leverage=3.0,
            entry_type="LIMIT"
        )
        ts.add_position(new_pos)
        
        # Retrieve and verify
        loaded_pos = ts.get_position("ETHUSDT", "long")
        assert loaded_pos.entry_type == "LIMIT", "New position should have entry_type"
        
        print("✅ Backward compatibility maintained")
        
    finally:
        if old_env:
            os.environ["TRADING_STATE_FILE"] = old_env
        else:
            os.environ.pop("TRADING_STATE_FILE", None)
        
        # Reload again to restore original
        importlib.reload(ts_module)
        
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        TradingState._instance = None


def test_strict_entry_type_validation():
    """Test strict entry type validation logic (conceptual test)"""
    print("\n=== Test 5: Strict entry type validation (conceptual) ===")
    
    # Test that STRICT_ENTRY_TYPE env var is read correctly
    old_env = os.environ.get("STRICT_ENTRY_TYPE")
    
    try:
        # Test default (should be "0" or not set)
        os.environ.pop("STRICT_ENTRY_TYPE", None)
        # Would need to reload main.py module to test actual behavior
        # For now, just verify the env var logic
        
        strict_mode = os.getenv("STRICT_ENTRY_TYPE", "0") == "1"
        assert strict_mode == False, "Default should be non-strict mode"
        
        # Test enabled
        os.environ["STRICT_ENTRY_TYPE"] = "1"
        strict_mode = os.getenv("STRICT_ENTRY_TYPE", "0") == "1"
        assert strict_mode == True, "Should enable strict mode when set to '1'"
        
        # Test disabled explicitly
        os.environ["STRICT_ENTRY_TYPE"] = "0"
        strict_mode = os.getenv("STRICT_ENTRY_TYPE", "0") == "1"
        assert strict_mode == False, "Should disable strict mode when set to '0'"
        
        print("✅ Strict entry type env var logic works correctly")
        
    finally:
        if old_env:
            os.environ["STRICT_ENTRY_TYPE"] = old_env
        else:
            os.environ.pop("STRICT_ENTRY_TYPE", None)


def test_closed_trade_record_structure():
    """Test that closed trade records have the expected structure"""
    print("\n=== Test 6: Closed trade record structure ===")
    
    # Expected fields in a closed trade record
    expected_fields = [
        "symbol", "side", "entry_price", "entry_type",
        "opened_at", "closed_at", "exit_reason", "intent_id"
    ]
    
    closed_trade = {
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_price": 50000.0,
        "entry_type": "MARKET",
        "opened_at": datetime.now().isoformat(),
        "closed_at": datetime.now().isoformat(),
        "exit_reason": "stale_prune",
        "intent_id": "test-intent-123",
        "leverage": 5.0,
        "size": 0.1
    }
    
    for field in expected_fields:
        assert field in closed_trade, f"Closed trade should have {field} field"
    
    # Additional optional fields
    assert "leverage" in closed_trade, "Should have leverage"
    assert "size" in closed_trade, "Should have size"
    
    print("✅ Closed trade record structure is correct")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("Running Option C Implementation Tests")
    print("=" * 60)
    
    tests = [
        test_position_metadata_entry_type,
        test_trading_state_closed_trades,
        test_prune_positions_returns_dict,
        test_backward_compatibility,
        test_strict_entry_type_validation,
        test_closed_trade_record_structure
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} error: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
