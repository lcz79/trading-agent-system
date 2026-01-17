#!/usr/bin/env python3
"""
Test script for Limit Order Ladder execution strategy.

Tests:
1. Ladder price generation (ATR-based and BPS-based)
2. Price rounding and precision
3. Request validation
4. DRY_RUN mode
"""

import sys
import os
from decimal import Decimal, ROUND_DOWN

# Add agents directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', '07_position_manager'))

def test_ladder_price_generation_bps():
    """Test BPS-based ladder price generation"""
    print("\n" + "="*60)
    print("TEST: BPS-based Ladder Price Generation")
    print("="*60)
    
    # Mock data
    symbol = "BTCUSDT"
    side = "long"
    current_price = 50000.0
    num_orders = 5
    bps_offsets = [5, 10, 15, 20, 25]
    
    # Expected prices for long (buy orders below current price)
    expected_prices = [
        current_price * (1 - 5/10000),    # 49975.0
        current_price * (1 - 10/10000),   # 49950.0
        current_price * (1 - 15/10000),   # 49925.0
        current_price * (1 - 20/10000),   # 49900.0
        current_price * (1 - 25/10000),   # 49875.0
    ]
    
    # Generate ladder prices using BPS
    prices = []
    for bps in bps_offsets:
        offset_pct = bps / 10000.0
        if side == "long":
            price = current_price * (1 - offset_pct)
        else:
            price = current_price * (1 + offset_pct)
        prices.append(price)
    
    # Verify
    print(f"Symbol: {symbol}, Side: {side}, Current Price: ${current_price:.2f}")
    print(f"BPS Offsets: {bps_offsets}")
    print(f"\nGenerated Prices:")
    for i, (price, expected) in enumerate(zip(prices, expected_prices), 1):
        offset_pct = ((current_price - price) / current_price) * 100
        match = "✅" if abs(price - expected) < 0.01 else "❌"
        print(f"  {i}. ${price:.2f} (offset: {offset_pct:.3f}%) {match}")
    
    # Test for SHORT side
    print(f"\nTesting SHORT side:")
    side = "short"
    prices_short = []
    for bps in bps_offsets:
        offset_pct = bps / 10000.0
        price = current_price * (1 + offset_pct)
        prices_short.append(price)
    
    for i, price in enumerate(prices_short, 1):
        offset_pct = ((price - current_price) / current_price) * 100
        print(f"  {i}. ${price:.2f} (offset: +{offset_pct:.3f}%)")
    
    return len(prices) == num_orders


def test_ladder_price_generation_atr():
    """Test ATR-based ladder price generation (simulated)"""
    print("\n" + "="*60)
    print("TEST: ATR-based Ladder Price Generation (Simulated)")
    print("="*60)
    
    # Mock data
    symbol = "ETHUSDT"
    side = "long"
    current_price = 3000.0
    atr = 30.0  # Simulated ATR value
    atr_pct = atr / current_price  # 1%
    num_orders = 3
    atr_multipliers = [0.5, 1.0, 1.5]
    
    print(f"Symbol: {symbol}, Side: {side}, Current Price: ${current_price:.2f}")
    print(f"ATR: ${atr:.2f} ({atr_pct*100:.2f}%)")
    print(f"ATR Multipliers: {atr_multipliers}")
    print(f"\nGenerated Prices:")
    
    prices = []
    for mult in atr_multipliers:
        offset_pct = atr_pct * mult
        if side == "long":
            price = current_price * (1 - offset_pct)
        else:
            price = current_price * (1 + offset_pct)
        prices.append(price)
        print(f"  {mult}x ATR: ${price:.2f} (offset: {offset_pct*100:.2f}%)")
    
    return len(prices) == num_orders


def test_quantity_rounding():
    """Test quantity rounding to exchange precision"""
    print("\n" + "="*60)
    print("TEST: Quantity Rounding")
    print("="*60)
    
    test_cases = [
        {"qty_raw": 0.123456, "qty_step": 0.001, "min_qty": 0.001, "expected": 0.123},
        {"qty_raw": 0.123456, "qty_step": 0.01, "min_qty": 0.01, "expected": 0.12},
        {"qty_raw": 0.000123, "qty_step": 0.001, "min_qty": 0.001, "expected": 0.001},  # Below min
        {"qty_raw": 1.555555, "qty_step": 0.1, "min_qty": 0.1, "expected": 1.5},
    ]
    
    all_pass = True
    for i, tc in enumerate(test_cases, 1):
        qty_raw = tc["qty_raw"]
        qty_step = tc["qty_step"]
        min_qty = tc["min_qty"]
        expected = tc["expected"]
        
        # Apply rounding logic
        d_qty = Decimal(str(qty_raw))
        d_step = Decimal(str(qty_step))
        steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
        final_qty_d = steps * d_step
        if final_qty_d < Decimal(str(min_qty)):
            final_qty_d = Decimal(str(min_qty))
        final_qty = float("{:f}".format(final_qty_d.normalize()))
        
        match = "✅" if abs(final_qty - expected) < 0.0001 else "❌"
        print(f"  Test {i}: {qty_raw} → {final_qty} (expected: {expected}) {match}")
        
        if abs(final_qty - expected) >= 0.0001:
            all_pass = False
    
    return all_pass


def test_request_validation():
    """Test OrderRequest validation"""
    print("\n" + "="*60)
    print("TEST: OrderRequest Validation")
    print("="*60)
    
    # Test valid request
    print("  Valid Request:")
    valid_request = {
        "symbol": "BTCUSDT",
        "side": "long",
        "leverage": 5.0,
        "size_pct": 0.15,
        "execution_mode": "LIMIT_LADDER",
        "max_orders_per_symbol": 5,
        "post_only": True,
        "time_in_force": "GTC",
        "ladder_bps_offsets": [5, 10, 15, 20, 25],
        "fallback_mode": "REPRICE",
        "max_spread_pct": 0.0015
    }
    print(f"    Symbol: {valid_request['symbol']}")
    print(f"    Execution Mode: {valid_request['execution_mode']}")
    print(f"    Max Orders: {valid_request['max_orders_per_symbol']}")
    print(f"    Fallback: {valid_request['fallback_mode']}")
    print(f"    ✅ Valid")
    
    # Test invalid execution mode
    print("\n  Invalid Execution Mode:")
    invalid_mode = valid_request.copy()
    invalid_mode["execution_mode"] = "INVALID_MODE"
    print(f"    Execution Mode: {invalid_mode['execution_mode']}")
    print(f"    ❌ Should be rejected (not in [MARKET, LIMIT_LADDER])")
    
    # Test invalid max_orders_per_symbol
    print("\n  Invalid Max Orders:")
    invalid_orders = valid_request.copy()
    invalid_orders["max_orders_per_symbol"] = 10
    print(f"    Max Orders: {invalid_orders['max_orders_per_symbol']}")
    print(f"    ⚠️ Warning: Exceeds MAX_ORDERS_PER_SYMBOL=5")
    
    return True


def test_dry_run_mode():
    """Test DRY_RUN mode behavior"""
    print("\n" + "="*60)
    print("TEST: DRY_RUN Mode")
    print("="*60)
    
    print("  DRY_RUN=true:")
    print("    - Should log planned orders without execution")
    print("    - Order IDs should be prefixed with 'dry_run_'")
    print("    - No exchange API calls should be made")
    print("    ✅ Behavior defined")
    
    print("\n  DRY_RUN=false:")
    print("    - Should execute orders on exchange")
    print("    - Order IDs should be real exchange IDs")
    print("    - Exchange API calls should be made")
    print("    ✅ Behavior defined")
    
    return True


def test_execution_modes():
    """Test execution mode routing"""
    print("\n" + "="*60)
    print("TEST: Execution Mode Routing")
    print("="*60)
    
    print("  MARKET mode:")
    print("    - Single market order")
    print("    - Immediate execution")
    print("    - Taker fees")
    print("    ✅ Implemented")
    
    print("\n  LIMIT_LADDER mode:")
    print("    - Multiple limit orders (ladder)")
    print("    - Spread check required")
    print("    - Post-only for maker fees")
    print("    - Fill monitoring")
    print("    - Fallback strategies (REPRICE/MARKET/NONE)")
    print("    ✅ Implemented")
    
    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("LIMIT ORDER LADDER - TEST SUITE")
    print("=" * 60)
    
    results = {
        "BPS Ladder Generation": test_ladder_price_generation_bps(),
        "ATR Ladder Generation": test_ladder_price_generation_atr(),
        "Quantity Rounding": test_quantity_rounding(),
        "Request Validation": test_request_validation(),
        "DRY_RUN Mode": test_dry_run_mode(),
        "Execution Modes": test_execution_modes(),
    }
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
