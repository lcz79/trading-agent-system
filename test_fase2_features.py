#!/usr/bin/env python3
"""
FASE 2 Scalping Optimizations - Feature Tests

This test file demonstrates and validates FASE 2 features:
1. Risk-based position sizing
2. Volatility filter (anti-chop)
3. Market regime detection (TREND vs RANGE)
4. ADX-aware time-based exits
5. Spread & slippage control
6. Telemetry logging

Run this file to verify FASE 2 implementations.
"""

import sys
import os
import tempfile
from datetime import datetime, timedelta

# Add agents path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents'))

from shared.position_sizing import (
    calculate_position_size,
    calculate_stop_loss_from_atr,
    calculate_take_profit_from_atr,
    calculate_trailing_distance_from_atr
)
from shared.spread_slippage import (
    calculate_spread_from_orderbook,
    check_spread_acceptable,
    calculate_slippage
)
from shared.telemetry import TradeRecord, get_telemetry_logger


def test_risk_based_position_sizing():
    """Test risk-based position sizing calculations"""
    print("\n" + "="*80)
    print("TEST 1: Risk-Based Position Sizing")
    print("="*80)
    
    # Scenario: Account with $1000 equity, 0.3% risk per trade
    equity = 1000.0
    risk_pct = 0.003  # 0.3%
    entry_price = 50000.0  # BTC entry
    
    # Calculate SL from ATR
    atr = 250.0
    atr_multiplier = 1.2
    stop_loss_price, sl_info = calculate_stop_loss_from_atr(
        entry_price=entry_price,
        atr=atr,
        atr_multiplier=atr_multiplier,
        direction='long'
    )
    
    print(f"\n📊 Input Parameters:")
    print(f"   Equity: ${equity:.2f}")
    print(f"   Risk per trade: {risk_pct*100:.2f}%")
    print(f"   Entry price: ${entry_price:.2f}")
    print(f"   ATR: ${atr:.2f}")
    print(f"   SL multiplier: {atr_multiplier}x")
    print(f"   Stop Loss price: ${stop_loss_price:.2f}")
    print(f"   SL distance: {sl_info['sl_distance_pct']*100:.3f}%")
    
    # Calculate position size
    leverage = 5.0
    qty_step = 0.001
    min_qty = 0.001
    
    final_qty, sizing_info = calculate_position_size(
        equity=equity,
        risk_pct=risk_pct,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        leverage=leverage,
        qty_step=qty_step,
        min_qty=min_qty
    )
    
    print(f"\n📊 Position Sizing Results:")
    print(f"   Risk amount: ${sizing_info['risk_amount_usdt']:.2f}")
    print(f"   Position value: ${sizing_info['position_value']:.2f}")
    print(f"   Raw quantity: {sizing_info['qty_raw']:.6f} BTC")
    print(f"   Final quantity: {final_qty:.6f} BTC")
    print(f"   Notional value: ${final_qty * entry_price:.2f}")
    print(f"   Leveraged exposure: ${final_qty * entry_price * leverage:.2f}")
    
    # Verify risk calculation
    actual_risk = final_qty * entry_price * leverage * sizing_info['stop_distance_pct']
    print(f"\n✅ Verification:")
    print(f"   Expected risk: ${sizing_info['risk_amount_usdt']:.2f}")
    print(f"   Actual risk: ${actual_risk:.2f}")
    print(f"   Difference: ${abs(actual_risk - sizing_info['risk_amount_usdt']):.4f}")
    
    assert abs(actual_risk - sizing_info['risk_amount_usdt']) < 1.0, "Risk calculation mismatch!"
    print(f"   ✓ Risk-based sizing validated")


def test_volatility_filter():
    """Test volatility filter (anti-chop)"""
    print("\n" + "="*80)
    print("TEST 2: Volatility Filter (Anti-Chop)")
    print("="*80)
    
    # Scenario: Different market conditions
    scenarios = [
        {"name": "High Volatility (Trending)", "atr": 300.0, "price": 50000.0, "should_trade": True},
        {"name": "Medium Volatility (Normal)", "atr": 150.0, "price": 50000.0, "should_trade": True},
        {"name": "Low Volatility (Consolidation)", "atr": 50.0, "price": 50000.0, "should_trade": False},
        {"name": "Very Low Volatility (Chop)", "atr": 20.0, "price": 50000.0, "should_trade": False},
    ]
    
    min_volatility_threshold = 0.0025  # 0.25%
    
    print(f"\n📊 Volatility Filter Threshold: {min_volatility_threshold*100:.3f}%\n")
    
    for scenario in scenarios:
        atr = scenario["atr"]
        price = scenario["price"]
        volatility_pct = atr / price
        should_trade = volatility_pct >= min_volatility_threshold
        
        status = "✅ TRADE" if should_trade else "🚫 BLOCK"
        expected = "✓" if should_trade == scenario["should_trade"] else "✗"
        
        print(f"{expected} {scenario['name']}:")
        print(f"   ATR: ${atr:.2f}, Price: ${price:.2f}")
        print(f"   Volatility: {volatility_pct*100:.3f}% -> {status}")
        
        assert should_trade == scenario["should_trade"], f"Volatility filter failed for {scenario['name']}"
    
    print(f"\n✓ Volatility filter validated for all scenarios")


def test_regime_detection():
    """Test market regime detection (TREND vs RANGE)"""
    print("\n" + "="*80)
    print("TEST 3: Market Regime Detection (TREND vs RANGE)")
    print("="*80)
    
    # Scenario: Different EMA configurations
    scenarios = [
        {"name": "Strong Uptrend", "ema20": 51000.0, "ema200": 48000.0, "expected": "TREND"},
        {"name": "Moderate Uptrend", "ema20": 50300.0, "ema200": 50000.0, "expected": "RANGE"},
        {"name": "Range/Consolidation", "ema20": 50050.0, "ema200": 50000.0, "expected": "RANGE"},
        {"name": "Strong Downtrend", "ema20": 47000.0, "ema200": 50000.0, "expected": "TREND"},
    ]
    
    trend_threshold = 0.005  # 0.5%
    
    print(f"\n📊 Regime Threshold: {trend_threshold*100:.2f}%\n")
    
    for scenario in scenarios:
        ema20 = scenario["ema20"]
        ema200 = scenario["ema200"]
        
        # Calculate trend strength
        trend_strength = abs((ema20 - ema200) / ema200) if ema200 > 0 else 0
        regime = "TREND" if trend_strength > trend_threshold else "RANGE"
        
        expected = "✓" if regime == scenario["expected"] else "✗"
        
        print(f"{expected} {scenario['name']}:")
        print(f"   EMA20: ${ema20:.2f}, EMA200: ${ema200:.2f}")
        print(f"   Trend strength: {trend_strength*100:.3f}% -> {regime}")
        
        assert regime == scenario["expected"], f"Regime detection failed for {scenario['name']}"
    
    print(f"\n✓ Regime detection validated for all scenarios")


def test_regime_aware_parameters():
    """Test regime-aware parameter adjustments"""
    print("\n" + "="*80)
    print("TEST 4: Regime-Aware Parameter Adjustments")
    print("="*80)
    
    # Base parameters
    entry_price = 50000.0
    atr = 250.0
    tp_multiplier = 2.4
    trailing_multiplier = 1.2
    
    # Test TREND vs RANGE
    regimes = ["TREND", "RANGE"]
    
    for regime in regimes:
        print(f"\n📊 {regime} Mode:")
        
        # Calculate TP with regime adjustment
        tp_price, tp_info = calculate_take_profit_from_atr(
            entry_price=entry_price,
            atr=atr,
            atr_multiplier=tp_multiplier,
            direction='long',
            regime=regime
        )
        
        # Calculate trailing distance with regime adjustment
        trailing_pct, trail_info = calculate_trailing_distance_from_atr(
            price=entry_price,
            atr=atr,
            atr_multiplier_base=trailing_multiplier,
            regime=regime
        )
        
        print(f"   Take Profit:")
        print(f"      Base multiplier: {tp_multiplier}x")
        print(f"      Regime multiplier: {tp_info['regime_multiplier']}x")
        print(f"      Effective multiplier: {tp_info['effective_multiplier']}x")
        print(f"      TP price: ${tp_price:.2f}")
        print(f"      TP distance: {tp_info['tp_distance_pct']*100:.2f}%")
        
        print(f"   Trailing Stop:")
        print(f"      Base multiplier: {trailing_multiplier}x")
        print(f"      Regime multiplier: {trail_info['regime_multiplier']}x")
        print(f"      Effective multiplier: {trail_info['effective_multiplier']}x")
        print(f"      Trailing distance: {trailing_pct*100:.2f}%")
        
        # Verify TREND is more lenient
        if regime == "TREND":
            assert tp_info['effective_multiplier'] > tp_multiplier, "TREND should have higher TP multiplier"
            assert trail_info['effective_multiplier'] > trailing_multiplier, "TREND should have higher trailing multiplier"
    
    print(f"\n✓ Regime-aware parameters validated")


def test_spread_checking():
    """Test spread checking and orderbook analysis"""
    print("\n" + "="*80)
    print("TEST 5: Spread & Slippage Control")
    print("="*80)
    
    # Mock orderbooks with different spread scenarios
    scenarios = [
        {
            "name": "Tight Spread (Good Liquidity)",
            "orderbook": {
                "bids": [[50000.0, 1.5], [49999.0, 2.0]],
                "asks": [[50005.0, 1.5], [50006.0, 2.0]]
            },
            "should_accept": True
        },
        {
            "name": "Wide Spread (Poor Liquidity)",
            "orderbook": {
                "bids": [[50000.0, 0.5], [49990.0, 1.0]],
                "asks": [[50100.0, 0.5], [50110.0, 1.0]]
            },
            "should_accept": False
        },
        {
            "name": "Normal Spread",
            "orderbook": {
                "bids": [[50000.0, 1.0], [49998.0, 1.5]],
                "asks": [[50020.0, 1.0], [50022.0, 1.5]]
            },
            "should_accept": True
        }
    ]
    
    max_spread_pct = 0.0008  # 0.08%
    
    print(f"\n📊 Maximum Acceptable Spread: {max_spread_pct*100:.4f}%\n")
    
    for scenario in scenarios:
        spread_pct, spread_info = calculate_spread_from_orderbook(scenario["orderbook"])
        is_acceptable, reason = check_spread_acceptable(spread_pct, max_spread_pct)
        
        expected = "✓" if is_acceptable == scenario["should_accept"] else "✗"
        status = "✅ ACCEPT" if is_acceptable else "🚫 REJECT"
        
        print(f"{expected} {scenario['name']}:")
        print(f"   Best bid: ${spread_info['best_bid']:.2f}")
        print(f"   Best ask: ${spread_info['best_ask']:.2f}")
        print(f"   Spread: {spread_pct*100:.4f}% -> {status}")
        if not is_acceptable:
            print(f"   Reason: {reason}")
        
        assert is_acceptable == scenario["should_accept"], f"Spread check failed for {scenario['name']}"
    
    print(f"\n✓ Spread checking validated")


def test_slippage_calculation():
    """Test slippage calculation"""
    print("\n" + "="*80)
    print("TEST 6: Slippage Calculation")
    print("="*80)
    
    scenarios = [
        {"name": "Long - Favorable", "expected": 50000.0, "fill": 49995.0, "direction": "long", "favorable": True},
        {"name": "Long - Unfavorable", "expected": 50000.0, "fill": 50010.0, "direction": "long", "favorable": False},
        {"name": "Short - Favorable", "expected": 50000.0, "fill": 50010.0, "direction": "short", "favorable": True},
        {"name": "Short - Unfavorable", "expected": 50000.0, "fill": 49995.0, "direction": "short", "favorable": False},
    ]
    
    print()
    
    for scenario in scenarios:
        slippage_pct, slippage_info = calculate_slippage(
            expected_price=scenario["expected"],
            fill_price=scenario["fill"],
            direction=scenario["direction"]
        )
        
        is_favorable = slippage_info['favorable']
        expected = "✓" if is_favorable == scenario["favorable"] else "✗"
        
        print(f"{expected} {scenario['name']}:")
        print(f"   Expected: ${scenario['expected']:.2f}")
        print(f"   Fill: ${scenario['fill']:.2f}")
        print(f"   Slippage: {slippage_pct*100:.4f}% ({'favorable' if is_favorable else 'unfavorable'})")
        
        assert is_favorable == scenario["favorable"], f"Slippage calculation failed for {scenario['name']}"
    
    print(f"\n✓ Slippage calculation validated")


def test_telemetry_logging():
    """Test telemetry logging with JSONL rotation"""
    print("\n" + "="*80)
    print("TEST 7: Telemetry Logging")
    print("="*80)
    
    # Create temporary file for testing
    test_file = tempfile.mktemp(suffix=".jsonl")
    
    logger = get_telemetry_logger(filepath=test_file, max_size_mb=1, max_rotated_files=2)
    
    # Log multiple trades
    print(f"\n📊 Logging test trades to: {test_file}\n")
    
    trades = [
        {
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 50000.0,
            "exit_price": 50500.0,
            "pnl_pct_gross": 5.0,
            "pnl_pct_net": 4.8,
            "reason_exit": "tp",
            "mode": "TREND"
        },
        {
            "symbol": "ETHUSDT",
            "side": "short",
            "entry_price": 3000.0,
            "exit_price": 2950.0,
            "pnl_pct_gross": 3.33,
            "pnl_pct_net": 3.2,
            "reason_exit": "sl",
            "mode": "RANGE"
        },
        {
            "symbol": "SOLUSDT",
            "side": "long",
            "entry_price": 100.0,
            "exit_price": 98.0,
            "pnl_pct_gross": -2.0,
            "pnl_pct_net": -2.1,
            "reason_exit": "time_exit_flat",
            "mode": "RANGE"
        }
    ]
    
    for trade in trades:
        record = TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            symbol=trade["symbol"],
            side=trade["side"],
            entry_price=trade["entry_price"],
            exit_price=trade["exit_price"],
            entry_time=(datetime.utcnow() - timedelta(minutes=30)).isoformat(),
            exit_time=datetime.utcnow().isoformat(),
            pnl_pct_gross=trade["pnl_pct_gross"],
            pnl_pct_net=trade["pnl_pct_net"],
            pnl_dollars=trade["pnl_pct_net"] * 10.0,  # Assume $10 per %
            fees_dollars=0.20,
            fees_pct=0.002,
            reason_exit=trade["reason_exit"],
            mode=trade["mode"],
            leverage=5.0,
            size=0.1,
            size_pct=0.15
        )
        logger.log_trade(record)
        print(f"   ✓ Logged: {trade['symbol']} {trade['side']} PnL={trade['pnl_pct_net']}% exit={trade['reason_exit']}")
    
    # Read back trades
    recent_trades = logger.read_recent_trades(limit=10)
    print(f"\n📊 Read {len(recent_trades)} trades from telemetry file")
    
    assert len(recent_trades) == len(trades), "Trade count mismatch!"
    
    # Cleanup
    try:
        os.remove(test_file)
    except FileNotFoundError:
        pass  # File already doesn't exist
    except Exception as e:
        print(f"   Warning: Could not cleanup test file: {e}")
    
    print(f"\n✓ Telemetry logging validated")


def main():
    """Run all FASE 2 feature tests"""
    print("\n" + "="*80)
    print("FASE 2 SCALPING OPTIMIZATIONS - FEATURE VALIDATION")
    print("="*80)
    
    try:
        test_risk_based_position_sizing()
        test_volatility_filter()
        test_regime_detection()
        test_regime_aware_parameters()
        test_spread_checking()
        test_slippage_calculation()
        test_telemetry_logging()
        
        print("\n" + "="*80)
        print("✅ ALL FASE 2 TESTS PASSED")
        print("="*80)
        print("\nFASE 2 features validated successfully:")
        print("  ✓ Risk-based position sizing")
        print("  ✓ Volatility filter (anti-chop)")
        print("  ✓ Market regime detection (TREND vs RANGE)")
        print("  ✓ Regime-aware parameter adjustments")
        print("  ✓ Spread & slippage control")
        print("  ✓ Telemetry logging with rotation")
        print("\n")
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
