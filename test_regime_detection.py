#!/usr/bin/env python3
"""
Tests for Market Regime Detection Module

Tests regime classification, hysteresis behavior, and volatility bucketing.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator'))

from regime import (
    detect_regime_with_hysteresis,
    calculate_volatility_bucket,
    clear_regime_cache,
    get_regime_summary
)
import time


def test_volatility_bucket():
    """Test volatility bucket calculation."""
    print("\n" + "="*80)
    print("TEST: Volatility Bucket Calculation")
    print("="*80)
    
    test_cases = [
        (4, 1000, "LOW"),       # 0.4% ATR
        (10, 1000, "MEDIUM"),   # 1.0% ATR
        (20, 1000, "HIGH"),     # 2.0% ATR
        (35, 1000, "EXTREME"),  # 3.5% ATR
    ]
    
    for atr, price, expected in test_cases:
        result = calculate_volatility_bucket(atr, price)
        atr_pct = (atr / price) * 100
        status = "✓" if result == expected else "✗"
        print(f"{status} ATR {atr} / Price {price} = {atr_pct:.2f}% → {result} (expected {expected})")
        assert result == expected, f"Expected {expected}, got {result}"
    
    print("✓ All volatility bucket tests passed")


def test_regime_detection_basic():
    """Test basic regime detection without hysteresis."""
    print("\n" + "="*80)
    print("TEST: Basic Regime Detection")
    print("="*80)
    
    clear_regime_cache()
    
    # Test TREND regime (high ADX)
    regime, metadata = detect_regime_with_hysteresis(
        symbol="BTCUSDT",
        adx=30.0,
        atr=250.0,
        price=50000.0,
        trend="bullish"
    )
    print(f"✓ ADX=30 → Regime: {regime} (expected TREND)")
    assert regime == "TREND", f"Expected TREND, got {regime}"
    assert metadata["confidence"] > 50, "Confidence should be >50 for clear trend"
    
    # Test RANGE regime (low ADX)
    clear_regime_cache()
    regime, metadata = detect_regime_with_hysteresis(
        symbol="ETHUSDT",
        adx=15.0,
        atr=30.0,
        price=3000.0,
        trend="neutral"
    )
    print(f"✓ ADX=15 → Regime: {regime} (expected RANGE)")
    assert regime == "RANGE", f"Expected RANGE, got {regime}"
    
    # Test TRANSITION regime (medium ADX)
    clear_regime_cache()
    regime, metadata = detect_regime_with_hysteresis(
        symbol="SOLUSDT",
        adx=22.0,
        atr=2.0,
        price=100.0,
        trend="bullish"
    )
    print(f"✓ ADX=22 → Regime: {regime} (expected TRANSITION)")
    assert regime == "TRANSITION", f"Expected TRANSITION, got {regime}"
    assert metadata["confidence"] == 50, "TRANSITION should have 50% confidence"
    
    print("✓ All basic regime detection tests passed")


def test_regime_hysteresis():
    """Test regime detection with hysteresis (prevents flapping)."""
    print("\n" + "="*80)
    print("TEST: Regime Hysteresis (Anti-Flapping)")
    print("="*80)
    
    clear_regime_cache()
    symbol = "BTCUSDT"
    
    # Initial detection: TREND
    regime1, meta1 = detect_regime_with_hysteresis(
        symbol=symbol,
        adx=30.0,
        atr=250.0,
        price=50000.0,
        trend="bullish"
    )
    print(f"✓ Initial: ADX=30 → {regime1}")
    assert regime1 == "TREND"
    assert not meta1.get("from_cache"), "First call should not be from cache"
    
    # Immediate check with different ADX (should use cache due to hysteresis)
    time.sleep(0.1)  # Small delay
    regime2, meta2 = detect_regime_with_hysteresis(
        symbol=symbol,
        adx=18.0,  # Would normally be RANGE
        atr=250.0,
        price=50000.0,
        trend="neutral"
    )
    print(f"✓ Immediate: ADX=18 → {regime2} (should stay TREND due to hysteresis)")
    assert regime2 == "TREND", "Hysteresis should prevent immediate regime change"
    assert meta2.get("from_cache"), "Should use cache within hysteresis period"
    assert "blocked_switch" in meta2, "Should indicate blocked switch"
    
    # Force recalculation
    regime3, meta3 = detect_regime_with_hysteresis(
        symbol=symbol,
        adx=18.0,
        atr=250.0,
        price=50000.0,
        trend="neutral",
        force_recalc=True
    )
    print(f"✓ Forced: ADX=18 → {regime3} (force_recalc=True)")
    assert regime3 == "RANGE", "Force recalc should override hysteresis"
    assert not meta3.get("from_cache"), "Force recalc should bypass cache"
    
    print("✓ All hysteresis tests passed")


def test_regime_with_ema_context():
    """Test regime detection with EMA context."""
    print("\n" + "="*80)
    print("TEST: Regime Detection with EMA Context")
    print("="*80)
    
    clear_regime_cache()
    
    regime, metadata = detect_regime_with_hysteresis(
        symbol="BTCUSDT",
        adx=28.0,
        atr=250.0,
        price=51000.0,
        trend="bullish",
        ema_20=50500.0,
        ema_50=49000.0
    )
    
    print(f"✓ Regime: {regime}")
    print(f"  EMA Alignment: {metadata.get('ema_alignment')}")
    print(f"  Price vs EMA20: {metadata.get('price_vs_ema20')}")
    
    assert metadata.get("ema_alignment") == "bullish", "EMA20 > EMA50 should be bullish"
    assert metadata.get("price_vs_ema20") == "above", "Price > EMA20 should be above"
    
    print("✓ EMA context test passed")


def test_regime_summary():
    """Test regime cache summary."""
    print("\n" + "="*80)
    print("TEST: Regime Cache Summary")
    print("="*80)
    
    clear_regime_cache()
    
    # Add a few regimes to cache
    for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        detect_regime_with_hysteresis(
            symbol=symbol,
            adx=25.0,
            atr=100.0,
            price=50000.0
        )
    
    summary = get_regime_summary()
    print(f"✓ Cached regimes: {summary['total_cached']}")
    print(f"  Symbols: {[s['symbol'] for s in summary['symbols']]}")
    
    assert summary["total_cached"] == 3, "Should have 3 cached regimes"
    assert len(summary["symbols"]) == 3, "Should list 3 symbols"
    
    print("✓ Regime summary test passed")


def run_all_tests():
    """Run all regime detection tests."""
    print("\n" + "="*80)
    print("REGIME DETECTION MODULE - TEST SUITE")
    print("="*80)
    
    test_volatility_bucket()
    test_regime_detection_basic()
    test_regime_hysteresis()
    test_regime_with_ema_context()
    test_regime_summary()
    
    print("\n" + "="*80)
    print("✓ ALL REGIME DETECTION TESTS PASSED")
    print("="*80)


if __name__ == "__main__":
    run_all_tests()
