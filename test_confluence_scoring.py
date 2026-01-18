#!/usr/bin/env python3
"""
Tests for Confluence Scoring Module

Tests timeframe alignment scoring, conflict penalties, and recommendations.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', 'orchestrator'))

from confluence import (
    calculate_confluence_score,
    calculate_tf_aligned,
    get_confluence_summary
)


def test_perfect_alignment():
    """Test confluence with perfect timeframe alignment."""
    print("\n" + "="*80)
    print("TEST: Perfect Timeframe Alignment")
    print("="*80)
    
    # All timeframes bullish for LONG
    timeframes = {
        "15m": {"trend": "bullish", "return_15m": 0.5},
        "1h": {"trend": "bullish", "return_1h": 0.8},
        "4h": {"trend": "bullish", "return_4h": 1.2},
        "1d": {"trend": "bullish", "return_1d": 2.0}
    }
    
    score, breakdown = calculate_confluence_score("LONG", timeframes)
    print(f"✓ LONG score with perfect alignment: {score}")
    print(f"  Total before penalties: {breakdown['total_before_penalties']}")
    print(f"  Penalties: {breakdown['penalties']}")
    
    assert score >= 90, f"Perfect alignment should score >=90, got {score}"
    assert len(breakdown["penalties"]) == 0, "No penalties expected for perfect alignment"
    
    print("✓ Perfect alignment test passed")


def test_conflicting_signals():
    """Test confluence with conflicting timeframe signals."""
    print("\n" + "="*80)
    print("TEST: Conflicting Timeframe Signals")
    print("="*80)
    
    # 15m bullish but 1h/4h bearish (conflict)
    timeframes = {
        "15m": {"trend": "bullish", "return_15m": 0.3},
        "1h": {"trend": "bearish", "return_1h": -0.6},
        "4h": {"trend": "bearish", "return_4h": -1.0},
        "1d": {"trend": "neutral", "return_1d": 0.1}
    }
    
    score, breakdown = calculate_confluence_score("LONG", timeframes)
    print(f"✓ LONG score with conflicts: {score}")
    print(f"  Total before penalties: {breakdown['total_before_penalties']}")
    print(f"  Penalties applied: {len(breakdown['penalties'])}")
    for penalty in breakdown['penalties']:
        print(f"    - {penalty['type']}: -{penalty['penalty']} ({penalty['reason']})")
    
    assert score < 50, f"Conflicting signals should score <50, got {score}"
    assert len(breakdown["penalties"]) > 0, "Penalties expected for major TF opposition"
    
    print("✓ Conflicting signals test passed")


def test_medium_confluence():
    """Test confluence with medium alignment (some agreement)."""
    print("\n" + "="*80)
    print("TEST: Medium Confluence")
    print("="*80)
    
    # Mixed signals - some alignment
    timeframes = {
        "15m": {"trend": "bullish", "return_15m": 0.4},
        "1h": {"trend": "neutral", "return_1h": 0.1},
        "4h": {"trend": "bullish", "return_4h": 0.3},
        "1d": {"trend": "neutral", "return_1d": -0.05}
    }
    
    score, breakdown = calculate_confluence_score("LONG", timeframes)
    print(f"✓ LONG score with medium confluence: {score}")
    print(f"  Weighted scores:")
    for tf, data in breakdown["weighted_scores"].items():
        print(f"    {tf}: {data['weighted_score']:.1f} (weight={data['weight']})")
    
    assert 60 <= score <= 85, f"Medium confluence should score 60-85, got {score}"
    
    print("✓ Medium confluence test passed")


def test_short_direction():
    """Test confluence scoring for SHORT direction."""
    print("\n" + "="*80)
    print("TEST: SHORT Direction Confluence")
    print("="*80)
    
    # All timeframes bearish for SHORT
    timeframes = {
        "15m": {"trend": "bearish", "return_15m": -0.5},
        "1h": {"trend": "bearish", "return_1h": -0.8},
        "4h": {"trend": "bearish", "return_4h": -1.2},
        "1d": {"trend": "bearish", "return_1d": -2.0}
    }
    
    score, breakdown = calculate_confluence_score("SHORT", timeframes)
    print(f"✓ SHORT score with perfect alignment: {score}")
    
    assert score >= 90, f"Perfect SHORT alignment should score >=90, got {score}"
    
    # Test opposite direction (should score low)
    score_long, _ = calculate_confluence_score("LONG", timeframes)
    print(f"✓ LONG score with bearish timeframes: {score_long}")
    
    assert score_long < 20, f"Opposite direction should score <20, got {score_long}"
    
    print("✓ SHORT direction test passed")


def test_tf_aligned_boolean():
    """Test simple boolean TF alignment."""
    print("\n" + "="*80)
    print("TEST: Boolean TF Alignment")
    print("="*80)
    
    # Aligned timeframes
    timeframes_aligned = {
        "15m": {"trend": "bullish"},
        "1h": {"trend": "bullish"},
        "4h": {"trend": "bullish"}
    }
    
    result = calculate_tf_aligned(timeframes_aligned)
    print(f"✓ Aligned timeframes: {result} (expected True)")
    assert result is True, "Aligned timeframes should return True"
    
    # Conflicting timeframes
    timeframes_conflict = {
        "15m": {"trend": "bullish"},
        "1h": {"trend": "bearish"},
        "4h": {"trend": "bullish"}
    }
    
    result = calculate_tf_aligned(timeframes_conflict)
    print(f"✓ Conflicting timeframes: {result} (expected False)")
    assert result is False, "Conflicting timeframes should return False"
    
    print("✓ Boolean alignment test passed")


def test_confluence_summary():
    """Test confluence summary with recommendations."""
    print("\n" + "="*80)
    print("TEST: Confluence Summary with Recommendations")
    print("="*80)
    
    # Strong bullish setup
    timeframes = {
        "15m": {"trend": "bullish", "return_15m": 0.6},
        "1h": {"trend": "bullish", "return_1h": 0.9},
        "4h": {"trend": "bullish", "return_4h": 1.5},
        "1d": {"trend": "bullish", "return_1d": 3.0}
    }
    
    summary = get_confluence_summary(timeframes)
    print(f"✓ Summary:")
    print(f"  LONG score: {summary['long_score']}")
    print(f"  SHORT score: {summary['short_score']}")
    print(f"  Recommendation: {summary['recommendation']}")
    print(f"  Confidence: {summary['confidence']}")
    print(f"  TF Aligned: {summary['tf_aligned']}")
    
    assert summary["recommendation"] == "LONG", "Strong bullish should recommend LONG"
    assert summary["confidence"] in ["HIGH", "MEDIUM"], "Strong setup should have HIGH/MEDIUM confidence"
    assert summary["long_score"] > summary["short_score"], "LONG score should exceed SHORT score"
    
    print("✓ Confluence summary test passed")


def test_neutral_timeframes():
    """Test confluence with neutral/sideways timeframes."""
    print("\n" + "="*80)
    print("TEST: Neutral Timeframes")
    print("="*80)
    
    # All neutral
    timeframes = {
        "15m": {"trend": "neutral", "return_15m": 0.05},
        "1h": {"trend": "neutral", "return_1h": -0.03},
        "4h": {"trend": "neutral", "return_4h": 0.08},
        "1d": {"trend": "neutral", "return_1d": 0.0}
    }
    
    summary = get_confluence_summary(timeframes)
    print(f"✓ Summary for neutral timeframes:")
    print(f"  LONG score: {summary['long_score']}")
    print(f"  SHORT score: {summary['short_score']}")
    print(f"  Recommendation: {summary['recommendation']}")
    
    assert summary["recommendation"] == "NEUTRAL", "Neutral timeframes should recommend NEUTRAL"
    assert summary["long_score"] < 70, "Neutral should score <70 for LONG"
    assert summary["short_score"] < 70, "Neutral should score <70 for SHORT"
    
    print("✓ Neutral timeframes test passed")


def run_all_tests():
    """Run all confluence scoring tests."""
    print("\n" + "="*80)
    print("CONFLUENCE SCORING MODULE - TEST SUITE")
    print("="*80)
    
    test_perfect_alignment()
    test_conflicting_signals()
    test_medium_confluence()
    test_short_direction()
    test_tf_aligned_boolean()
    test_confluence_summary()
    test_neutral_timeframes()
    
    print("\n" + "="*80)
    print("✓ ALL CONFLUENCE SCORING TESTS PASSED")
    print("="*80)


if __name__ == "__main__":
    run_all_tests()
