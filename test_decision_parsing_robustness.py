#!/usr/bin/env python3
"""
Test suite for robust AI decision parsing and validation.
Validates that decisions with LLM formatting variations are accepted.
"""

import sys
import os
from pathlib import Path
from typing import Optional, List

# Set dummy API key to avoid import errors
os.environ['DEEPSEEK_API_KEY'] = 'dummy_key_for_testing'

# Add agents directory to path
sys.path.insert(0, str(Path(__file__).parent / 'agents' / '04_master_ai_agent'))

from main import normalize_blocker_value, normalize_blocker_list, Decision


def test_normalize_blocker_with_parenthesis():
    """Test normalization of blocker values with extra info in parentheses"""
    print("\n" + "="*60)
    print("TEST 1: Normalize blockers with parentheses")
    print("="*60)
    
    # Test cases from problem statement
    assert normalize_blocker_value("LOW_PRE_SCORE (47)", "hard") == "LOW_PRE_SCORE"
    assert normalize_blocker_value("CONFLICTING_SIGNALS (trend ...)", "soft") == "CONFLICTING_SIGNALS"
    assert normalize_blocker_value("LOW_CONFIDENCE (55%)", "soft") == "LOW_CONFIDENCE"
    
    print("✅ PASS: Blockers with parentheses normalized correctly")


def test_normalize_blocker_with_spaces():
    """Test normalization of blocker values with trailing text"""
    print("\n" + "="*60)
    print("TEST 2: Normalize blockers with spaces/trailing text")
    print("="*60)
    
    assert normalize_blocker_value("LOW_PRE_SCORE extra text", "hard") == "LOW_PRE_SCORE"
    assert normalize_blocker_value("CONFLICTING_SIGNALS with details", "soft") == "CONFLICTING_SIGNALS"
    assert normalize_blocker_value("INSUFFICIENT_MARGIN available=5.2", "hard") == "INSUFFICIENT_MARGIN"
    
    print("✅ PASS: Blockers with spaces normalized correctly")


def test_normalize_blocker_aliases():
    """Test mapping of common aliases to valid values"""
    print("\n" + "="*60)
    print("TEST 3: Map common aliases to valid values")
    print("="*60)
    
    # Hard blocker aliases
    assert normalize_blocker_value("LOW_CONFIDENCE_SETUP", "hard") == "LOW_PRE_SCORE"
    assert normalize_blocker_value("INSUFFICIENT_BALANCE", "hard") == "INSUFFICIENT_MARGIN"
    assert normalize_blocker_value("MAX_POSITION", "hard") == "MAX_POSITIONS"
    assert normalize_blocker_value("KNIFE_CATCHING", "hard") == "CRASH_GUARD"
    
    # Soft blocker aliases
    assert normalize_blocker_value("LOW_CONF", "soft") == "LOW_CONFIDENCE"
    assert normalize_blocker_value("MIXED_SIGNALS", "soft") == "CONFLICTING_SIGNALS"
    
    print("✅ PASS: Aliases mapped correctly")


def test_normalize_blocker_case_insensitive():
    """Test that normalization is case-insensitive"""
    print("\n" + "="*60)
    print("TEST 4: Case-insensitive normalization")
    print("="*60)
    
    assert normalize_blocker_value("low_pre_score", "hard") == "LOW_PRE_SCORE"
    assert normalize_blocker_value("Low_Confidence", "soft") == "LOW_CONFIDENCE"
    assert normalize_blocker_value("INSUFFICIENT_MARGIN", "hard") == "INSUFFICIENT_MARGIN"
    
    print("✅ PASS: Case-insensitive normalization works")


def test_normalize_blocker_with_hyphens():
    """Test normalization of blocker values with hyphens"""
    print("\n" + "="*60)
    print("TEST 5: Normalize blockers with hyphens")
    print("="*60)
    
    assert normalize_blocker_value("LOW-PRE-SCORE", "hard") == "LOW_PRE_SCORE"
    assert normalize_blocker_value("CONFLICTING-SIGNALS", "soft") == "CONFLICTING_SIGNALS"
    
    print("✅ PASS: Hyphens replaced with underscores")


def test_normalize_blocker_unknown_values():
    """Test that unknown values are dropped with warning"""
    print("\n" + "="*60)
    print("TEST 6: Unknown values are dropped")
    print("="*60)
    
    # Unknown values should return None
    assert normalize_blocker_value("UNKNOWN_BLOCKER", "hard") is None
    assert normalize_blocker_value("INVALID_REASON", "soft") is None
    assert normalize_blocker_value("RANDOM_TEXT (info)", "hard") is None
    
    print("✅ PASS: Unknown values return None (will be dropped from list)")


def test_normalize_blocker_list():
    """Test normalization of blocker lists"""
    print("\n" + "="*60)
    print("TEST 7: Normalize lists of blockers")
    print("="*60)
    
    # Mixed valid, invalid, and formatted values
    hard_list = [
        "LOW_PRE_SCORE (47)",
        "INSUFFICIENT_MARGIN",
        "UNKNOWN_BLOCKER",
        "LOW_CONFIDENCE_SETUP",
        "MAX_POSITIONS extra info"
    ]
    
    result = normalize_blocker_list(hard_list, "hard")
    
    assert "LOW_PRE_SCORE" in result
    assert "INSUFFICIENT_MARGIN" in result
    assert "MAX_POSITIONS" in result
    assert "UNKNOWN_BLOCKER" not in result
    
    print(f"✅ PASS: List normalized correctly: {result}")


def test_decision_model_with_formatted_blockers():
    """Test that Decision model accepts and normalizes formatted blockers"""
    print("\n" + "="*60)
    print("TEST 8: Decision model with formatted blockers")
    print("="*60)
    
    # Simulate LLM output with formatting variations
    decision_data = {
        'symbol': 'BTCUSDT',
        'action': 'HOLD',
        'leverage': 0,
        'size_pct': 0,
        'confidence': 50,
        'rationale': 'Low pre-score and conflicting signals',
        'blocked_by': [
            'LOW_PRE_SCORE (47)',  # With score in parentheses
            'LOW_RANGE_SCORE extra info'  # With trailing text
        ],
        'soft_blockers': [
            'CONFLICTING_SIGNALS (trend ...)',  # With description
            'LOW_CONFIDENCE'  # Clean value
        ],
        'direction_considered': 'NONE'
    }
    
    try:
        decision = Decision(**decision_data)
        
        # Check that blockers were normalized
        assert 'LOW_PRE_SCORE' in decision.blocked_by
        assert 'LOW_RANGE_SCORE' in decision.blocked_by
        assert 'CONFLICTING_SIGNALS' in decision.soft_blockers
        assert 'LOW_CONFIDENCE' in decision.soft_blockers
        
        print(f"✅ PASS: Decision model normalized blockers correctly")
        print(f"   blocked_by: {decision.blocked_by}")
        print(f"   soft_blockers: {decision.soft_blockers}")
        
    except Exception as e:
        print(f"❌ FAIL: Decision model validation failed: {e}")
        raise


def test_decision_model_with_aliases():
    """Test that Decision model maps aliases correctly"""
    print("\n" + "="*60)
    print("TEST 9: Decision model with aliases")
    print("="*60)
    
    decision_data = {
        'symbol': 'ETHUSDT',
        'action': 'HOLD',
        'leverage': 0,
        'size_pct': 0,
        'confidence': 60,
        'rationale': 'Using aliases for blockers',
        'blocked_by': [
            'LOW_CONFIDENCE_SETUP',  # Maps to LOW_PRE_SCORE
            'INSUFFICIENT_BALANCE'   # Maps to INSUFFICIENT_MARGIN
        ],
        'soft_blockers': [
            'LOW_CONF',              # Maps to LOW_CONFIDENCE
            'MIXED_SIGNALS'          # Maps to CONFLICTING_SIGNALS
        ],
        'direction_considered': 'NONE'
    }
    
    try:
        decision = Decision(**decision_data)
        
        # Check that aliases were mapped
        assert 'LOW_PRE_SCORE' in decision.blocked_by
        assert 'INSUFFICIENT_MARGIN' in decision.blocked_by
        assert 'LOW_CONFIDENCE' in decision.soft_blockers
        assert 'CONFLICTING_SIGNALS' in decision.soft_blockers
        
        print(f"✅ PASS: Aliases mapped correctly")
        print(f"   blocked_by: {decision.blocked_by}")
        print(f"   soft_blockers: {decision.soft_blockers}")
        
    except Exception as e:
        print(f"❌ FAIL: Alias mapping failed: {e}")
        raise


def test_decision_model_drops_unknown():
    """Test that Decision model drops unknown values without failing"""
    print("\n" + "="*60)
    print("TEST 10: Decision model drops unknown values")
    print("="*60)
    
    decision_data = {
        'symbol': 'SOLUSDT',
        'action': 'OPEN_LONG',
        'leverage': 5.0,
        'size_pct': 0.15,
        'confidence': 80,
        'rationale': 'Strong setup with some unknown blockers that should be ignored',
        'blocked_by': [
            'UNKNOWN_BLOCKER_1',     # Should be dropped
            'INVALID_REASON'         # Should be dropped
        ],
        'soft_blockers': [
            'LOW_CONFIDENCE',        # Valid, should be kept
            'RANDOM_TEXT'            # Should be dropped
        ],
        'direction_considered': 'LONG',
        'tp_pct': 0.02,
        'sl_pct': 0.015
    }
    
    try:
        decision = Decision(**decision_data)
        
        # Unknown values should be dropped
        assert len(decision.blocked_by) == 0, "Unknown hard blockers should be dropped"
        assert 'LOW_CONFIDENCE' in decision.soft_blockers
        assert 'RANDOM_TEXT' not in decision.soft_blockers
        assert len(decision.soft_blockers) == 1
        
        print(f"✅ PASS: Unknown values dropped, valid values kept")
        print(f"   blocked_by: {decision.blocked_by} (empty as expected)")
        print(f"   soft_blockers: {decision.soft_blockers}")
        
    except Exception as e:
        print(f"❌ FAIL: Dropping unknown values failed: {e}")
        raise


def test_open_decision_with_valid_soft_blockers():
    """Test that OPEN_LONG decision with soft_blockers is accepted"""
    print("\n" + "="*60)
    print("TEST 11: OPEN decision with soft blockers is accepted")
    print("="*60)
    
    decision_data = {
        'symbol': 'BTCUSDT',
        'action': 'OPEN_LONG',
        'leverage': 5.0,
        'size_pct': 0.15,
        'confidence': 75,
        'rationale': 'Strong setup with 4 confirmations, opening despite low confidence flag',
        'setup_confirmations': ['RSI oversold', 'Support bounce', 'Volume spike', 'Bullish momentum'],
        'blocked_by': [],  # No hard blockers
        'soft_blockers': ['LOW_CONFIDENCE (75% is borderline)'],  # Soft warning with description
        'direction_considered': 'LONG',
        'tp_pct': 0.02,
        'sl_pct': 0.015,
        'time_in_trade_limit_sec': 3600,
        'entry_type': 'MARKET'
    }
    
    try:
        decision = Decision(**decision_data)
        
        # Should accept OPEN_LONG with soft blockers
        assert decision.action == 'OPEN_LONG'
        assert len(decision.blocked_by) == 0
        assert 'LOW_CONFIDENCE' in decision.soft_blockers
        
        print(f"✅ PASS: OPEN_LONG with soft blockers accepted")
        print(f"   action: {decision.action}")
        print(f"   blocked_by: {decision.blocked_by}")
        print(f"   soft_blockers: {decision.soft_blockers}")
        
    except Exception as e:
        print(f"❌ FAIL: OPEN decision with soft blockers rejected: {e}")
        raise


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*80)
    print(" DECISION PARSING ROBUSTNESS TEST SUITE")
    print("="*80)
    
    tests = [
        test_normalize_blocker_with_parenthesis,
        test_normalize_blocker_with_spaces,
        test_normalize_blocker_aliases,
        test_normalize_blocker_case_insensitive,
        test_normalize_blocker_with_hyphens,
        test_normalize_blocker_unknown_values,
        test_normalize_blocker_list,
        test_decision_model_with_formatted_blockers,
        test_decision_model_with_aliases,
        test_decision_model_drops_unknown,
        test_open_decision_with_valid_soft_blockers,
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
