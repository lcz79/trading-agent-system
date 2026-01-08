#!/usr/bin/env python3
"""
Test suite for soft blockers implementation.
Validates that HARD blockers force HOLD while SOFT blockers allow OPEN with proper justification.
"""

import sys
import json
from pathlib import Path

# Add agents directory to path
sys.path.insert(0, str(Path(__file__).parent / 'agents' / '04_master_ai_agent'))

from main import enforce_decision_consistency, Decision


def test_hard_blocker_forces_hold():
    """Test that HARD blockers in blocked_by force HOLD action"""
    print("\n" + "="*60)
    print("TEST 1: HARD blocker should force HOLD")
    print("="*60)
    
    decision = {
        'symbol': 'BTCUSDT',
        'action': 'OPEN_LONG',
        'leverage': 5.0,
        'size_pct': 0.15,
        'confidence': 75,
        'rationale': 'Strong setup',
        'setup_confirmations': ['RSI oversold', 'Support level', 'Volume spike'],
        'blocked_by': ['INSUFFICIENT_MARGIN'],
        'direction_considered': 'LONG'
    }
    
    result = enforce_decision_consistency(decision)
    
    assert result['action'] == 'HOLD', f"Expected HOLD but got {result['action']}"
    assert 'INSUFFICIENT_MARGIN' in result['blocked_by'], "INSUFFICIENT_MARGIN should remain in blocked_by"
    print(f"✅ PASS: Action forced to HOLD when HARD blocker present")
    print(f"   blocked_by: {result['blocked_by']}")
    print(f"   action: {result['action']}")
    

def test_soft_blocker_allows_open():
    """Test that SOFT blockers in soft_blockers do NOT force HOLD"""
    print("\n" + "="*60)
    print("TEST 2: SOFT blocker should NOT force HOLD")
    print("="*60)
    
    decision = {
        'symbol': 'ETHUSDT',
        'action': 'OPEN_SHORT',
        'leverage': 4.0,
        'size_pct': 0.12,
        'confidence': 55,
        'rationale': 'Moderate confidence but 4 strong confirmations justify entry',
        'setup_confirmations': ['Resistance rejection', 'RSI overbought', 'Bearish momentum', 'Volume increase'],
        'blocked_by': [],  # No HARD blockers
        'soft_blockers': ['LOW_CONFIDENCE'],  # SOFT warning
        'direction_considered': 'SHORT'
    }
    
    result = enforce_decision_consistency(decision)
    
    assert result['action'] == 'OPEN_SHORT', f"Expected OPEN_SHORT but got {result['action']}"
    assert not result.get('blocked_by'), "blocked_by should be empty (no HARD blockers)"
    assert 'LOW_CONFIDENCE' in result.get('soft_blockers', []), "LOW_CONFIDENCE should remain in soft_blockers"
    print(f"✅ PASS: Action remains OPEN_SHORT with SOFT blocker present")
    print(f"   blocked_by: {result.get('blocked_by', [])}")
    print(f"   soft_blockers: {result.get('soft_blockers', [])}")
    print(f"   action: {result['action']}")


def test_backward_compatibility_migration():
    """Test that legacy soft reasons in blocked_by are migrated to soft_blockers"""
    print("\n" + "="*60)
    print("TEST 3: Backward compatibility - migrate soft reasons")
    print("="*60)
    
    decision = {
        'symbol': 'SOLUSDT',
        'action': 'HOLD',
        'leverage': 0,
        'size_pct': 0,
        'confidence': 45,
        'rationale': 'Low confidence setup',
        'setup_confirmations': [],
        'blocked_by': ['LOW_CONFIDENCE', 'CONFLICTING_SIGNALS'],  # Legacy soft reasons in blocked_by
        'direction_considered': 'NONE'
    }
    
    result = enforce_decision_consistency(decision)
    
    # blocked_by should now be empty (soft reasons migrated)
    assert not result.get('blocked_by'), f"blocked_by should be empty after migration but got {result.get('blocked_by')}"
    
    # soft_blockers should contain the migrated reasons
    soft = result.get('soft_blockers', [])
    assert 'LOW_CONFIDENCE' in soft, "LOW_CONFIDENCE should be migrated to soft_blockers"
    assert 'CONFLICTING_SIGNALS' in soft, "CONFLICTING_SIGNALS should be migrated to soft_blockers"
    
    print(f"✅ PASS: Legacy soft reasons migrated from blocked_by to soft_blockers")
    print(f"   blocked_by (after): {result.get('blocked_by', [])}")
    print(f"   soft_blockers (after): {result.get('soft_blockers', [])}")


def test_mixed_hard_and_soft():
    """Test handling of both HARD and SOFT blockers together"""
    print("\n" + "="*60)
    print("TEST 4: Mixed HARD and SOFT blockers")
    print("="*60)
    
    decision = {
        'symbol': 'BTCUSDT',
        'action': 'OPEN_LONG',
        'leverage': 5.0,
        'size_pct': 0.15,
        'confidence': 60,
        'rationale': 'Decent setup but system constraints active',
        'setup_confirmations': ['Support level', 'RSI neutral'],
        'blocked_by': ['MAX_POSITIONS'],  # HARD blocker
        'soft_blockers': ['CONFLICTING_SIGNALS'],  # SOFT warning
        'direction_considered': 'LONG'
    }
    
    result = enforce_decision_consistency(decision)
    
    # Should force HOLD due to HARD blocker
    assert result['action'] == 'HOLD', f"Expected HOLD due to HARD blocker but got {result['action']}"
    assert 'MAX_POSITIONS' in result['blocked_by'], "MAX_POSITIONS should remain in blocked_by"
    assert 'CONFLICTING_SIGNALS' in result.get('soft_blockers', []), "CONFLICTING_SIGNALS should remain in soft_blockers"
    
    print(f"✅ PASS: HARD blocker forces HOLD even with SOFT blocker present")
    print(f"   blocked_by: {result['blocked_by']}")
    print(f"   soft_blockers: {result.get('soft_blockers', [])}")
    print(f"   action: {result['action']}")


def test_decision_model_validation():
    """Test that Decision model accepts soft_blockers field"""
    print("\n" + "="*60)
    print("TEST 5: Decision model validation with soft_blockers")
    print("="*60)
    
    try:
        decision = Decision(
            symbol='ETHUSDT',
            action='OPEN_LONG',
            leverage=5.0,
            size_pct=0.15,
            confidence=80,
            rationale='Strong bullish setup with multiple confirmations',
            setup_confirmations=['RSI oversold', 'Support bounce', 'Volume surge', 'Bullish momentum'],
            blocked_by=[],  # No HARD blockers
            soft_blockers=['LOW_CONFIDENCE'],  # SOFT warning (even though confidence is 80)
            direction_considered='LONG',
            tp_pct=0.02,
            sl_pct=0.015,
            time_in_trade_limit_sec=3600,
            cooldown_sec=900
        )
        
        assert decision.soft_blockers == ['LOW_CONFIDENCE'], "soft_blockers not set correctly"
        assert decision.blocked_by == [], "blocked_by should be empty"
        
        print(f"✅ PASS: Decision model accepts and validates soft_blockers field")
        print(f"   Model: {decision.model_dump()}")
        
    except Exception as e:
        print(f"❌ FAIL: Decision model validation failed: {e}")
        raise


def test_infer_soft_blockers_on_hold():
    """Test that soft blockers are inferred when action is HOLD with low confidence"""
    print("\n" + "="*60)
    print("TEST 6: Infer soft_blockers on HOLD with low confidence")
    print("="*60)
    
    decision = {
        'symbol': 'SOLUSDT',
        'action': 'HOLD',
        'leverage': 0,
        'size_pct': 0,
        'confidence': 35,  # Below threshold
        'rationale': 'Uncertain market conditions',
        'setup_confirmations': [],
        'direction_considered': 'NONE'
    }
    
    result = enforce_decision_consistency(decision)
    
    # Should infer soft_blockers since confidence is low and no hard blockers
    assert result.get('soft_blockers'), "soft_blockers should be inferred for low confidence HOLD"
    assert 'LOW_CONFIDENCE' in result.get('soft_blockers', []), "LOW_CONFIDENCE should be inferred"
    assert not result.get('blocked_by'), "blocked_by should remain empty"
    
    print(f"✅ PASS: soft_blockers inferred for HOLD with low confidence")
    print(f"   blocked_by: {result.get('blocked_by', [])}")
    print(f"   soft_blockers: {result.get('soft_blockers', [])}")


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*80)
    print(" SOFT BLOCKERS IMPLEMENTATION TEST SUITE")
    print("="*80)
    
    tests = [
        test_hard_blocker_forces_hold,
        test_soft_blocker_allows_open,
        test_backward_compatibility_migration,
        test_mixed_hard_and_soft,
        test_decision_model_validation,
        test_infer_soft_blockers_on_hold
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   Error: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ ERROR in {test.__name__}: {e}")
            failed += 1
    
    print("\n" + "="*80)
    print(f" TEST RESULTS: {passed} passed, {failed} failed")
    print("="*80)
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
