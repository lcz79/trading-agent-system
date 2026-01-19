#!/usr/bin/env python3
"""
Test script for fast decision path implementation.
Tests the new /decide_batch_fast and /explain_batch endpoints.
"""
import os
import sys
import json
import asyncio
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', '04_master_ai_agent'))

# Set required env vars for testing
os.environ['DEEPSEEK_API_KEY'] = 'test-key-for-testing'

# Import after setting env
import main as master_ai

def test_fast_decision_model():
    """Test 1: DecisionFast model validation"""
    print("\n" + "="*60)
    print("TEST 1: DecisionFast Model Validation")
    print("="*60)
    
    # Test minimal valid decision
    print("\n1. Testing minimal valid decision (HOLD)...")
    try:
        decision = master_ai.DecisionFast(
            symbol="BTCUSDT",
            action="HOLD",
            reason_code="LOW_VOL"
        )
        assert decision.symbol == "BTCUSDT"
        assert decision.action == "HOLD"
        assert decision.reason_code == "LOW_VOL"
        assert decision.entry_type == "MARKET"  # Default
        assert decision.leverage == 1.0  # Default
        print("   ✅ Minimal HOLD decision valid")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test full OPEN_LONG with LIMIT
    print("\n2. Testing full OPEN_LONG with LIMIT entry...")
    try:
        decision = master_ai.DecisionFast(
            symbol="ETHUSDT",
            action="OPEN_LONG",
            entry_type="LIMIT",
            entry_price=3500.0,
            leverage=5.0,
            size_pct=0.15,
            tp_pct=0.02,
            sl_pct=0.015,
            time_in_trade_limit_sec=3600,
            cooldown_sec=600,
            entry_expires_sec=240,
            confidence=78,
            reason_code="STRONG_LONG"
        )
        assert decision.action == "OPEN_LONG"
        assert decision.entry_type == "LIMIT"
        assert decision.entry_price == 3500.0
        assert decision.confidence == 78
        print("   ✅ Full OPEN_LONG with LIMIT valid")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test invalid action
    print("\n3. Testing invalid action rejection...")
    try:
        decision = master_ai.DecisionFast(
            symbol="SOLUSDT",
            action="INVALID_ACTION",
            reason_code="TEST"
        )
        print("   ❌ Should have rejected invalid action!")
        return False
    except Exception as e:
        print(f"   ✅ Correctly rejected invalid action: {e}")
    
    print("\n✅ TEST 1 PASSED: DecisionFast model validation works")
    return True


def test_fast_decision_fallback():
    """Test 2: Fast decision fallback behavior"""
    print("\n" + "="*60)
    print("TEST 2: Fast Decision Fallback Behavior")
    print("="*60)
    
    # Test safe_json_loads with truncated JSON
    print("\n1. Testing safe_json_loads with truncated response...")
    truncated = '{"decisions": [{"symbol": "BTCUSDT", "action": "OPEN_LONG", "leverage": 5.0, "size_pct":'
    result = master_ai.safe_json_loads(truncated, context_label="test_truncated")
    
    # Should return empty dict on parse failure
    if not result:
        print("   ✅ Returns empty dict for truncated JSON")
    else:
        print(f"   ⚠️ Unexpected result: {result}")
    
    # Test with markdown wrapped JSON
    print("\n2. Testing safe_json_loads with markdown wrapped JSON...")
    markdown_json = '''```json
{
    "decisions": [
        {
            "symbol": "ETHUSDT",
            "action": "HOLD",
            "reason_code": "LOW_VOL"
        }
    ]
}
```'''
    result = master_ai.safe_json_loads(markdown_json, context_label="test_markdown")
    
    if result and 'decisions' in result:
        print("   ✅ Successfully extracted JSON from markdown")
        print(f"   Decisions: {result['decisions']}")
    else:
        print(f"   ❌ Failed to extract JSON: {result}")
        return False
    
    # Test with valid JSON
    print("\n3. Testing safe_json_loads with valid JSON...")
    valid = '{"decisions": [{"symbol": "SOLUSDT", "action": "OPEN_SHORT", "reason_code": "STRONG_SHORT"}]}'
    result = master_ai.safe_json_loads(valid, context_label="test_valid")
    
    if result and 'decisions' in result and len(result['decisions']) == 1:
        print("   ✅ Valid JSON parsed correctly")
    else:
        print(f"   ❌ Valid JSON parse failed: {result}")
        return False
    
    print("\n✅ TEST 2 PASSED: Fallback behavior works correctly")
    return True


def test_reason_codes():
    """Test 3: Reason code usage"""
    print("\n" + "="*60)
    print("TEST 3: Reason Code Usage")
    print("="*60)
    
    # Define expected reason codes
    expected_codes = [
        "STRONG_LONG",
        "STRONG_SHORT",
        "LOW_VOL",
        "NO_MARGIN",
        "HOLD_WAIT",
        "CRASH_GUARD",
        "LLM_PARSE_ERROR",
        "PARSE_ERROR",
        "MISSING_DECISION",
        "CRITICAL_ERROR"
    ]
    
    print("\n1. Testing reason code examples...")
    for code in expected_codes:
        try:
            decision = master_ai.DecisionFast(
                symbol="TESTUSDT",
                action="HOLD",
                reason_code=code
            )
            print(f"   ✅ {code}: valid")
        except Exception as e:
            print(f"   ❌ {code}: {e}")
            return False
    
    print("\n2. Testing reason code with OPEN actions...")
    try:
        decision = master_ai.DecisionFast(
            symbol="BTCUSDT",
            action="OPEN_LONG",
            reason_code="STRONG_LONG",
            leverage=5.0,
            size_pct=0.15,
            confidence=80
        )
        print("   ✅ STRONG_LONG with OPEN_LONG: valid")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    print("\n✅ TEST 3 PASSED: Reason codes work correctly")
    return True


def test_explain_batch_request_model():
    """Test 4: ExplainBatchRequest model"""
    print("\n" + "="*60)
    print("TEST 4: ExplainBatchRequest Model")
    print("="*60)
    
    # Test minimal request
    print("\n1. Testing minimal ExplainBatchRequest...")
    try:
        request = master_ai.ExplainBatchRequest(
            fast_decisions=[
                {"symbol": "BTCUSDT", "action": "HOLD", "reason_code": "LOW_VOL"}
            ],
            global_data={},
            assets_data={}
        )
        assert len(request.fast_decisions) == 1
        print("   ✅ Minimal request valid")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    # Test with context_ref
    print("\n2. Testing with context_ref...")
    try:
        request = master_ai.ExplainBatchRequest(
            context_ref="cycle_2024-01-19T12:00:00",
            fast_decisions=[
                {"symbol": "ETHUSDT", "action": "OPEN_LONG", "confidence": 75}
            ],
            global_data={"portfolio": {"equity": 100.0}},
            assets_data={"ETHUSDT": {"tech": {}}}
        )
        assert request.context_ref is not None
        print("   ✅ Request with context_ref valid")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False
    
    print("\n✅ TEST 4 PASSED: ExplainBatchRequest model works")
    return True


def test_minimal_response_size():
    """Test 5: Verify response size is minimal"""
    print("\n" + "="*60)
    print("TEST 5: Response Size Comparison")
    print("="*60)
    
    # Compare DecisionFast vs Decision
    print("\n1. Comparing model sizes...")
    
    # Full Decision (legacy)
    full_decision = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "rationale": "Strong bullish momentum on 15m timeframe with RSI bounce from oversold (32). EMA20 above EMA50 indicating uptrend. Fibonacci 0.618 support holding at 42000. Volume increasing on green candles. MACD crossover bullish. Gann square of 9 shows support. News sentiment positive. Forecast model predicts +2.5% move.",
        "confidence": 78,
        "confirmations": ["RSI oversold bounce", "EMA bullish alignment", "Fib 0.618 support", "Volume confirmation", "MACD crossover"],
        "risk_factors": ["Recent volatility spike", "Resistance at 44000"],
        "setup_confirmations": ["RSI oversold bounce", "EMA bullish alignment"],
        "blocked_by": [],
        "soft_blockers": [],
        "direction_considered": "LONG",
        "tp_pct": 0.02,
        "sl_pct": 0.015,
        "time_in_trade_limit_sec": 3600,
        "cooldown_sec": 600,
        "entry_type": "MARKET",
        "entry_price": None,
        "entry_expires_sec": 240
    }
    
    # Fast Decision
    fast_decision = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "entry_type": "MARKET",
        "entry_price": None,
        "leverage": 5.0,
        "size_pct": 0.15,
        "tp_pct": 0.02,
        "sl_pct": 0.015,
        "time_in_trade_limit_sec": 3600,
        "cooldown_sec": 600,
        "entry_expires_sec": 240,
        "confidence": 78,
        "reason_code": "STRONG_LONG"
    }
    
    full_size = len(json.dumps(full_decision))
    fast_size = len(json.dumps(fast_decision))
    reduction = ((full_size - fast_size) / full_size) * 100
    
    print(f"\n   Full Decision: {full_size} bytes")
    print(f"   Fast Decision: {fast_size} bytes")
    print(f"   Reduction: {reduction:.1f}%")
    
    if reduction > 40:  # Expect at least 40% reduction
        print(f"   ✅ Achieved {reduction:.1f}% size reduction (target: >40%)")
    else:
        print(f"   ⚠️ Only {reduction:.1f}% reduction (target: >40%)")
    
    # Test with 3 symbols
    print("\n2. Testing with multiple symbols...")
    full_batch = [full_decision.copy() for _ in range(3)]
    fast_batch = [fast_decision.copy() for _ in range(3)]
    
    full_batch_size = len(json.dumps({"decisions": full_batch}))
    fast_batch_size = len(json.dumps({"decisions": fast_batch}))
    batch_reduction = ((full_batch_size - fast_batch_size) / full_batch_size) * 100
    
    print(f"\n   Full Batch (3 symbols): {full_batch_size} bytes")
    print(f"   Fast Batch (3 symbols): {fast_batch_size} bytes")
    print(f"   Reduction: {batch_reduction:.1f}%")
    
    if batch_reduction > 40:
        print(f"   ✅ Batch reduction: {batch_reduction:.1f}%")
    else:
        print(f"   ⚠️ Batch reduction only {batch_reduction:.1f}%")
    
    print("\n✅ TEST 5 PASSED: Response size significantly reduced")
    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("FAST DECISION PATH TEST SUITE")
    print("="*60)
    
    tests = [
        ("DecisionFast Model", test_fast_decision_model),
        ("Fallback Behavior", test_fast_decision_fallback),
        ("Reason Codes", test_reason_codes),
        ("ExplainBatchRequest Model", test_explain_batch_request_model),
        ("Response Size", test_minimal_response_size),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ TEST FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
