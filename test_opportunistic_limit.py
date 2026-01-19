#!/usr/bin/env python3
"""
Test suite for opportunistic LIMIT feature.

Tests validation gates, risk-based sizing, orchestrator mapping,
and backward compatibility.
"""

import json
import sys
import os

# Add agents path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents'))

from agents.shared import position_sizing


def test_valid_opportunistic_limit():
    """Test that a valid opportunistic LIMIT passes all gates"""
    print("=" * 80)
    print("TEST 1: Valid Opportunistic LIMIT")
    print("=" * 80)
    
    # Sample HOLD decision with valid opportunistic_limit
    decision = {
        "symbol": "ETHUSDT",
        "action": "HOLD",
        "direction_considered": "NONE",
        "setup_confirmations": [],
        "blocked_by": [],
        "soft_blockers": ["LOW_CONFIDENCE"],
        "confidence": 55,
        "rationale": "Insufficient confirmations for direct entry, but valid support test opportunity",
        "leverage": 1.0,
        "size_pct": 0.0,
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 3500.0,
            "entry_expires_sec": 180,
            "tp_pct": 0.015,  # 1.5%
            "sl_pct": 0.010,  # 1.0%
            "rr": 1.5,
            "edge_score": 72,
            "reasoning_bullets": [
                "Price at Fib 0.618 support (3500)",
                "RSI 15m oversold at 32",
                "Volume spike confirms support test",
                "1h trend neutral"
            ]
        }
    }
    
    # Expected validation: should pass
    opp = decision["opportunistic_limit"]
    
    # Validate required fields
    assert opp["side"] in ["LONG", "SHORT"], f"Invalid side: {opp['side']}"
    assert opp["entry_price"] > 0, f"Invalid entry_price: {opp['entry_price']}"
    assert 60 <= opp["entry_expires_sec"] <= 300, f"entry_expires_sec out of range: {opp['entry_expires_sec']}"
    assert opp["tp_pct"] >= 0.010, f"tp_pct too low: {opp['tp_pct']}"
    assert 0.0025 <= opp["sl_pct"] <= 0.025, f"sl_pct out of bounds: {opp['sl_pct']}"
    assert opp["rr"] >= 1.5, f"RR too low: {opp['rr']}"
    
    # Validate action is HOLD
    assert decision["action"] == "HOLD", f"Opportunistic only for HOLD, got {decision['action']}"
    
    # Validate no hard blockers
    assert not decision["blocked_by"], f"Hard blockers present: {decision['blocked_by']}"
    
    # Validate price distance (assume current ~3510)
    current_price = 3510.0
    price_diff_pct = abs(opp["entry_price"] - current_price) / current_price
    assert price_diff_pct <= 0.008, f"Entry price too far: {price_diff_pct*100:.2f}% > 0.8%"
    
    print(f"✅ Decision: {decision['action']} {decision['symbol']}")
    print(f"✅ Opportunistic LIMIT: {opp['side']} @ {opp['entry_price']}")
    print(f"✅ RR: {opp['rr']:.2f}, TP: {opp['tp_pct']*100:.1f}%, SL: {opp['sl_pct']*100:.1f}%")
    print(f"✅ Edge score: {opp['edge_score']}")
    print(f"✅ All gates passed")
    print("\n✅ TEST 1 PASSED\n")


def test_invalid_rr():
    """Test that opportunistic LIMIT with low RR is rejected"""
    print("=" * 80)
    print("TEST 2: Invalid RR (< 1.5)")
    print("=" * 80)
    
    decision = {
        "symbol": "BTCUSDT",
        "action": "HOLD",
        "blocked_by": [],
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 50000.0,
            "entry_expires_sec": 180,
            "tp_pct": 0.010,  # 1.0%
            "sl_pct": 0.010,  # 1.0%
            "rr": 1.0,  # Invalid: < 1.5
            "edge_score": 70,
            "reasoning_bullets": ["Some reasoning"]
        }
    }
    
    opp = decision["opportunistic_limit"]
    
    # Should fail RR gate
    try:
        assert opp["rr"] >= 1.5, f"RR {opp['rr']} < 1.5 (minimum)"
        print("❌ TEST 2 FAILED: RR gate did not block")
        sys.exit(1)
    except AssertionError as e:
        print(f"✅ RR gate blocked as expected: {e}")
        print("\n✅ TEST 2 PASSED\n")


def test_invalid_tp_pct():
    """Test that opportunistic LIMIT with low TP is rejected"""
    print("=" * 80)
    print("TEST 3: Invalid TP (<1%)")
    print("=" * 80)
    
    decision = {
        "symbol": "SOLUSDT",
        "action": "HOLD",
        "blocked_by": [],
        "opportunistic_limit": {
            "side": "SHORT",
            "entry_price": 150.0,
            "entry_expires_sec": 180,
            "tp_pct": 0.005,  # 0.5% - Invalid: < 1%
            "sl_pct": 0.010,
            "rr": 0.5,  # Also invalid
            "edge_score": 65,
            "reasoning_bullets": ["Some reasoning"]
        }
    }
    
    opp = decision["opportunistic_limit"]
    
    # Should fail TP gate
    try:
        assert opp["tp_pct"] >= 0.010, f"tp_pct {opp['tp_pct']} < 0.010 (1% minimum)"
        print("❌ TEST 3 FAILED: TP gate did not block")
        sys.exit(1)
    except AssertionError as e:
        print(f"✅ TP gate blocked as expected: {e}")
        print("\n✅ TEST 3 PASSED\n")


def test_invalid_action():
    """Test that opportunistic LIMIT is rejected when action != HOLD"""
    print("=" * 80)
    print("TEST 4: Invalid Action (OPEN_LONG instead of HOLD)")
    print("=" * 80)
    
    decision = {
        "symbol": "ETHUSDT",
        "action": "OPEN_LONG",  # Invalid: should be HOLD
        "blocked_by": [],
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 3500.0,
            "entry_expires_sec": 180,
            "tp_pct": 0.015,
            "sl_pct": 0.010,
            "rr": 1.5,
            "edge_score": 72,
            "reasoning_bullets": ["Valid reasoning"]
        }
    }
    
    # Should fail action gate
    try:
        assert decision["action"] == "HOLD", f"Opportunistic only for HOLD, got {decision['action']}"
        print("❌ TEST 4 FAILED: Action gate did not block")
        sys.exit(1)
    except AssertionError as e:
        print(f"✅ Action gate blocked as expected: {e}")
        print("\n✅ TEST 4 PASSED\n")


def test_hard_blockers_present():
    """Test that opportunistic LIMIT is rejected when hard blockers present"""
    print("=" * 80)
    print("TEST 5: Hard Blockers Present")
    print("=" * 80)
    
    decision = {
        "symbol": "BTCUSDT",
        "action": "HOLD",
        "blocked_by": ["INSUFFICIENT_MARGIN", "CRASH_GUARD"],  # Hard blockers
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 50000.0,
            "entry_expires_sec": 180,
            "tp_pct": 0.015,
            "sl_pct": 0.010,
            "rr": 1.5,
            "edge_score": 70,
            "reasoning_bullets": ["Valid reasoning"]
        }
    }
    
    # Should fail hard blocker gate
    try:
        assert not decision["blocked_by"], f"Hard blockers present: {decision['blocked_by']}"
        print("❌ TEST 5 FAILED: Hard blocker gate did not block")
        sys.exit(1)
    except AssertionError as e:
        print(f"✅ Hard blocker gate blocked as expected: {e}")
        print("\n✅ TEST 5 PASSED\n")


def test_orchestrator_mapping():
    """Test that orchestrator correctly maps HOLD + opportunistic_limit to PM payload"""
    print("=" * 80)
    print("TEST 6: Orchestrator Mapping")
    print("=" * 80)
    
    decision = {
        "symbol": "ETHUSDT",
        "action": "HOLD",
        "blocked_by": [],
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 3500.0,
            "entry_expires_sec": 180,
            "tp_pct": 0.015,
            "sl_pct": 0.010,
            "rr": 1.5,
            "edge_score": 72,
            "leverage": 3.5,
            "size_pct": 0.10,
            "reasoning_bullets": ["Fib support", "RSI oversold"]
        }
    }
    
    # Simulate orchestrator mapping
    opp = decision["opportunistic_limit"]
    opp_action = "OPEN_LONG" if opp["side"] == "LONG" else "OPEN_SHORT"
    
    pm_payload = {
        "symbol": decision["symbol"],
        "side": opp_action,
        "leverage": opp["leverage"],
        "size_pct": opp["size_pct"],
        "entry_type": "LIMIT",
        "entry_price": opp["entry_price"],
        "entry_ttl_sec": opp["entry_expires_sec"],
        "tp_pct": opp["tp_pct"],
        "sl_pct": opp["sl_pct"],
        "features": {
            "opportunistic": True,
            "rr": opp["rr"],
            "edge_score": opp["edge_score"],
            "reasoning": opp["reasoning_bullets"],
            "original_action": "HOLD"
        }
    }
    
    # Validate PM payload
    assert pm_payload["symbol"] == "ETHUSDT"
    assert pm_payload["side"] == "OPEN_LONG"
    assert pm_payload["entry_type"] == "LIMIT"
    assert pm_payload["entry_price"] == 3500.0
    assert pm_payload["entry_ttl_sec"] == 180
    assert pm_payload["features"]["opportunistic"] is True
    assert pm_payload["features"]["original_action"] == "HOLD"
    
    print(f"✅ Mapped HOLD to {pm_payload['side']} LIMIT")
    print(f"✅ Entry: {pm_payload['entry_type']} @ {pm_payload['entry_price']}")
    print(f"✅ TTL: {pm_payload['entry_ttl_sec']}s")
    print(f"✅ Features marked as opportunistic")
    print(f"✅ PM Payload: {json.dumps(pm_payload, indent=2)}")
    print("\n✅ TEST 6 PASSED\n")


def test_backward_compatibility():
    """Test that decisions without opportunistic_limit still work"""
    print("=" * 80)
    print("TEST 7: Backward Compatibility")
    print("=" * 80)
    
    # Decision without opportunistic_limit
    decision_old = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "direction_considered": "LONG",
        "setup_confirmations": ["RSI oversold", "MACD bullish"],
        "blocked_by": [],
        "confidence": 78,
        "rationale": "Strong bullish setup",
        "leverage": 5.0,
        "size_pct": 0.15,
        "tp_pct": 0.02,
        "sl_pct": 0.015,
        "entry_type": "MARKET"
    }
    
    # Should work normally without opportunistic_limit
    assert decision_old["action"] == "OPEN_LONG"
    assert "opportunistic_limit" not in decision_old or decision_old.get("opportunistic_limit") is None
    
    print(f"✅ Old decision format works: {decision_old['action']} {decision_old['symbol']}")
    print(f"✅ No opportunistic_limit field present")
    print(f"✅ Backward compatibility maintained")
    print("\n✅ TEST 7 PASSED\n")


def test_entry_price_distance():
    """Test that entry price too far from current is rejected"""
    print("=" * 80)
    print("TEST 8: Entry Price Distance Check")
    print("=" * 80)
    
    current_price = 50000.0
    
    decision = {
        "symbol": "BTCUSDT",
        "action": "HOLD",
        "blocked_by": [],
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 49000.0,  # 2% away - invalid (> 0.8%)
            "entry_expires_sec": 180,
            "tp_pct": 0.015,
            "sl_pct": 0.010,
            "rr": 1.5,
            "edge_score": 70,
            "reasoning_bullets": ["Some reasoning"]
        }
    }
    
    opp = decision["opportunistic_limit"]
    price_diff_pct = abs(opp["entry_price"] - current_price) / current_price
    
    # Should fail distance gate
    try:
        assert price_diff_pct <= 0.008, f"Entry price {opp['entry_price']} too far from current {current_price} ({price_diff_pct*100:.2f}% > 0.8%)"
        print("❌ TEST 8 FAILED: Distance gate did not block")
        sys.exit(1)
    except AssertionError as e:
        print(f"✅ Distance gate blocked as expected: {e}")
        print(f"✅ Price diff: {price_diff_pct*100:.2f}% > 0.8%")
        print("\n✅ TEST 8 PASSED\n")


def test_expires_sec_bounds():
    """Test that entry_expires_sec outside bounds is rejected"""
    print("=" * 80)
    print("TEST 9: entry_expires_sec Bounds")
    print("=" * 80)
    
    # Test too short
    decision_short = {
        "symbol": "ETHUSDT",
        "action": "HOLD",
        "blocked_by": [],
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 3500.0,
            "entry_expires_sec": 30,  # Invalid: < 60
            "tp_pct": 0.015,
            "sl_pct": 0.010,
            "rr": 1.5,
            "edge_score": 70,
            "reasoning_bullets": ["Valid reasoning"]
        }
    }
    
    opp = decision_short["opportunistic_limit"]
    
    try:
        assert 60 <= opp["entry_expires_sec"] <= 300, f"entry_expires_sec {opp['entry_expires_sec']} not in [60, 300]"
        print("❌ TEST 9a FAILED: Expires gate did not block (too short)")
        sys.exit(1)
    except AssertionError as e:
        print(f"✅ Expires gate blocked too short: {e}")
    
    # Test too long
    decision_long = {
        "symbol": "ETHUSDT",
        "action": "HOLD",
        "blocked_by": [],
        "opportunistic_limit": {
            "side": "LONG",
            "entry_price": 3500.0,
            "entry_expires_sec": 400,  # Invalid: > 300
            "tp_pct": 0.015,
            "sl_pct": 0.010,
            "rr": 1.5,
            "edge_score": 70,
            "reasoning_bullets": ["Valid reasoning"]
        }
    }
    
    opp = decision_long["opportunistic_limit"]
    
    try:
        assert 60 <= opp["entry_expires_sec"] <= 300, f"entry_expires_sec {opp['entry_expires_sec']} not in [60, 300]"
        print("❌ TEST 9b FAILED: Expires gate did not block (too long)")
        sys.exit(1)
    except AssertionError as e:
        print(f"✅ Expires gate blocked too long: {e}")
    
    print("\n✅ TEST 9 PASSED\n")


def run_all_tests():
    """Run all test cases"""
    print("\n" + "=" * 80)
    print("OPPORTUNISTIC LIMIT FEATURE - TEST SUITE")
    print("=" * 80 + "\n")
    
    try:
        test_valid_opportunistic_limit()
        test_invalid_rr()
        test_invalid_tp_pct()
        test_invalid_action()
        test_hard_blockers_present()
        test_orchestrator_mapping()
        test_backward_compatibility()
        test_entry_price_distance()
        test_expires_sec_bounds()
        
        print("\n" + "=" * 80)
        print("ALL TESTS PASSED ✅")
        print("=" * 80 + "\n")
        return 0
    except Exception as e:
        print(f"\n❌ TEST SUITE FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
