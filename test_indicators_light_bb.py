#!/usr/bin/env python3
"""
Test suite for LIGHT+BB indicators implementation.

Tests the following indicators:
1. Range metrics (64-candle window)
2. Bollinger Bands (20, 2)
3. Volume z-score (20-period window)

Validates:
- Correct calculation with sufficient data
- Graceful degradation with insufficient data
- Serialization compatibility (float/None, no NaN/Inf)
- Integration into multi-timeframe analysis
"""

import sys
import os
import pandas as pd
import numpy as np

# Add agents path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agents', '01_technical_analyzer'))

from indicators import CryptoTechnicalAnalysisBybit


def create_synthetic_ohlcv(n_candles: int, base_price: float = 3500.0, seed: int = 42) -> pd.DataFrame:
    """Create synthetic OHLCV data for testing"""
    np.random.seed(seed)
    dates = pd.date_range('2024-01-01', periods=n_candles, freq='15min')
    
    # Generate realistic price data with trend
    close_prices = base_price + np.cumsum(np.random.randn(n_candles) * 10)
    
    data = {
        'timestamp': dates,
        'open': close_prices + np.random.uniform(-5, 5, n_candles),
        'high': close_prices + np.abs(np.random.uniform(5, 20, n_candles)),
        'low': close_prices - np.abs(np.random.uniform(5, 20, n_candles)),
        'close': close_prices,
        'volume': np.random.uniform(1000, 5000, n_candles)
    }
    
    return pd.DataFrame(data)


def test_range_metrics_basic():
    """Test range metrics calculation with sufficient data"""
    print("=" * 80)
    print("TEST 1: Range Metrics - Basic Calculation (64 candles)")
    print("=" * 80)
    
    analyzer = CryptoTechnicalAnalysisBybit()
    df = create_synthetic_ohlcv(100)
    
    result = analyzer.calculate_range_metrics(df, window=64)
    
    # Validate all required fields present
    required_fields = [
        'range_high', 'range_low', 'range_mid', 
        'range_width_pct', 'distance_to_range_low_pct', 'distance_to_range_high_pct'
    ]
    
    assert isinstance(result, dict), "Result should be a dict"
    for field in required_fields:
        assert field in result, f"Missing field: {field}"
        assert isinstance(result[field], (int, float)), f"{field} should be numeric"
        assert not np.isnan(result[field]), f"{field} should not be NaN"
        assert not np.isinf(result[field]), f"{field} should not be Inf"
    
    # Validate logical constraints
    assert result['range_high'] >= result['range_low'], "range_high should be >= range_low"
    # Check mid is approximately average (within 0.01 due to rounding)
    expected_mid = (result['range_high'] + result['range_low']) / 2
    assert abs(result['range_mid'] - expected_mid) < 0.01, f"range_mid should be approximately average: {result['range_mid']} vs {expected_mid}"
    assert result['range_width_pct'] >= 0, "range_width_pct should be non-negative"
    
    print(f"✅ range_high: {result['range_high']}")
    print(f"✅ range_low: {result['range_low']}")
    print(f"✅ range_mid: {result['range_mid']}")
    print(f"✅ range_width_pct: {result['range_width_pct']:.3f}%")
    print(f"✅ distance_to_range_low_pct: {result['distance_to_range_low_pct']:.3f}%")
    print(f"✅ distance_to_range_high_pct: {result['distance_to_range_high_pct']:.3f}%")
    print("\n✅ TEST 1 PASSED\n")


def test_range_metrics_insufficient_data():
    """Test range metrics with insufficient data (graceful degradation)"""
    print("=" * 80)
    print("TEST 2: Range Metrics - Insufficient Data (10 candles, need 64)")
    print("=" * 80)
    
    analyzer = CryptoTechnicalAnalysisBybit()
    df = create_synthetic_ohlcv(10)
    
    result = analyzer.calculate_range_metrics(df, window=64)
    
    # Should return empty dict (graceful degradation)
    assert isinstance(result, dict), "Result should be a dict"
    assert len(result) == 0, "Result should be empty dict with insufficient data"
    
    print(f"✅ Result with 10 candles (need 64): {result}")
    print("✅ Graceful degradation confirmed")
    print("\n✅ TEST 2 PASSED\n")


def test_bollinger_bands_basic():
    """Test Bollinger Bands calculation"""
    print("=" * 80)
    print("TEST 3: Bollinger Bands - Basic Calculation (period=20, std_dev=2)")
    print("=" * 80)
    
    analyzer = CryptoTechnicalAnalysisBybit()
    df = create_synthetic_ohlcv(100)
    
    result = analyzer.calculate_bollinger_bands(df['close'], period=20, std_dev=2.0)
    
    # Validate all required fields present
    required_fields = ['bb_middle', 'bb_upper', 'bb_lower', 'bb_width_pct']
    
    assert isinstance(result, dict), "Result should be a dict"
    for field in required_fields:
        assert field in result, f"Missing field: {field}"
        assert isinstance(result[field], (int, float)), f"{field} should be numeric"
        assert not np.isnan(result[field]), f"{field} should not be NaN"
        assert not np.isinf(result[field]), f"{field} should not be Inf"
    
    # Validate logical constraints
    assert result['bb_upper'] >= result['bb_middle'], "bb_upper should be >= bb_middle"
    assert result['bb_middle'] >= result['bb_lower'], "bb_middle should be >= bb_lower"
    assert result['bb_width_pct'] >= 0, "bb_width_pct should be non-negative"
    
    print(f"✅ bb_middle: {result['bb_middle']}")
    print(f"✅ bb_upper: {result['bb_upper']}")
    print(f"✅ bb_lower: {result['bb_lower']}")
    print(f"✅ bb_width_pct: {result['bb_width_pct']:.3f}%")
    print("\n✅ TEST 3 PASSED\n")


def test_bollinger_bands_insufficient_data():
    """Test Bollinger Bands with insufficient data"""
    print("=" * 80)
    print("TEST 4: Bollinger Bands - Insufficient Data (10 candles, need 20)")
    print("=" * 80)
    
    analyzer = CryptoTechnicalAnalysisBybit()
    df = create_synthetic_ohlcv(10)
    
    result = analyzer.calculate_bollinger_bands(df['close'], period=20, std_dev=2.0)
    
    # Should return empty dict (graceful degradation)
    assert isinstance(result, dict), "Result should be a dict"
    assert len(result) == 0, "Result should be empty dict with insufficient data"
    
    print(f"✅ Result with 10 candles (need 20): {result}")
    print("✅ Graceful degradation confirmed")
    print("\n✅ TEST 4 PASSED\n")


def test_volume_zscore_basic():
    """Test volume z-score calculation"""
    print("=" * 80)
    print("TEST 5: Volume Z-Score - Basic Calculation (window=20)")
    print("=" * 80)
    
    analyzer = CryptoTechnicalAnalysisBybit()
    df = create_synthetic_ohlcv(100)
    
    result = analyzer.calculate_volume_zscore(df['volume'], window=20)
    
    # Validate result
    assert isinstance(result, (int, float)), "Result should be numeric"
    assert not np.isnan(result), "Result should not be NaN"
    assert not np.isinf(result), "Result should not be Inf"
    
    # Should be clamped to [-5, 5]
    assert -5.0 <= result <= 5.0, f"Z-score should be clamped to [-5, 5], got {result}"
    
    print(f"✅ volume_zscore: {result}")
    print(f"✅ Value is within bounds [-5, 5]")
    print("\n✅ TEST 5 PASSED\n")


def test_volume_zscore_insufficient_data():
    """Test volume z-score with insufficient data"""
    print("=" * 80)
    print("TEST 6: Volume Z-Score - Insufficient Data (10 candles, need 20)")
    print("=" * 80)
    
    analyzer = CryptoTechnicalAnalysisBybit()
    df = create_synthetic_ohlcv(10)
    
    result = analyzer.calculate_volume_zscore(df['volume'], window=20)
    
    # Should return 0.0 (graceful degradation)
    assert isinstance(result, (int, float)), "Result should be numeric"
    assert result == 0.0, f"Result should be 0.0 with insufficient data, got {result}"
    
    print(f"✅ Result with 10 candles (need 20): {result}")
    print("✅ Graceful degradation confirmed (returns 0.0)")
    print("\n✅ TEST 6 PASSED\n")


def test_volume_zscore_zero_std():
    """Test volume z-score with zero standard deviation (edge case)"""
    print("=" * 80)
    print("TEST 7: Volume Z-Score - Zero Std Dev (constant volume)")
    print("=" * 80)
    
    analyzer = CryptoTechnicalAnalysisBybit()
    
    # Create data with constant volume (std=0)
    df = create_synthetic_ohlcv(100)
    df['volume'] = 3000.0  # Constant volume
    
    result = analyzer.calculate_volume_zscore(df['volume'], window=20)
    
    # Should return 0.0 when std=0
    assert isinstance(result, (int, float)), "Result should be numeric"
    assert result == 0.0, f"Result should be 0.0 when std=0, got {result}"
    
    print(f"✅ Result with constant volume (std=0): {result}")
    print("✅ Edge case handled correctly")
    print("\n✅ TEST 7 PASSED\n")


def test_serialization():
    """Test that all indicators produce JSON-serializable values"""
    print("=" * 80)
    print("TEST 8: Serialization - All indicators should be JSON-safe")
    print("=" * 80)
    
    import json
    
    analyzer = CryptoTechnicalAnalysisBybit()
    df = create_synthetic_ohlcv(100)
    
    # Collect all indicator results
    results = {
        'range_metrics': analyzer.calculate_range_metrics(df, window=64),
        'bb_metrics': analyzer.calculate_bollinger_bands(df['close'], period=20, std_dev=2.0),
        'volume_zscore': analyzer.calculate_volume_zscore(df['volume'], window=20)
    }
    
    # Try to serialize
    try:
        json_str = json.dumps(results)
        assert len(json_str) > 0, "JSON string should not be empty"
        
        # Deserialize to verify
        parsed = json.loads(json_str)
        assert parsed == results, "Deserialized data should match original"
        
        print("✅ Range metrics: serializable")
        print("✅ BB metrics: serializable")
        print("✅ Volume z-score: serializable")
        print("✅ All indicators are JSON-safe")
        print("\n✅ TEST 8 PASSED\n")
    except (TypeError, ValueError) as e:
        assert False, f"Serialization failed: {e}"


def run_all_tests():
    """Run all test cases"""
    print("\n" + "=" * 80)
    print("LIGHT+BB INDICATORS TEST SUITE")
    print("=" * 80 + "\n")
    
    tests = [
        test_range_metrics_basic,
        test_range_metrics_insufficient_data,
        test_bollinger_bands_basic,
        test_bollinger_bands_insufficient_data,
        test_volume_zscore_basic,
        test_volume_zscore_insufficient_data,
        test_volume_zscore_zero_std,
        test_serialization
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"❌ FAILED: {test_func.__name__}")
            print(f"   Error: {e}\n")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR in {test_func.__name__}: {e}\n")
            failed += 1
    
    print("=" * 80)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed")
    print("=" * 80)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
