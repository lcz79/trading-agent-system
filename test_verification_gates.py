#!/usr/bin/env python3
"""
Tests for Verification and Safety Gates Module

Tests HARD BLOCK and SOFT DEGRADE logic for trading decisions.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator'))

from verification import (
    verify_confluence,
    verify_limit_entry_params,
    verify_risk_params,
    verify_timeframe_opposition,
    apply_degrade_logic,
    verify_decision
)


def test_confluence_verification():
    """Test confluence threshold verification."""
    print("\n" + "="*80)
    print("TEST: Confluence Verification")
    print("="*80)
    
    # Should pass
    passes, reason = verify_confluence("LONG", 60)
    print(f"✓ Confluence 60: {passes} (expected True)")
    assert passes is True, "Confluence >= 40 should pass"
    
    # Should block
    passes, reason = verify_confluence("LONG", 35)
    print(f"✓ Confluence 35: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "Confluence < 40 should block"
    assert reason is not None, "Should provide block reason"
    
    # Edge case
    passes, _ = verify_confluence("SHORT", 40)
    print(f"✓ Confluence 40 (edge): {passes} (expected True)")
    assert passes is True, "Confluence = 40 should pass (inclusive)"
    
    print("✓ Confluence verification tests passed")


def test_limit_entry_verification():
    """Test LIMIT entry parameter verification."""
    print("\n" + "="*80)
    print("TEST: LIMIT Entry Parameter Verification")
    print("="*80)
    
    # MARKET entry - should pass
    passes, reason = verify_limit_entry_params("MARKET", None, None, 50000)
    print(f"✓ MARKET entry: {passes} (expected True)")
    assert passes is True, "MARKET entry should always pass"
    
    # Valid LIMIT entry
    passes, reason = verify_limit_entry_params("LIMIT", 50000, 180, 50100)
    print(f"✓ Valid LIMIT entry: {passes} (expected True)")
    assert passes is True, "Valid LIMIT should pass"
    
    # Missing entry_price
    passes, reason = verify_limit_entry_params("LIMIT", None, 180, 50000)
    print(f"✓ LIMIT without price: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "LIMIT without entry_price should block"
    
    # TTL too short
    passes, reason = verify_limit_entry_params("LIMIT", 50000, 30, 50100)
    print(f"✓ LIMIT with TTL=30s: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "TTL < 60s should block"
    
    # TTL too long
    passes, reason = verify_limit_entry_params("LIMIT", 50000, 1000, 50100)
    print(f"✓ LIMIT with TTL=1000s: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "TTL > 600s should block"
    
    # Entry price too far from market
    passes, reason = verify_limit_entry_params("LIMIT", 51500, 180, 50000)
    print(f"✓ LIMIT price 3% from market: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "Entry price >2% from market should block"
    
    print("✓ LIMIT entry verification tests passed")


def test_risk_params_verification():
    """Test risk parameter bounds verification."""
    print("\n" + "="*80)
    print("TEST: Risk Parameter Verification")
    print("="*80)
    
    # Valid params
    passes, reason = verify_risk_params(5.0, 0.15, 0.02, 0.015)
    print(f"✓ Valid params (lev=5, size=0.15): {passes} (expected True)")
    assert passes is True, "Valid params should pass"
    
    # Leverage too high
    passes, reason = verify_risk_params(25.0, 0.15, 0.02, 0.015)
    print(f"✓ Leverage=25: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "Leverage > 20 should block"
    
    # Size too large
    passes, reason = verify_risk_params(5.0, 0.35, 0.02, 0.015)
    print(f"✓ Size=0.35: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "Size > 0.30 should block"
    
    # TP too tight
    passes, reason = verify_risk_params(5.0, 0.15, 0.002, 0.015)
    print(f"✓ TP=0.002: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "TP < 0.005 should block"
    
    # SL too wide
    passes, reason = verify_risk_params(5.0, 0.15, 0.02, 0.08)
    print(f"✓ SL=0.08: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "SL > 0.05 should block"
    
    print("✓ Risk parameter verification tests passed")


def test_timeframe_opposition():
    """Test 1h opposition detection."""
    print("\n" + "="*80)
    print("TEST: Timeframe Opposition Detection")
    print("="*80)
    
    # No opposition for LONG
    timeframes = {
        "1h": {"trend": "bullish", "return_1h": 0.8}
    }
    passes, reason = verify_timeframe_opposition("LONG", timeframes)
    print(f"✓ LONG with bullish 1h: {passes} (expected True)")
    assert passes is True, "Aligned 1h should pass"
    
    # Strong opposition for LONG (bearish 1h)
    timeframes = {
        "1h": {"trend": "bearish", "return_1h": -0.8}
    }
    passes, reason = verify_timeframe_opposition("LONG", timeframes)
    print(f"✓ LONG with strong bearish 1h: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "Strong 1h opposition should block LONG"
    
    # Strong opposition for SHORT (bullish 1h)
    timeframes = {
        "1h": {"trend": "bullish", "return_1h": 0.9}
    }
    passes, reason = verify_timeframe_opposition("SHORT", timeframes)
    print(f"✓ SHORT with strong bullish 1h: {passes} (expected False)")
    print(f"  Reason: {reason}")
    assert passes is False, "Strong 1h opposition should block SHORT"
    
    # Weak opposition (should pass)
    timeframes = {
        "1h": {"trend": "bearish", "return_1h": -0.3}
    }
    passes, reason = verify_timeframe_opposition("LONG", timeframes)
    print(f"✓ LONG with weak bearish 1h: {passes} (expected True)")
    assert passes is True, "Weak opposition should not block"
    
    print("✓ Timeframe opposition tests passed")


def test_degrade_logic():
    """Test soft degrade parameter modifications."""
    print("\n" + "="*80)
    print("TEST: Soft Degrade Logic")
    print("="*80)
    
    decision = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "entry_type": "MARKET",
        "entry_ttl_sec": 180
    }
    
    # Degrade 1: Medium confluence
    modified, reasons = apply_degrade_logic(
        decision, 
        confluence_score=50,
        volatility_bucket="MEDIUM",
        regime="TREND",
        timeframes={}
    )
    print(f"✓ Medium confluence degrade:")
    print(f"  Original size: {decision['size_pct']:.3f}")
    print(f"  Modified size: {modified['size_pct']:.3f}")
    print(f"  Reasons: {reasons}")
    assert modified["size_pct"] < decision["size_pct"], "Size should be reduced"
    assert len(reasons) > 0, "Should provide degrade reasons"
    
    # Degrade 2: High volatility
    modified, reasons = apply_degrade_logic(
        decision,
        confluence_score=70,
        volatility_bucket="HIGH",
        regime="TREND",
        timeframes={}
    )
    print(f"✓ High volatility degrade:")
    print(f"  Modified size: {modified['size_pct']:.3f}")
    print(f"  Reasons: {reasons}")
    assert modified["size_pct"] < decision["size_pct"], "Size should be reduced for HIGH volatility"
    
    # Degrade 3: RANGE regime with MARKET entry
    modified, reasons = apply_degrade_logic(
        decision,
        confluence_score=70,
        volatility_bucket="MEDIUM",
        regime="RANGE",
        timeframes={}
    )
    print(f"✓ RANGE regime degrade:")
    print(f"  Reasons: {reasons}")
    assert any("LIMIT" in r for r in reasons), "Should suggest LIMIT in RANGE"
    
    # Degrade 4: Extreme volatility (reduce leverage)
    modified, reasons = apply_degrade_logic(
        decision,
        confluence_score=70,
        volatility_bucket="EXTREME",
        regime="TREND",
        timeframes={}
    )
    print(f"✓ Extreme volatility degrade:")
    print(f"  Original leverage: {decision['leverage']:.1f}x")
    print(f"  Modified leverage: {modified['leverage']:.1f}x")
    assert modified["leverage"] < decision["leverage"], "Leverage should be reduced for EXTREME volatility"
    
    print("✓ Degrade logic tests passed")


def test_full_verification_block():
    """Test full verification with BLOCK outcome."""
    print("\n" + "="*80)
    print("TEST: Full Verification - BLOCK Outcome")
    print("="*80)
    
    decision = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "entry_type": "MARKET"
    }
    
    tech_data = {
        "timeframes": {
            "15m": {"price": 50000, "trend": "bullish"},
            "1h": {"trend": "bullish", "return_1h": 0.5}
        }
    }
    
    enhanced_data = {
        "confluence_score": 30,  # Too low - should BLOCK
        "volatility_bucket": "MEDIUM",
        "regime": "TREND"
    }
    
    result = verify_decision(decision, tech_data, enhanced_data)
    print(f"✓ Verification result: {result.action}")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reasons: {result.reasons}")
    
    assert result.action == "BLOCK", "Low confluence should BLOCK"
    assert not result.allowed, "BLOCK should not allow execution"
    assert len(result.reasons) > 0, "Should provide block reasons"
    
    print("✓ BLOCK outcome test passed")


def test_full_verification_degrade():
    """Test full verification with DEGRADE outcome."""
    print("\n" + "="*80)
    print("TEST: Full Verification - DEGRADE Outcome")
    print("="*80)
    
    decision = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "entry_type": "MARKET"
    }
    
    tech_data = {
        "timeframes": {
            "15m": {"price": 50000, "trend": "bullish"},
            "1h": {"trend": "bullish", "return_1h": 0.5}
        }
    }
    
    enhanced_data = {
        "confluence_score": 50,  # Medium - should DEGRADE
        "volatility_bucket": "HIGH",
        "regime": "TREND"
    }
    
    result = verify_decision(decision, tech_data, enhanced_data)
    print(f"✓ Verification result: {result.action}")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reasons: {result.reasons}")
    print(f"  Modified params: {result.modified_params}")
    
    assert result.action == "DEGRADE", "Medium confluence + HIGH vol should DEGRADE"
    assert result.allowed, "DEGRADE should allow execution with modifications"
    assert len(result.modified_params) > 0, "Should provide modified parameters"
    assert result.modified_params.get("size_pct", 0.15) < 0.15, "Size should be reduced"
    
    print("✓ DEGRADE outcome test passed")


def test_full_verification_allow():
    """Test full verification with ALLOW outcome."""
    print("\n" + "="*80)
    print("TEST: Full Verification - ALLOW Outcome")
    print("="*80)
    
    decision = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "entry_type": "MARKET",
        "tp_pct": 0.02,
        "sl_pct": 0.015
    }
    
    tech_data = {
        "timeframes": {
            "15m": {"price": 50000, "trend": "bullish"},
            "1h": {"trend": "bullish", "return_1h": 0.8}
        }
    }
    
    enhanced_data = {
        "confluence_score": 80,  # High - should ALLOW
        "volatility_bucket": "MEDIUM",
        "regime": "TREND"
    }
    
    result = verify_decision(decision, tech_data, enhanced_data)
    print(f"✓ Verification result: {result.action}")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reasons: {result.reasons}")
    
    assert result.action == "ALLOW", "High confluence with valid params should ALLOW"
    assert result.allowed, "ALLOW should permit execution"
    
    print("✓ ALLOW outcome test passed")


def run_all_tests():
    """Run all verification tests."""
    print("\n" + "="*80)
    print("VERIFICATION MODULE - TEST SUITE")
    print("="*80)
    
    test_confluence_verification()
    test_limit_entry_verification()
    test_risk_params_verification()
    test_timeframe_opposition()
    test_degrade_logic()
    test_full_verification_block()
    test_full_verification_degrade()
    test_full_verification_allow()
    
    print("\n" + "="*80)
    print("✓ ALL VERIFICATION TESTS PASSED")
    print("="*80)


if __name__ == "__main__":
    run_all_tests()
