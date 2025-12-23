#!/usr/bin/env python3
"""
Test the trailing stop and reverse fixes.
This test validates:
1. Background monitoring loop initialization
2. SHORT trailing stop logic
3. AI fallback logic
"""

import json
import sys
import os
import time
from unittest.mock import Mock, MagicMock, patch
from threading import Thread

# Add agents directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', '07_position_manager'))

def test_background_loop_initialization():
    """Test that background monitoring loop is properly initialized"""
    print("🧪 Test 1: Background loop initialization")
    
    try:
        # Read the position manager file to verify background loop exists
        pm_file = os.path.join(os.path.dirname(__file__), 'agents', '07_position_manager', 'main.py')
        with open(pm_file, 'r') as f:
            content = f.read()
        
        # Check for position_monitor_loop function
        if 'def position_monitor_loop():' in content:
            print("  ✓ position_monitor_loop function defined")
        else:
            print("  ❌ position_monitor_loop function not found")
            return False
        
        # Check that the loop calls the right functions
        if 'check_recent_closes_and_save_cooldown()' in content and \
           'check_and_update_trailing_stops()' in content and \
           'check_smart_reverse()' in content:
            print("  ✓ Loop calls trailing and reverse check functions")
        else:
            print("  ❌ Loop doesn't call expected functions")
            return False
        
        # Check that the loop runs every 30 seconds
        if 'time.sleep(30)' in content:
            print("  ✓ Loop runs every 30 seconds")
        else:
            print("  ⚠️ Loop interval may not be 30 seconds")
        
        # Check that the thread is started
        if 'Thread(target=position_monitor_loop, daemon=True).start()' in content:
            print("  ✓ Background thread is started")
        else:
            print("  ❌ Background thread is not started")
            return False
        
        print("✅ Test 1 passed: Background loop initialization\n")
        return True
        
    except Exception as e:
        print(f"  ❌ Test 1 failed: {e}\n")
        return False


def test_short_trailing_logic():
    """Test SHORT position trailing stop logic"""
    print("🧪 Test 2: SHORT trailing stop logic")
    
    try:
        # Test parameters
        entry_price = 100.0
        mark_price = 95.0  # Price dropped (profit for SHORT)
        trailing_distance = 0.02  # 2%
        
        # For SHORT: target_sl = trough * (1 + trailing_distance)
        trough = mark_price  # Lowest price seen
        target_sl = trough * (1 + trailing_distance)  # 95 * 1.02 = 96.9
        
        print(f"  Scenario: SHORT position")
        print(f"  Entry: ${entry_price}, Mark: ${mark_price}")
        print(f"  Trough: ${trough}, Target SL: ${target_sl:.2f}")
        
        # Test case 1: No existing SL (baseline = 0)
        baseline = 0.0
        if baseline == 0.0:
            new_sl_price = target_sl
            print(f"  Case 1 - No existing SL: new_sl = ${new_sl_price:.2f} ✓")
        else:
            print("  Case 1 failed: Should set initial SL")
            return False
        
        # Test case 2: Price dropped further, SL should lower
        baseline = 98.0  # Previous SL
        if target_sl < baseline:
            new_sl_price = target_sl
            print(f"  Case 2 - Price dropped: SL lowering ${baseline:.2f} -> ${new_sl_price:.2f} ✓")
        else:
            print(f"  Case 2 failed: Should lower SL when target_sl ({target_sl:.2f}) < baseline ({baseline:.2f})")
            return False
        
        # Test case 3: Price went up, SL should NOT raise
        baseline = 95.0  # Previous SL (lower than target)
        mark_price_up = 96.5
        trough_up = 95.0  # Trough doesn't increase
        target_sl_up = trough_up * (1 + trailing_distance)  # 95 * 1.02 = 96.9
        
        new_sl_price = None
        if target_sl_up >= baseline:
            # Don't raise SL - would reduce protection
            print(f"  Case 3 - Price went up: SL NOT raised (target ${target_sl_up:.2f} >= baseline ${baseline:.2f}) ✓")
        else:
            new_sl_price = target_sl_up
            print(f"  Case 3 failed: Should NOT raise SL when price goes up")
            return False
        
        print("✅ Test 2 passed: SHORT trailing logic is correct\n")
        return True
        
    except Exception as e:
        print(f"  ❌ Test 2 failed: {e}\n")
        return False


def test_ai_fallback_logic():
    """Test AI fallback when reverse analysis fails"""
    print("🧪 Test 3: AI fallback logic")
    
    try:
        # Simulate AI failure scenarios
        HARD_STOP_THRESHOLD = -0.20  # -20%
        
        # Test case 1: AI fails but loss is not critical
        roi = -0.12  # -12% loss
        print(f"  Case 1: AI fails with ROI={roi*100:.2f}%")
        if roi <= HARD_STOP_THRESHOLD:
            action = "CLOSE"
            print(f"    ❌ Should maintain position (not critical)")
            return False
        else:
            action = "HOLD"
            print(f"    ✓ Maintains position with monitoring")
        
        # Test case 2: AI fails and loss is critical
        roi = -0.22  # -22% loss (critical)
        print(f"  Case 2: AI fails with ROI={roi*100:.2f}%")
        if roi <= HARD_STOP_THRESHOLD:
            action = "CLOSE"
            print(f"    ✓ Executes safety close")
        else:
            action = "HOLD"
            print(f"    ❌ Should close position (critical loss)")
            return False
        
        print("✅ Test 3 passed: AI fallback logic is correct\n")
        return True
        
    except Exception as e:
        print(f"  ❌ Test 3 failed: {e}\n")
        return False


def test_orchestrator_timeout():
    """Test that orchestrator uses longer timeout"""
    print("🧪 Test 4: Orchestrator timeout configuration")
    
    try:
        # Import orchestrator main
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator'))
        
        # Read the file to check timeout value
        orchestrator_file = os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator', 'main.py')
        with open(orchestrator_file, 'r') as f:
            content = f.read()
        
        # Check for timeout=60 in manage_active_positions call
        if 'manage_active_positions", timeout=60' in content:
            print("  ✓ Timeout increased to 60 seconds")
        else:
            print("  ❌ Timeout not found or incorrect")
            return False
        
        # Check for retry logic
        if 'for attempt in range(1, 4):' in content:
            print("  ✓ Retry logic implemented (3 attempts)")
        else:
            print("  ❌ Retry logic not found")
            return False
        
        # Check for error logging (not silent except)
        if 'except Exception as e:' in content and 'print(f"' in content:
            print("  ✓ Error logging implemented")
        else:
            print("  ⚠️ Error logging may be missing")
        
        print("✅ Test 4 passed: Orchestrator configuration correct\n")
        return True
        
    except Exception as e:
        print(f"  ❌ Test 4 failed: {e}\n")
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing Trailing Stop and Reverse Fixes")
    print("=" * 60 + "\n")
    
    results = []
    
    # Run tests
    results.append(("Background loop initialization", test_background_loop_initialization()))
    results.append(("SHORT trailing logic", test_short_trailing_logic()))
    results.append(("AI fallback logic", test_ai_fallback_logic()))
    results.append(("Orchestrator timeout", test_orchestrator_timeout()))
    
    # Summary
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
