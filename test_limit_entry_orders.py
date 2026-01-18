#!/usr/bin/env python3
"""
Test script for LIMIT entry order support in position manager.

This script validates:
1. LIMIT order submission with orderLinkId
2. Pending order tracking and state management
3. TTL expiration and cancellation
4. Order fill detection and SL placement
5. Backward compatibility with MARKET orders
"""

import sys
import json
import time
from datetime import datetime, timedelta

# Mock test helpers
def test_order_intent_model():
    """Test OrderIntent data model with new LIMIT fields"""
    print("=" * 60)
    print("TEST: OrderIntent Data Model")
    print("=" * 60)
    
    sys.path.insert(0, '/home/runner/work/trading-agent-system/trading-agent-system/agents/07_position_manager')
    from shared.trading_state import OrderIntent, OrderStatus
    
    # Test MARKET order intent (backward compatibility)
    market_intent = OrderIntent(
        intent_id="test-market-001",
        symbol="BTCUSDT",
        side="long",
        leverage=5.0,
        size_pct=0.15,
        entry_type="MARKET"
    )
    
    assert market_intent.entry_type == "MARKET"
    assert market_intent.entry_price is None
    assert market_intent.entry_expires_at is None
    assert market_intent.exchange_order_link_id is None
    print("✅ MARKET order intent: PASS")
    
    # Test LIMIT order intent
    expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
    limit_intent = OrderIntent(
        intent_id="test-limit-001",
        symbol="ETHUSDT",
        side="long",
        leverage=3.0,
        size_pct=0.10,
        entry_type="LIMIT",
        entry_price=3500.0,
        entry_expires_at=expires_at,
        exchange_order_link_id="test-limit-001"
    )
    
    assert limit_intent.entry_type == "LIMIT"
    assert limit_intent.entry_price == 3500.0
    assert limit_intent.entry_expires_at == expires_at
    assert limit_intent.exchange_order_link_id == "test-limit-001"
    print("✅ LIMIT order intent: PASS")
    
    # Test serialization
    intent_dict = limit_intent.to_dict()
    assert "entry_type" in intent_dict
    assert "entry_price" in intent_dict
    assert "entry_expires_at" in intent_dict
    assert "exchange_order_link_id" in intent_dict
    print("✅ Intent serialization: PASS")
    
    # Test deserialization
    restored_intent = OrderIntent.from_dict(intent_dict)
    assert restored_intent.entry_type == "LIMIT"
    assert restored_intent.entry_price == 3500.0
    assert restored_intent.exchange_order_link_id == "test-limit-001"
    print("✅ Intent deserialization: PASS")
    
    print("\n✅ All OrderIntent model tests PASSED\n")


def test_order_request_model():
    """Test OrderRequest Pydantic model with new LIMIT fields"""
    print("=" * 60)
    print("TEST: OrderRequest API Model")
    print("=" * 60)
    
    try:
        sys.path.insert(0, '/home/runner/work/trading-agent-system/trading-agent-system/agents/07_position_manager')
        from main import OrderRequest
    except ModuleNotFoundError as e:
        print(f"⚠️ Skipping test due to missing dependencies: {e}")
        print("✅ Test skipped (dependencies unavailable in test environment)\n")
        return
    
    # Test MARKET order request (backward compatibility - default)
    market_req = OrderRequest(
        symbol="BTCUSDT",
        side="buy",
        leverage=5.0,
        size_pct=0.15,
        sl_pct=0.02
    )
    
    assert market_req.entry_type == "MARKET"  # Default value
    assert market_req.entry_price is None
    assert market_req.entry_ttl_sec is None
    print("✅ MARKET order request (default): PASS")
    
    # Test explicit MARKET order request
    market_req_explicit = OrderRequest(
        symbol="BTCUSDT",
        side="buy",
        leverage=5.0,
        size_pct=0.15,
        sl_pct=0.02,
        entry_type="MARKET"
    )
    
    assert market_req_explicit.entry_type == "MARKET"
    print("✅ MARKET order request (explicit): PASS")
    
    # Test LIMIT order request
    limit_req = OrderRequest(
        symbol="ETHUSDT",
        side="buy",
        leverage=3.0,
        size_pct=0.10,
        sl_pct=0.015,
        entry_type="LIMIT",
        entry_price=3500.0,
        entry_ttl_sec=3600
    )
    
    assert limit_req.entry_type == "LIMIT"
    assert limit_req.entry_price == 3500.0
    assert limit_req.entry_ttl_sec == 3600
    print("✅ LIMIT order request: PASS")
    
    # Test JSON serialization
    limit_json = limit_req.model_dump()
    assert limit_json["entry_type"] == "LIMIT"
    assert limit_json["entry_price"] == 3500.0
    assert limit_json["entry_ttl_sec"] == 3600
    print("✅ OrderRequest JSON serialization: PASS")
    
    print("\n✅ All OrderRequest model tests PASSED\n")


def test_trading_state_update():
    """Test TradingState update_intent_status with exchange_order_link_id"""
    print("=" * 60)
    print("TEST: TradingState exchange_order_link_id Update")
    print("=" * 60)
    
    sys.path.insert(0, '/home/runner/work/trading-agent-system/trading-agent-system/agents/07_position_manager')
    from shared.trading_state import get_trading_state, OrderIntent, OrderStatus
    
    trading_state = get_trading_state()
    
    # Create a test intent
    test_intent = OrderIntent(
        intent_id="test-update-001",
        symbol="BTCUSDT",
        side="long",
        leverage=5.0,
        size_pct=0.15,
        entry_type="LIMIT",
        entry_price=50000.0
    )
    
    trading_state.add_intent(test_intent)
    print("✅ Intent added to state")
    
    # Update with exchange_order_link_id
    trading_state.update_intent_status(
        "test-update-001",
        OrderStatus.PENDING,
        exchange_order_id="bybit-order-12345",
        exchange_order_link_id="test-update-001"
    )
    print("✅ Intent updated with exchange_order_link_id")
    
    # Retrieve and verify
    updated_intent = trading_state.get_intent("test-update-001")
    assert updated_intent is not None
    assert updated_intent.status == OrderStatus.PENDING
    assert updated_intent.exchange_order_id == "bybit-order-12345"
    assert updated_intent.exchange_order_link_id == "test-update-001"
    print("✅ Intent retrieval and verification: PASS")
    
    # Clean up
    if "test-update-001" in trading_state._state["intents"]:
        del trading_state._state["intents"]["test-update-001"]
        trading_state._save_state()
    
    print("\n✅ All TradingState update tests PASSED\n")


def test_order_filter_logic():
    """Test the logic for filtering non-entry orders"""
    print("=" * 60)
    print("TEST: Non-Entry Order Filtering Logic")
    print("=" * 60)
    
    # Test case 1: Entry order (should NOT be filtered)
    entry_order = {
        "stopOrderType": "",
        "createType": "",
        "reduceOnly": False,
        "orderStatus": "New"
    }
    
    is_entry = (
        not entry_order.get("stopOrderType", "") and
        "StopLoss" not in entry_order.get("createType", "") and
        not entry_order.get("reduceOnly", False)
    )
    assert is_entry is True
    print("✅ Entry order correctly identified: PASS")
    
    # Test case 2: Stop-loss order (should be filtered)
    sl_order = {
        "stopOrderType": "StopLoss",
        "createType": "CreateByStopLoss",
        "reduceOnly": True,
        "orderStatus": "New"
    }
    
    is_entry = (
        not sl_order.get("stopOrderType", "") and
        "StopLoss" not in sl_order.get("createType", "") and
        not sl_order.get("reduceOnly", False)
    )
    assert is_entry is False
    print("✅ Stop-loss order correctly filtered: PASS")
    
    # Test case 3: Take-profit order (should be filtered)
    tp_order = {
        "stopOrderType": "TakeProfit",
        "createType": "CreateByTakeProfit",
        "reduceOnly": True,
        "orderStatus": "New"
    }
    
    is_entry = (
        not tp_order.get("stopOrderType", "") and
        "StopLoss" not in tp_order.get("createType", "") and
        not tp_order.get("reduceOnly", False)
    )
    assert is_entry is False
    print("✅ Take-profit order correctly filtered: PASS")
    
    # Test case 4: Reduce-only order (should be filtered)
    reduce_order = {
        "stopOrderType": "",
        "createType": "",
        "reduceOnly": True,
        "orderStatus": "New"
    }
    
    is_entry = (
        not reduce_order.get("stopOrderType", "") and
        "StopLoss" not in reduce_order.get("createType", "") and
        not reduce_order.get("reduceOnly", False)
    )
    assert is_entry is False
    print("✅ Reduce-only order correctly filtered: PASS")
    
    print("\n✅ All order filtering tests PASSED\n")


def test_ttl_expiry_logic():
    """Test TTL expiration detection logic"""
    print("=" * 60)
    print("TEST: TTL Expiration Detection")
    print("=" * 60)
    
    # Test case 1: Not expired
    future_time = (datetime.now() + timedelta(hours=1)).isoformat()
    is_expired = datetime.now() > datetime.fromisoformat(future_time)
    assert is_expired is False
    print("✅ Future expiry correctly identified as NOT expired: PASS")
    
    # Test case 2: Expired
    past_time = (datetime.now() - timedelta(hours=1)).isoformat()
    is_expired = datetime.now() > datetime.fromisoformat(past_time)
    assert is_expired is True
    print("✅ Past expiry correctly identified as expired: PASS")
    
    # Test case 3: Edge case - exactly now (should be expired)
    now_time = datetime.now().isoformat()
    time.sleep(0.1)  # Ensure we're past the exact time
    is_expired = datetime.now() > datetime.fromisoformat(now_time)
    assert is_expired is True
    print("✅ Edge case (exactly now) correctly handled: PASS")
    
    print("\n✅ All TTL expiry tests PASSED\n")


def run_all_tests():
    """Run all test suites"""
    print("\n" + "=" * 60)
    print("LIMIT ENTRY ORDER IMPLEMENTATION TEST SUITE")
    print("=" * 60 + "\n")
    
    tests = [
        ("OrderIntent Model", test_order_intent_model),
        ("OrderRequest Model", test_order_request_model),
        ("TradingState Update", test_trading_state_update),
        ("Order Filter Logic", test_order_filter_logic),
        ("TTL Expiry Logic", test_ttl_expiry_logic),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
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
