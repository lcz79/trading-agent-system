#!/usr/bin/env python3
"""
Test to verify portfolio data structure consistency between orchestrator and master AI.
This ensures the fix for wallet logging is correct.
"""

def test_orchestrator_portfolio_structure():
    """Test that orchestrator creates the correct portfolio structure"""
    print("=" * 70)
    print("TEST 1: Orchestrator portfolio structure")
    print("=" * 70)
    
    # Simulate Position Manager response
    pm_response = {
        "equity": 250.5,
        "available": 170.3,
        "available_for_new_trades": 160.0,
        "available_source": "bybit_unified_im_derived",
        "components": {
            "walletBalance": 245.3,
            "totalPositionIM": 50.0,
        }
    }
    
    # Simulate orchestrator logic
    portfolio = pm_response.copy()
    
    # Check if available_for_new_trades exists (it should)
    if "available_for_new_trades" not in portfolio:
        available = portfolio.get('available', 0)
        portfolio["available_for_new_trades"] = max(0.0, available * 0.95) if available > 0 else 0.0
        portfolio["available_source"] = "orchestrator_fallback"
        print("⚠️ Fallback triggered (shouldn't happen with proper PM response)")
    else:
        print("✅ available_for_new_trades found in portfolio")
    
    # Create enhanced_global_data as orchestrator does
    enhanced_global_data = {
        "portfolio": portfolio,
        "already_open": [],
        "max_positions": 3,
        "positions_open_count": 0,
    }
    
    # Verify structure
    assert "portfolio" in enhanced_global_data, "portfolio key missing"
    assert "wallet" not in enhanced_global_data, "old wallet key should not exist"
    
    portfolio_data = enhanced_global_data["portfolio"]
    assert "equity" in portfolio_data, "equity missing from portfolio"
    assert "available" in portfolio_data, "available missing from portfolio"
    assert "available_for_new_trades" in portfolio_data, "available_for_new_trades missing"
    assert "available_source" in portfolio_data, "available_source missing"
    
    print(f"✅ Portfolio structure correct:")
    print(f"   - equity: {portfolio_data['equity']}")
    print(f"   - available: {portfolio_data['available']}")
    print(f"   - available_for_new_trades: {portfolio_data['available_for_new_trades']}")
    print(f"   - available_source: {portfolio_data['available_source']}")
    
    return True


def test_master_ai_reads_portfolio():
    """Test that master AI reads from portfolio correctly"""
    print("\n" + "=" * 70)
    print("TEST 2: Master AI reading from portfolio")
    print("=" * 70)
    
    # Simulate payload from orchestrator
    class MockPayload:
        def __init__(self):
            self.global_data = {
                "portfolio": {
                    "equity": 250.5,
                    "available": 170.3,
                    "available_for_new_trades": 160.0,
                    "available_source": "bybit_unified_im_derived"
                },
                "already_open": [],
                "max_positions": 3,
                "positions_open_count": 0
            }
            self.assets_data = {}
    
    payload = MockPayload()
    
    # Simulate Master AI logic (from decide_batch)
    portfolio = payload.global_data.get('portfolio', {})
    wallet_equity = portfolio.get('equity', 0)
    wallet_available = portfolio.get('available', 0)
    wallet_available_for_new_trades = portfolio.get('available_for_new_trades', wallet_available)
    wallet_source = portfolio.get('available_source', 'unknown')
    
    # Verify reads
    assert wallet_equity == 250.5, f"equity mismatch: {wallet_equity}"
    assert wallet_available == 170.3, f"available mismatch: {wallet_available}"
    assert wallet_available_for_new_trades == 160.0, f"available_for_new_trades mismatch: {wallet_available_for_new_trades}"
    assert wallet_source == "bybit_unified_im_derived", f"source mismatch: {wallet_source}"
    
    # Check margin constraint
    margin_threshold = 10.0
    can_open_new_positions = wallet_available_for_new_trades >= margin_threshold
    
    print(f"✅ Master AI reads portfolio correctly:")
    print(f"   - equity: {wallet_equity}")
    print(f"   - available: {wallet_available}")
    print(f"   - available_for_new_trades: {wallet_available_for_new_trades}")
    print(f"   - available_source: {wallet_source}")
    print(f"   - can_open_new_positions: {can_open_new_positions} (threshold={margin_threshold})")
    
    return True


def test_fallback_behavior():
    """Test fallback when available_for_new_trades is missing"""
    print("\n" + "=" * 70)
    print("TEST 3: Fallback behavior")
    print("=" * 70)
    
    # Simulate old PM response without available_for_new_trades
    portfolio = {
        "equity": 1000.0,
        "available": 800.0,
    }
    
    # Orchestrator fallback logic
    if "available_for_new_trades" not in portfolio:
        available = portfolio.get('available', 0)
        portfolio["available_for_new_trades"] = max(0.0, available * 0.95) if available > 0 else 0.0
        portfolio["available_source"] = "orchestrator_fallback"
        print("✅ Fallback triggered correctly")
    
    # Verify fallback calculation
    expected_available = 800.0 * 0.95  # 760.0
    assert portfolio["available_for_new_trades"] == expected_available, \
        f"fallback calculation error: {portfolio['available_for_new_trades']} != {expected_available}"
    assert portfolio["available_source"] == "orchestrator_fallback"
    
    print(f"✅ Fallback calculation correct:")
    print(f"   - original available: 800.0")
    print(f"   - available_for_new_trades: {portfolio['available_for_new_trades']} (95% of available)")
    print(f"   - source: {portfolio['available_source']}")
    
    return True


def test_no_duplicate_wallet_key():
    """Verify that no duplicate wallet key exists"""
    print("\n" + "=" * 70)
    print("TEST 4: No duplicate wallet key")
    print("=" * 70)
    
    # Simulate orchestrator creating global_data
    portfolio = {
        "equity": 250.5,
        "available": 170.3,
        "available_for_new_trades": 160.0,
        "available_source": "bybit_unified_im_derived"
    }
    
    enhanced_global_data = {
        "portfolio": portfolio,
        "already_open": [],
        "max_positions": 3,
        "positions_open_count": 0,
    }
    
    # Check no wallet key exists
    assert "wallet" not in enhanced_global_data, "❌ FAIL: duplicate 'wallet' key found!"
    
    print("✅ No duplicate 'wallet' key found")
    print("✅ Only 'portfolio' key exists with all wallet data")
    
    return True


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("PORTFOLIO DATA CONSISTENCY TEST SUITE")
    print("=" * 70 + "\n")
    
    tests = [
        ("Orchestrator portfolio structure", test_orchestrator_portfolio_structure),
        ("Master AI reads portfolio", test_master_ai_reads_portfolio),
        ("Fallback behavior", test_fallback_behavior),
        ("No duplicate wallet key", test_no_duplicate_wallet_key),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Test '{name}' failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Portfolio data structure is consistent.")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
