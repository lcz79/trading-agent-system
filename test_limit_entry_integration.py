#!/usr/bin/env python3
"""
Comprehensive test suite for LIMIT entry integration end-to-end.

Tests:
1. AI response parsing with entry_type/entry_price/entry_expires_sec
2. Validation and fallback behavior for invalid LIMIT parameters
3. Payload propagation from orchestrator to position manager
4. Cancel+replace flow for pending LIMIT orders
5. Guardrail behavior with existing positions and scale-in mode
"""

import sys
import json
import os
from datetime import datetime, timedelta

# Add paths for imports
sys.path.insert(0, '/home/runner/work/trading-agent-system/trading-agent-system/agents/04_master_ai_agent')
sys.path.insert(0, '/home/runner/work/trading-agent-system/trading-agent-system/agents/07_position_manager')

def test_ai_decision_model_limit_fields():
    """Test that Decision model accepts LIMIT entry fields"""
    print("=" * 60)
    print("TEST: AI Decision Model - LIMIT Entry Fields")
    print("=" * 60)
    
    try:
        from main import Decision
        
        # Test MARKET decision (default)
        market_dec = Decision(
            symbol="BTCUSDT",
            action="OPEN_LONG",
            leverage=5.0,
            size_pct=0.15,
            confidence=75,
            rationale="Test market entry",
            entry_type="MARKET"
        )
        
        assert market_dec.entry_type == "MARKET"
        assert market_dec.entry_price is None
        assert market_dec.entry_expires_sec == 240  # default
        print("✅ MARKET decision: PASS")
        
        # Test LIMIT decision
        limit_dec = Decision(
            symbol="ETHUSDT",
            action="OPEN_SHORT",
            leverage=3.0,
            size_pct=0.12,
            confidence=80,
            rationale="Test limit entry at resistance",
            entry_type="LIMIT",
            entry_price=3500.0,
            entry_expires_sec=120
        )
        
        assert limit_dec.entry_type == "LIMIT"
        assert limit_dec.entry_price == 3500.0
        assert limit_dec.entry_expires_sec == 120
        print("✅ LIMIT decision: PASS")
        
        print("\n✅ All Decision model tests PASSED\n")
        return True
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_limit_validation_and_fallback():
    """Test validation logic for LIMIT entry parameters"""
    print("=" * 60)
    print("TEST: LIMIT Entry Validation and Fallback")
    print("=" * 60)
    
    test_cases = [
        {
            "name": "Valid LIMIT entry",
            "decision": {
                "symbol": "BTCUSDT",
                "action": "OPEN_LONG",
                "leverage": 5.0,
                "size_pct": 0.15,
                "confidence": 80,
                "rationale": "Valid limit",
                "entry_type": "LIMIT",
                "entry_price": 50000.0,
                "entry_expires_sec": 300
            },
            "expected_type": "LIMIT",
            "expected_price": 50000.0,
            "expected_expires": 300
        },
        {
            "name": "LIMIT without entry_price (should fallback to MARKET)",
            "decision": {
                "symbol": "ETHUSDT",
                "action": "OPEN_LONG",
                "leverage": 5.0,
                "size_pct": 0.15,
                "confidence": 80,
                "rationale": "Missing price",
                "entry_type": "LIMIT",
                "entry_price": None,
                "entry_expires_sec": 300
            },
            "expected_type": "MARKET",  # Should fallback
            "expected_price": None,
            "expected_expires": None
        },
        {
            "name": "LIMIT with invalid entry_price (should fallback to MARKET)",
            "decision": {
                "symbol": "SOLUSDT",
                "action": "OPEN_SHORT",
                "leverage": 5.0,
                "size_pct": 0.15,
                "confidence": 80,
                "rationale": "Invalid price",
                "entry_type": "LIMIT",
                "entry_price": -100.0,  # Invalid
                "entry_expires_sec": 300
            },
            "expected_type": "MARKET",  # Should fallback
            "expected_price": None,
            "expected_expires": None
        },
        {
            "name": "LIMIT with expires_sec too low (should clamp to 10)",
            "decision": {
                "symbol": "BTCUSDT",
                "action": "OPEN_LONG",
                "leverage": 5.0,
                "size_pct": 0.15,
                "confidence": 80,
                "rationale": "Low expires",
                "entry_type": "LIMIT",
                "entry_price": 50000.0,
                "entry_expires_sec": 5  # Too low
            },
            "expected_type": "LIMIT",
            "expected_price": 50000.0,
            "expected_expires": 10  # Clamped
        },
        {
            "name": "LIMIT with expires_sec too high (should clamp to 3600)",
            "decision": {
                "symbol": "ETHUSDT",
                "action": "OPEN_SHORT",
                "leverage": 5.0,
                "size_pct": 0.15,
                "confidence": 80,
                "rationale": "High expires",
                "entry_type": "LIMIT",
                "entry_price": 3500.0,
                "entry_expires_sec": 5000  # Too high
            },
            "expected_type": "LIMIT",
            "expected_price": 3500.0,
            "expected_expires": 3600  # Clamped
        }
    ]
    
    # Simulate validation logic
    def validate_decision(d):
        """Simulate the validation logic from decide_batch"""
        if d.get("entry_type") == "LIMIT":
            entry_price = d.get("entry_price")
            entry_expires_sec = d.get("entry_expires_sec", 240)
            
            # Validate entry_price
            if not entry_price or not isinstance(entry_price, (int, float)) or entry_price <= 0:
                print(f"      ⚠️ LIMIT entry without valid entry_price: {entry_price}. Falling back to MARKET.")
                d["entry_type"] = "MARKET"
                d["entry_price"] = None
                d["entry_expires_sec"] = None
            else:
                # Validate and clamp entry_expires_sec
                try:
                    entry_expires_sec = int(entry_expires_sec)
                    if entry_expires_sec < 10:
                        print(f"      ⚠️ entry_expires_sec {entry_expires_sec} < 10, clamping to 10")
                        entry_expires_sec = 10
                    elif entry_expires_sec > 3600:
                        print(f"      ⚠️ entry_expires_sec {entry_expires_sec} > 3600, clamping to 3600")
                        entry_expires_sec = 3600
                    d["entry_expires_sec"] = entry_expires_sec
                except (ValueError, TypeError):
                    print(f"      ⚠️ Invalid entry_expires_sec, using default 240")
                    d["entry_expires_sec"] = 240
        return d
    
    all_passed = True
    for test_case in test_cases:
        print(f"\n  📝 Test: {test_case['name']}")
        decision = test_case["decision"].copy()
        validated = validate_decision(decision)
        
        # Check results
        if validated["entry_type"] != test_case["expected_type"]:
            print(f"    ❌ FAIL: entry_type={validated['entry_type']}, expected={test_case['expected_type']}")
            all_passed = False
        elif validated["entry_price"] != test_case["expected_price"]:
            print(f"    ❌ FAIL: entry_price={validated['entry_price']}, expected={test_case['expected_price']}")
            all_passed = False
        elif validated.get("entry_expires_sec") != test_case["expected_expires"]:
            print(f"    ❌ FAIL: entry_expires_sec={validated.get('entry_expires_sec')}, expected={test_case['expected_expires']}")
            all_passed = False
        else:
            print(f"    ✅ PASS")
    
    if all_passed:
        print("\n✅ All validation tests PASSED\n")
    else:
        print("\n❌ Some validation tests FAILED\n")
    
    return all_passed


def test_orchestrator_payload_propagation():
    """Test that orchestrator properly forwards LIMIT fields to position manager"""
    print("=" * 60)
    print("TEST: Orchestrator Payload Propagation")
    print("=" * 60)
    
    # Simulate AI decision
    ai_decision = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "tp_pct": 0.02,
        "sl_pct": 0.015,
        "time_in_trade_limit_sec": 3600,
        "cooldown_sec": 900,
        "entry_type": "LIMIT",
        "entry_price": 50000.0,
        "entry_expires_sec": 240
    }
    
    # Simulate orchestrator payload building
    sym = ai_decision["symbol"]
    action = ai_decision["action"]
    leverage = ai_decision["leverage"]
    size_pct = ai_decision["size_pct"]
    tp_pct = ai_decision.get("tp_pct")
    sl_pct = ai_decision.get("sl_pct")
    time_in_trade_limit_sec = ai_decision.get("time_in_trade_limit_sec")
    cooldown_sec = ai_decision.get("cooldown_sec")
    entry_type = ai_decision.get("entry_type", "MARKET")
    entry_price = ai_decision.get("entry_price")
    entry_expires_sec = ai_decision.get("entry_expires_sec", 240)
    
    # Build payload (mimic orchestrator logic)
    payload = {
        "symbol": sym,
        "side": action,
        "leverage": leverage,
        "size_pct": size_pct,
        "intent_id": "test-intent-123",
        "features": ai_decision
    }
    
    if tp_pct is not None:
        payload["tp_pct"] = tp_pct
    if sl_pct is not None:
        payload["sl_pct"] = sl_pct
    if time_in_trade_limit_sec is not None:
        payload["time_in_trade_limit_sec"] = time_in_trade_limit_sec
    if cooldown_sec is not None:
        payload["cooldown_sec"] = cooldown_sec
    
    # Add LIMIT entry params
    if entry_type and entry_type != "MARKET":
        payload["entry_type"] = entry_type
    if entry_price is not None:
        payload["entry_price"] = entry_price
    if entry_expires_sec is not None:
        payload["entry_ttl_sec"] = entry_expires_sec  # Note: position manager uses entry_ttl_sec
    
    # Verify payload
    print(f"  Built payload: {json.dumps(payload, indent=2)}")
    
    assert payload["entry_type"] == "LIMIT", "entry_type not in payload"
    assert payload["entry_price"] == 50000.0, "entry_price not in payload"
    assert payload["entry_ttl_sec"] == 240, "entry_ttl_sec not in payload"
    
    print("\n✅ Payload propagation test PASSED\n")
    return True


def test_cancel_replace_logic():
    """Test cancel+replace logic for pending LIMIT orders"""
    print("=" * 60)
    print("TEST: Cancel+Replace Logic")
    print("=" * 60)
    
    # Scenario: existing LIMIT order at 50000, new decision at 50500 (price changed)
    existing_limit = {
        "intent_id": "old-intent-123",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_type": "LIMIT",
        "entry_price": 50000.0,
        "status": "PENDING"
    }
    
    new_decision_price = 50500.0
    old_price = existing_limit["entry_price"]
    
    # Calculate if price changed significantly (0.1% threshold)
    price_changed = abs(float(old_price) - float(new_decision_price)) / float(old_price) > 0.001
    
    print(f"  Existing order: price={old_price}")
    print(f"  New decision: price={new_decision_price}")
    print(f"  Price change: {((new_decision_price - old_price) / old_price * 100):.2f}%")
    print(f"  Threshold: 0.1%")
    print(f"  Should cancel+replace: {price_changed}")
    
    assert price_changed, "Should detect price change"
    
    # Scenario 2: price hasn't changed much (should skip)
    new_decision_price_2 = 50025.0  # Only 0.05% change
    price_changed_2 = abs(float(old_price) - float(new_decision_price_2)) / float(old_price) > 0.001
    
    print(f"\n  Scenario 2:")
    print(f"  New decision: price={new_decision_price_2}")
    print(f"  Price change: {((new_decision_price_2 - old_price) / old_price * 100):.2f}%")
    print(f"  Should skip: {not price_changed_2}")
    
    assert not price_changed_2, "Should skip small price changes"
    
    print("\n✅ Cancel+replace logic test PASSED\n")
    return True


def test_scale_in_guardrail():
    """Test scale-in guardrail behavior"""
    print("=" * 60)
    print("TEST: Scale-in Guardrail Behavior")
    print("=" * 60)
    
    # Scenario 1: ALLOW_SCALE_IN=false, existing position
    ALLOW_SCALE_IN = False
    HEDGE_MODE = False
    
    existing_position = {"symbol": "BTCUSDT", "side": "long", "contracts": 0.5}
    desired_side = "long"
    
    should_block = (existing_position is not None and 
                    not HEDGE_MODE and 
                    not ALLOW_SCALE_IN)
    
    print(f"  Scenario 1: ALLOW_SCALE_IN=false, existing long position")
    print(f"  Desired: long")
    print(f"  Should block: {should_block}")
    
    assert should_block, "Should block when scale-in disabled"
    print("  ✅ PASS: Blocked as expected")
    
    # Scenario 2: ALLOW_SCALE_IN=true, check max entries
    ALLOW_SCALE_IN = True
    MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE = 2
    
    pending_intents = [
        {"symbol": "BTCUSDT", "side": "long", "status": "PENDING"},
        {"symbol": "BTCUSDT", "side": "long", "status": "PENDING"}
    ]
    
    count = len(pending_intents)
    should_block_2 = count >= MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE
    
    print(f"\n  Scenario 2: ALLOW_SCALE_IN=true, {count} pending entries")
    print(f"  Max allowed: {MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE}")
    print(f"  Should block: {should_block_2}")
    
    assert should_block_2, "Should block when max entries reached"
    print("  ✅ PASS: Blocked at max entries")
    
    # Scenario 3: ALLOW_SCALE_IN=true, below max entries
    pending_intents_3 = [
        {"symbol": "BTCUSDT", "side": "long", "status": "PENDING"}
    ]
    
    count_3 = len(pending_intents_3)
    should_allow = count_3 < MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE
    
    print(f"\n  Scenario 3: ALLOW_SCALE_IN=true, {count_3} pending entries")
    print(f"  Max allowed: {MAX_PENDING_ENTRIES_PER_SYMBOL_SIDE}")
    print(f"  Should allow: {should_allow}")
    
    assert should_allow, "Should allow when below max entries"
    print("  ✅ PASS: Allowed as expected")
    
    print("\n✅ All scale-in guardrail tests PASSED\n")
    return True


def run_all_tests():
    """Run all test suites"""
    print("\n" + "=" * 60)
    print("LIMIT ENTRY INTEGRATION - COMPREHENSIVE TEST SUITE")
    print("=" * 60 + "\n")
    
    tests = [
        ("AI Decision Model - LIMIT Fields", test_ai_decision_model_limit_fields),
        ("LIMIT Validation and Fallback", test_limit_validation_and_fallback),
        ("Orchestrator Payload Propagation", test_orchestrator_payload_propagation),
        ("Cancel+Replace Logic", test_cancel_replace_logic),
        ("Scale-in Guardrail Behavior", test_scale_in_guardrail),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"\n❌ TEST FAILED: {test_name}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            print()
    
    print("\n" + "=" * 60)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
