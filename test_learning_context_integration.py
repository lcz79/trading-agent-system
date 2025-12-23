#!/usr/bin/env python3
"""
Manual integration test for learning context.
This script tests the actual HTTP endpoints when services are running.

Prerequisites:
- docker-compose up (all services running)
- Learning Agent has some trading history data

Usage:
    python3 test_learning_context_integration.py
"""
import json
import sys
import time
from datetime import datetime

try:
    import httpx
except ImportError:
    print("❌ httpx not installed. Install with: pip install httpx")
    sys.exit(1)


def test_learning_agent_health():
    """Test 1: Verify Learning Agent is running"""
    print("\n" + "="*60)
    print("Test 1: Learning Agent Health Check")
    print("="*60)
    
    try:
        response = httpx.get("http://localhost:8010/health", timeout=5.0)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Response: {json.dumps(data, indent=2)}")
            print("✅ Learning Agent is running")
            return True
        else:
            print(f"❌ Unexpected status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Failed to connect to Learning Agent: {e}")
        print("   Make sure services are running: docker-compose up")
        return False


def test_learning_context_endpoint():
    """Test 2: Fetch learning_context from Learning Agent"""
    print("\n" + "="*60)
    print("Test 2: Learning Context Endpoint")
    print("="*60)
    
    try:
        response = httpx.get("http://localhost:8010/learning_context", timeout=10.0)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # Verify structure
            required_fields = ["status", "period_hours", "as_of", "performance", 
                             "recent_trades", "by_symbol", "risk_flags"]
            
            print("\n📋 Learning Context Structure:")
            for field in required_fields:
                has_field = field in data
                status = "✅" if has_field else "❌"
                print(f"{status} {field}: {has_field}")
            
            # Print details
            print(f"\n📊 Performance Metrics:")
            perf = data.get("performance", {})
            print(f"   - Total trades: {perf.get('total_trades', 0)}")
            print(f"   - Win rate: {perf.get('win_rate', 0)*100:.1f}%")
            print(f"   - Total PnL: {perf.get('total_pnl', 0):.2f}%")
            print(f"   - Max drawdown: {perf.get('max_drawdown', 0):.2f}%")
            
            print(f"\n📈 Recent Trades:")
            recent = data.get("recent_trades", [])
            print(f"   - Count: {len(recent)}")
            if recent:
                print(f"   - Last 3 trades:")
                for trade in recent[-3:]:
                    ts = trade.get('timestamp', 'N/A')[:19]
                    sym = trade.get('symbol', 'UNK')
                    pnl = trade.get('pnl_pct', 0)
                    print(f"     • [{ts}] {sym}: {pnl:+.2f}%")
            
            print(f"\n🎯 Per-Symbol Stats:")
            by_symbol = data.get("by_symbol", {})
            if by_symbol:
                for symbol, stats in by_symbol.items():
                    print(f"   - {symbol}: {stats.get('total_trades', 0)} trades, "
                          f"win_rate={stats.get('win_rate', 0)*100:.0f}%, "
                          f"pnl={stats.get('total_pnl', 0):.1f}%")
            else:
                print("   - No per-symbol data yet")
            
            print(f"\n🚨 Risk Flags:")
            risk = data.get("risk_flags", {})
            print(f"   - Losing streak: {risk.get('losing_streak_count', 0)}")
            print(f"   - Last trade PnL: {risk.get('last_trade_pnl_pct', 0):.2f}%")
            print(f"   - Negative PnL period: {risk.get('negative_pnl_period', False)}")
            print(f"   - High drawdown: {risk.get('high_drawdown_period', False)}")
            
            # Verify all required fields present
            all_present = all(field in data for field in required_fields)
            if all_present:
                print("\n✅ Learning context endpoint returns correct structure")
                return True
            else:
                print("\n❌ Some required fields missing")
                return False
        else:
            print(f"❌ Unexpected status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Failed to fetch learning context: {e}")
        return False


def test_orchestrator_integration():
    """Test 3: Verify orchestrator would include learning_context (simulation)"""
    print("\n" + "="*60)
    print("Test 3: Orchestrator Integration (Simulation)")
    print("="*60)
    
    print("📝 Simulating orchestrator behavior...")
    
    try:
        # Fetch learning_context like orchestrator does
        response = httpx.get("http://localhost:8010/learning_context", timeout=5.0)
        
        if response.status_code == 200:
            learning_context = response.json()
            
            # Simulate orchestrator's global_data construction
            simulated_payload = {
                "learning_params": {},  # From fetch_learning_params()
                "global_data": {
                    "portfolio": {"equity": 1000, "available": 900},
                    "already_open": [],
                    "max_positions": 3,
                    "positions_open_count": 0,
                    "learning_context": learning_context  # NEW: Added by orchestrator
                },
                "assets_data": {}
            }
            
            print("✅ Orchestrator would construct payload with learning_context:")
            print(f"   - global_data has 'learning_context': {'learning_context' in simulated_payload['global_data']}")
            print(f"   - learning_context status: {learning_context.get('status')}")
            print(f"   - learning_context has performance: {'performance' in learning_context}")
            
            return True
        else:
            print(f"❌ Failed to fetch learning_context: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Simulation failed: {e}")
        return False


def test_empty_history_resilience():
    """Test 4: Verify endpoint works with no trading history"""
    print("\n" + "="*60)
    print("Test 4: Empty History Resilience")
    print("="*60)
    
    print("📝 This test verifies the endpoint returns success even with no history")
    print("   (The actual resilience is tested in unit tests)")
    
    try:
        response = httpx.get("http://localhost:8010/learning_context", timeout=5.0)
        
        if response.status_code == 200:
            data = response.json()
            
            # Even with no history, should return success
            status = data.get("status")
            print(f"✅ Status: {status}")
            
            # Check structure is present even if empty
            has_structure = all(k in data for k in ["performance", "recent_trades", "by_symbol", "risk_flags"])
            print(f"✅ Has required structure: {has_structure}")
            
            return status == "success" and has_structure
        else:
            print(f"❌ Unexpected status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_logging_output():
    """Test 5: Verify orchestrator logging would show context usage"""
    print("\n" + "="*60)
    print("Test 5: Logging Verification")
    print("="*60)
    
    print("📝 Checking if learning_context can be logged properly...")
    
    try:
        response = httpx.get("http://localhost:8010/learning_context", timeout=5.0)
        
        if response.status_code == 200:
            data = response.json()
            
            # Simulate orchestrator logging
            if data.get("status") == "success":
                perf = data.get("performance", {})
                recent_trades_count = len(data.get("recent_trades", []))
                trades_in_window = perf.get("total_trades", 0)
                pnl = perf.get("total_pnl", 0)
                win_rate = perf.get("win_rate", 0) * 100
                
                log_message = (
                    f"🧠 Learning context: "
                    f"last_N={recent_trades_count}, "
                    f"trades_in_window={trades_in_window}, "
                    f"pnl={pnl:.2f}%, "
                    f"win_rate={win_rate:.1f}%"
                )
                
                print(f"\n✅ Simulated orchestrator log message:")
                print(f"   {log_message}")
                return True
            else:
                print(f"❌ Status not success: {data.get('status')}")
                return False
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def main():
    """Run all integration tests"""
    print("="*60)
    print("LEARNING CONTEXT INTEGRATION TESTS")
    print("="*60)
    print("\nPrerequisites:")
    print("- Docker containers running: docker-compose up")
    print("- Learning Agent at http://localhost:8010")
    print()
    
    # Run tests
    results = []
    
    # Test 1: Health check (prerequisite)
    health_ok = test_learning_agent_health()
    if not health_ok:
        print("\n❌ Learning Agent not available. Cannot continue tests.")
        print("   Start services with: docker-compose up")
        return 1
    
    # Test 2: Learning context endpoint
    results.append(("Learning Context Endpoint", test_learning_context_endpoint()))
    
    # Test 3: Orchestrator integration
    results.append(("Orchestrator Integration", test_orchestrator_integration()))
    
    # Test 4: Empty history resilience
    results.append(("Empty History Resilience", test_empty_history_resilience()))
    
    # Test 5: Logging
    results.append(("Logging Output", test_logging_output()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✅ ALL INTEGRATION TESTS PASSED")
        print("\nNext steps:")
        print("1. Check orchestrator logs for: '🧠 Learning context:' messages")
        print("2. Verify Master AI prompt includes learning_context")
        print("3. Monitor AI decisions to see if context affects trading")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
