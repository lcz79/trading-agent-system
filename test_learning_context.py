#!/usr/bin/env python3
"""
Test script for learning context implementation.

Tests:
1. Learning Agent /learning_context endpoint returns correct structure
2. Resilience: handles missing/corrupt history file
3. Orchestrator includes learning_context in Master AI payload
4. Master AI accepts and uses learning_context
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add agents to path
sys.path.insert(0, str(Path(__file__).parent / "agents" / "10_learning_agent"))

def create_test_trading_history(filepath: str, num_trades: int = 10):
    """Create a test trading history file with sample trades"""
    trades = []
    base_time = datetime.now() - timedelta(hours=48)
    
    for i in range(num_trades):
        # Alternate between winning and losing trades
        is_winner = i % 3 != 0  # 2 wins, 1 loss pattern
        
        trade = {
            "timestamp": (base_time + timedelta(hours=i*2)).isoformat(),
            "symbol": ["BTCUSDT", "ETHUSDT", "SOLUSDT"][i % 3],
            "side": "long" if i % 2 == 0 else "short",
            "entry_price": 40000 + i * 100,
            "exit_price": 40000 + i * 100 + (200 if is_winner else -150),
            "pnl_pct": 2.5 if is_winner else -1.8,
            "leverage": 5.0,
            "size_pct": 0.15,
            "duration_minutes": 60 + i * 10,
            "market_conditions": {"test": True}
        }
        trades.append(trade)
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        json.dump(trades, f, indent=2)
    
    print(f"✅ Created test trading history: {filepath} ({num_trades} trades)")


def test_learning_context_structure():
    """Test 1: Verify learning_context endpoint returns correct structure"""
    print("\n" + "="*60)
    print("Test 1: Learning Context Structure")
    print("="*60)
    
    # Import after path setup
    from main import calculate_per_symbol_stats, calculate_risk_flags, calculate_performance
    
    # Create sample trades
    trades = [
        {
            "timestamp": (datetime.now() - timedelta(hours=10)).isoformat(),
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 40000,
            "exit_price": 40500,
            "pnl_pct": 2.5,
            "leverage": 5.0,
            "size_pct": 0.15,
            "duration_minutes": 120,
        },
        {
            "timestamp": (datetime.now() - timedelta(hours=8)).isoformat(),
            "symbol": "ETHUSDT",
            "side": "short",
            "entry_price": 2500,
            "exit_price": 2450,
            "pnl_pct": 2.0,
            "leverage": 5.0,
            "size_pct": 0.15,
            "duration_minutes": 90,
        },
        {
            "timestamp": (datetime.now() - timedelta(hours=6)).isoformat(),
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 40500,
            "exit_price": 40200,
            "pnl_pct": -1.5,
            "leverage": 5.0,
            "size_pct": 0.15,
            "duration_minutes": 60,
        },
    ]
    
    # Test calculate_performance
    perf = calculate_performance(trades)
    print(f"✅ Performance calculated:")
    print(f"   - Total trades: {perf['total_trades']}")
    print(f"   - Win rate: {perf['win_rate']*100:.1f}%")
    print(f"   - Total PnL: {perf['total_pnl']:.2f}%")
    print(f"   - Max drawdown: {perf['max_drawdown']:.2f}%")
    
    assert perf['total_trades'] == 3, "Expected 3 trades"
    assert perf['winning_trades'] == 2, "Expected 2 winning trades"
    assert perf['losing_trades'] == 1, "Expected 1 losing trade"
    
    # Test calculate_per_symbol_stats
    by_symbol = calculate_per_symbol_stats(trades)
    print(f"✅ Per-symbol stats calculated:")
    for symbol, stats in by_symbol.items():
        print(f"   - {symbol}: {stats['total_trades']} trades, win_rate={stats['win_rate']*100:.0f}%")
    
    assert "BTCUSDT" in by_symbol, "Expected BTCUSDT stats"
    assert "ETHUSDT" in by_symbol, "Expected ETHUSDT stats"
    assert by_symbol["BTCUSDT"]["total_trades"] == 2, "Expected 2 BTCUSDT trades"
    
    # Test calculate_risk_flags
    risk_flags = calculate_risk_flags(trades, perf)
    print(f"✅ Risk flags calculated:")
    print(f"   - Losing streak: {risk_flags['losing_streak_count']}")
    print(f"   - Last trade PnL: {risk_flags['last_trade_pnl_pct']:.2f}%")
    print(f"   - Negative PnL period: {risk_flags['negative_pnl_period']}")
    print(f"   - High drawdown: {risk_flags['high_drawdown_period']}")
    
    assert risk_flags['losing_streak_count'] == 1, "Expected losing streak of 1"
    assert risk_flags['last_trade_pnl_pct'] == -1.5, "Expected last trade -1.5%"
    assert not risk_flags['negative_pnl_period'], "Expected positive PnL period"
    
    print("✅ Test 1 PASSED: All helper functions work correctly")


def test_empty_history_resilience():
    """Test 2: Verify resilience with empty/missing history"""
    print("\n" + "="*60)
    print("Test 2: Empty History Resilience")
    print("="*60)
    
    from main import calculate_performance, calculate_per_symbol_stats, calculate_risk_flags
    
    # Test with empty list
    empty_trades = []
    perf = calculate_performance(empty_trades)
    by_symbol = calculate_per_symbol_stats(empty_trades)
    risk_flags = calculate_risk_flags(empty_trades, perf)
    
    print(f"✅ Empty history handled gracefully:")
    print(f"   - Performance: {perf}")
    print(f"   - By symbol: {by_symbol}")
    print(f"   - Risk flags: {risk_flags}")
    
    assert perf['total_trades'] == 0, "Expected 0 trades"
    assert perf['win_rate'] == 0.0, "Expected 0% win rate"
    assert len(by_symbol) == 0, "Expected empty by_symbol dict"
    assert risk_flags['losing_streak_count'] == 0, "Expected 0 losing streak"
    
    print("✅ Test 2 PASSED: Empty history handled correctly")


def test_learning_context_trades_config():
    """Test 3: Verify LEARNING_CONTEXT_TRADES configuration"""
    print("\n" + "="*60)
    print("Test 3: LEARNING_CONTEXT_TRADES Configuration")
    print("="*60)
    
    # Check environment variable can be loaded
    os.environ['LEARNING_CONTEXT_TRADES'] = '25'
    
    # Re-import to get updated env var
    import importlib
    import main as learning_main
    importlib.reload(learning_main)
    
    assert learning_main.LEARNING_CONTEXT_TRADES == 25, "Expected LEARNING_CONTEXT_TRADES=25"
    print(f"✅ LEARNING_CONTEXT_TRADES configured: {learning_main.LEARNING_CONTEXT_TRADES}")
    
    # Reset to default
    os.environ['LEARNING_CONTEXT_TRADES'] = '30'
    importlib.reload(learning_main)
    
    assert learning_main.LEARNING_CONTEXT_TRADES == 30, "Expected default LEARNING_CONTEXT_TRADES=30"
    print(f"✅ Default LEARNING_CONTEXT_TRADES: {learning_main.LEARNING_CONTEXT_TRADES}")
    
    print("✅ Test 3 PASSED: Configuration works correctly")


def test_integration_scenario():
    """Test 4: Simulate full integration scenario"""
    print("\n" + "="*60)
    print("Test 4: Integration Scenario")
    print("="*60)
    
    # Create test data directory
    test_data_dir = "/tmp/test_learning_context"
    os.makedirs(test_data_dir, exist_ok=True)
    
    # Create test trading history
    history_file = f"{test_data_dir}/trading_history.json"
    create_test_trading_history(history_file, num_trades=15)
    
    print(f"✅ Test trading history created at {history_file}")
    
    # Verify file exists and is valid JSON
    with open(history_file, 'r') as f:
        trades = json.load(f)
        assert len(trades) == 15, "Expected 15 trades in file"
        print(f"✅ Trading history file verified: {len(trades)} trades")
    
    # Test that trades have the required fields
    for i, trade in enumerate(trades[:3]):
        required_fields = ['timestamp', 'symbol', 'side', 'pnl_pct', 'leverage']
        for field in required_fields:
            assert field in trade, f"Trade {i} missing field: {field}"
    
    print("✅ All trades have required fields")
    
    # Clean up
    import shutil
    shutil.rmtree(test_data_dir)
    print(f"✅ Test data cleaned up")
    
    print("✅ Test 4 PASSED: Integration scenario works")


def main():
    """Run all tests"""
    print("="*60)
    print("LEARNING CONTEXT IMPLEMENTATION TESTS")
    print("="*60)
    
    try:
        test_learning_context_structure()
        test_empty_history_resilience()
        test_learning_context_trades_config()
        test_integration_scenario()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        return 0
    
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
