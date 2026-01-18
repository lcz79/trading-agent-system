#!/usr/bin/env python3
"""
Integration Test for Advanced Preprocessing and Safety Gates

Tests the complete workflow:
1. Preprocessing computes regime, volatility, confluence
2. Verification applies BLOCK/DEGRADE gates
3. End-to-end decision flow with enhanced fields
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator'))

from regime import detect_regime_with_hysteresis, calculate_volatility_bucket
from confluence import calculate_confluence_score, get_confluence_summary
from correlation import calculate_portfolio_correlation_risk
from verification import verify_decision


def test_preprocessing_integration():
    """Test complete preprocessing pipeline."""
    print("\n" + "="*80)
    print("TEST: Preprocessing Integration")
    print("="*80)
    
    # Simulate tech data from technical analyzer
    tech_data = {
        "timeframes": {
            "15m": {
                "price": 50000.0,
                "trend": "bullish",
                "rsi": 55,
                "adx": 28.0,
                "atr": 250.0,
                "return_15m": 0.5,
                "ema_20": 49800.0,
                "ema_50": 49000.0
            },
            "1h": {
                "trend": "bullish",
                "return_1h": 0.8,
                "rsi": 62
            },
            "4h": {
                "trend": "bullish",
                "return_4h": 1.2,
                "rsi": 65
            },
            "1d": {
                "trend": "bullish",
                "return_1d": 2.0,
                "rsi": 70
            }
        }
    }
    
    symbol = "BTCUSDT"
    tf_15m = tech_data["timeframes"]["15m"]
    
    # Step 1: Compute regime
    regime, regime_meta = detect_regime_with_hysteresis(
        symbol=symbol,
        adx=tf_15m["adx"],
        atr=tf_15m["atr"],
        price=tf_15m["price"],
        trend=tf_15m["trend"],
        ema_20=tf_15m["ema_20"],
        ema_50=tf_15m["ema_50"]
    )
    
    print(f"\n✓ Regime Detection:")
    print(f"  Regime: {regime}")
    print(f"  Confidence: {regime_meta['confidence']}%")
    print(f"  Volatility bucket: {regime_meta['volatility_bucket']}")
    
    assert regime == "TREND", f"Expected TREND regime, got {regime}"
    
    # Step 2: Compute volatility bucket
    volatility_bucket = calculate_volatility_bucket(tf_15m["atr"], tf_15m["price"])
    print(f"  Volatility: {volatility_bucket}")
    
    # Step 3: Compute confluence
    long_confluence, long_breakdown = calculate_confluence_score("LONG", tech_data["timeframes"])
    short_confluence, short_breakdown = calculate_confluence_score("SHORT", tech_data["timeframes"])
    
    print(f"\n✓ Confluence Scoring:")
    print(f"  LONG: {long_confluence}/100")
    print(f"  SHORT: {short_confluence}/100")
    
    assert long_confluence >= 90, f"Perfect bullish alignment should score >=90, got {long_confluence}"
    assert short_confluence <= 20, f"Perfect bullish for SHORT should score <=20, got {short_confluence}"
    
    # Step 4: Correlation risk (placeholder)
    corr_risk_long, corr_breakdown = calculate_portfolio_correlation_risk([], symbol, "long")
    print(f"\n✓ Correlation Risk:")
    print(f"  Risk score: {corr_risk_long}")
    print(f"  Status: {corr_breakdown['status']}")
    
    assert corr_risk_long == 0.0, "Placeholder should return 0.0"
    
    print("\n✓ Preprocessing integration test passed")


def test_verification_integration():
    """Test verification gates with enhanced data."""
    print("\n" + "="*80)
    print("TEST: Verification Integration")
    print("="*80)
    
    tech_data = {
        "timeframes": {
            "15m": {
                "price": 50000.0,
                "trend": "bullish",
                "adx": 28.0,
                "atr": 250.0
            },
            "1h": {
                "trend": "bullish",
                "return_1h": 0.8
            }
        }
    }
    
    # Test Case 1: High confluence - should ALLOW
    print("\n--- Test Case 1: High Confluence (ALLOW) ---")
    decision_allow = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "entry_type": "MARKET",
        "tp_pct": 0.02,
        "sl_pct": 0.015
    }
    
    enhanced_data_allow = {
        "confluence_score": 85,
        "volatility_bucket": "MEDIUM",
        "regime": "TREND"
    }
    
    result = verify_decision(decision_allow, tech_data, enhanced_data_allow)
    print(f"  Result: {result.action}")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reasons: {result.reasons}")
    
    assert result.action == "ALLOW", f"High confluence should ALLOW, got {result.action}"
    assert result.allowed is True
    
    # Test Case 2: Low confluence - should BLOCK
    print("\n--- Test Case 2: Low Confluence (BLOCK) ---")
    enhanced_data_block = {
        "confluence_score": 30,
        "volatility_bucket": "MEDIUM",
        "regime": "TREND"
    }
    
    result = verify_decision(decision_allow, tech_data, enhanced_data_block)
    print(f"  Result: {result.action}")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reasons: {result.reasons}")
    
    assert result.action == "BLOCK", f"Low confluence should BLOCK, got {result.action}"
    assert result.allowed is False
    assert "Confluence too low" in str(result.reasons)
    
    # Test Case 3: Medium confluence + HIGH vol - should DEGRADE
    print("\n--- Test Case 3: Medium Confluence + HIGH Vol (DEGRADE) ---")
    enhanced_data_degrade = {
        "confluence_score": 50,
        "volatility_bucket": "HIGH",
        "regime": "TREND"
    }
    
    result = verify_decision(decision_allow, tech_data, enhanced_data_degrade)
    print(f"  Result: {result.action}")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reasons: {result.reasons}")
    print(f"  Modified size: {result.modified_params.get('size_pct', 0.15):.3f}")
    
    assert result.action == "DEGRADE", f"Medium conf + HIGH vol should DEGRADE, got {result.action}"
    assert result.allowed is True
    assert result.modified_params.get("size_pct", 0.15) < 0.15, "Size should be reduced"
    
    # Test Case 4: Invalid LIMIT params - should BLOCK
    print("\n--- Test Case 4: Invalid LIMIT Entry (BLOCK) ---")
    decision_invalid_limit = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "entry_type": "LIMIT",
        "entry_price": None,  # Missing!
        "entry_ttl_sec": 180
    }
    
    enhanced_data_valid = {
        "confluence_score": 80,
        "volatility_bucket": "MEDIUM",
        "regime": "TREND"
    }
    
    result = verify_decision(decision_invalid_limit, tech_data, enhanced_data_valid)
    print(f"  Result: {result.action}")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reasons: {result.reasons}")
    
    assert result.action == "BLOCK", "Invalid LIMIT should BLOCK"
    assert "entry_price" in str(result.reasons)
    
    print("\n✓ Verification integration tests passed")


def test_end_to_end_workflow():
    """Test complete end-to-end workflow."""
    print("\n" + "="*80)
    print("TEST: End-to-End Workflow")
    print("="*80)
    
    # Simulate complete workflow for a trading decision
    symbol = "ETHUSDT"
    
    # 1. Tech data (from analyzer)
    tech_data = {
        "timeframes": {
            "15m": {
                "price": 3500.0,
                "trend": "bullish",
                "rsi": 58,
                "adx": 26.0,
                "atr": 35.0,
                "return_15m": 0.4,
                "ema_20": 3480.0,
                "ema_50": 3450.0
            },
            "1h": {
                "trend": "neutral",
                "return_1h": 0.1,
                "rsi": 52
            },
            "4h": {
                "trend": "bullish",
                "return_4h": 0.6,
                "rsi": 60
            },
            "1d": {
                "trend": "neutral",
                "return_1d": 0.2,
                "rsi": 55
            }
        }
    }
    
    tf_15m = tech_data["timeframes"]["15m"]
    
    # 2. Preprocessing
    print("\n--- Phase 1: Preprocessing ---")
    regime, regime_meta = detect_regime_with_hysteresis(
        symbol=symbol,
        adx=tf_15m["adx"],
        atr=tf_15m["atr"],
        price=tf_15m["price"],
        trend=tf_15m["trend"]
    )
    
    volatility_bucket = calculate_volatility_bucket(tf_15m["atr"], tf_15m["price"])
    
    long_confluence, _ = calculate_confluence_score("LONG", tech_data["timeframes"])
    short_confluence, _ = calculate_confluence_score("SHORT", tech_data["timeframes"])
    
    print(f"  Regime: {regime}")
    print(f"  Volatility: {volatility_bucket}")
    print(f"  Confluence LONG: {long_confluence}/100")
    print(f"  Confluence SHORT: {short_confluence}/100")
    
    # 3. AI Decision (simulated)
    print("\n--- Phase 2: AI Decision (Simulated) ---")
    ai_decision = {
        "symbol": symbol,
        "action": "OPEN_LONG",
        "leverage": 5.0,
        "size_pct": 0.15,
        "entry_type": "MARKET",
        "tp_pct": 0.02,
        "sl_pct": 0.015,
        "confidence": 75
    }
    print(f"  AI wants to: {ai_decision['action']}")
    print(f"  Size: {ai_decision['size_pct']:.3f}")
    print(f"  Leverage: {ai_decision['leverage']:.1f}x")
    
    # 4. Verification
    print("\n--- Phase 3: Verification Safety Gates ---")
    enhanced_data = {
        "confluence_score": long_confluence,
        "volatility_bucket": volatility_bucket,
        "regime": regime
    }
    
    result = verify_decision(ai_decision, tech_data, enhanced_data)
    print(f"  Gate decision: {result.action}")
    print(f"  Allowed: {result.allowed}")
    
    if result.action == "DEGRADE":
        print(f"  Reasons:")
        for reason in result.reasons:
            print(f"    - {reason}")
        print(f"  Modified size: {result.modified_params.get('size_pct', ai_decision['size_pct']):.3f}")
        final_size = result.modified_params.get('size_pct', ai_decision['size_pct'])
    elif result.action == "BLOCK":
        print(f"  BLOCKED. Reasons:")
        for reason in result.reasons:
            print(f"    - {reason}")
        final_size = 0.0
    else:  # ALLOW
        print(f"  ✅ All safety checks passed")
        final_size = ai_decision['size_pct']
    
    # 5. Execution (simulated)
    print("\n--- Phase 4: Execution ---")
    if result.allowed:
        print(f"  ✅ Would execute: {ai_decision['action']} on {symbol}")
        print(f"     Final size: {final_size:.3f}")
        print(f"     Leverage: {result.modified_params.get('leverage', ai_decision['leverage']):.1f}x")
    else:
        print(f"  🚫 Trade blocked, no execution")
    
    # Assertions
    assert regime in ["TREND", "RANGE", "TRANSITION"], f"Invalid regime: {regime}"
    assert volatility_bucket in ["LOW", "MEDIUM", "HIGH", "EXTREME"], f"Invalid volatility: {volatility_bucket}"
    assert 0 <= long_confluence <= 100, f"Invalid confluence: {long_confluence}"
    assert result.action in ["ALLOW", "DEGRADE", "BLOCK"], f"Invalid gate action: {result.action}"
    
    print("\n✓ End-to-end workflow test passed")


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*80)
    print("PREPROCESSING & SAFETY GATES - INTEGRATION TEST SUITE")
    print("="*80)
    
    test_preprocessing_integration()
    test_verification_integration()
    test_end_to_end_workflow()
    
    print("\n" + "="*80)
    print("✓ ALL INTEGRATION TESTS PASSED")
    print("="*80)
    print("\nSummary:")
    print("  ✅ Preprocessing pipeline works correctly")
    print("  ✅ Verification gates (BLOCK/DEGRADE/ALLOW) work correctly")
    print("  ✅ End-to-end workflow integrates all components")
    print("  ✅ Ready for deployment")


if __name__ == "__main__":
    run_all_tests()
