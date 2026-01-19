# Opportunistic Limit Indicators Implementation

## Summary

Successfully implemented missing indicators (LIGHT+BB: range structure, Bollinger Bands, volume z-score) to enable `opportunistic_limit` generation by the LLM, with configurable validation thresholds via environment variables.

## Implementation Details

### A. Technical Indicators (`agents/01_technical_analyzer/indicators.py`)

#### 1. Range Metrics (64-candle window)
Applied to 15m and 1h timeframes:
- `range_high`: Maximum high over window
- `range_low`: Minimum low over window
- `range_mid`: Midpoint of range
- `range_width_pct`: Range width as percentage of midpoint
- `distance_to_range_low_pct`: Current price distance from range low (%)
- `distance_to_range_high_pct`: Current price distance from range high (%)

#### 2. Bollinger Bands (20-period SMA, 2 std dev)
Applied to 15m and 1h timeframes:
- `bb_upper`: Upper band (SMA + 2*std)
- `bb_middle`: Middle band (SMA)
- `bb_lower`: Lower band (SMA - 2*std)
- `bb_width_pct`: Band width as percentage of middle

#### 3. Volume Z-Score (20-period window)
Applied to 15m and 1h timeframes:
- Standardized volume: `(vol - mean) / std`
- Clamped to [-5, 5] range
- Handles std=0 case gracefully

### B. Master AI Agent Updates (`agents/04_master_ai_agent/main.py`)

#### 1. Prompt Changes
- **Before**: "MAY propose opportunistic_limit"
- **After**: "MUST evaluate if opportunistic_limit exists when action=HOLD"
- Added guidance on using range metrics, BB, and volume z-score
- Requirement to explain why opportunistic_limit is null if not proposed
- Updated example to showcase new indicators

#### 2. Environment Variables
```bash
OPP_LIMIT_MIN_TP_PCT=0.008              # Minimum TP 0.8% (was hardcoded 1%)
OPP_LIMIT_MIN_RR=1.5                     # Minimum risk/reward ratio
OPP_LIMIT_MAX_ENTRY_DISTANCE_PCT=0.006  # Max entry distance 0.6% (was 0.8%)
OPP_LIMIT_MIN_EDGE_SCORE=60             # Minimum edge score (new)
```

#### 3. Enhanced Logging
- Log when LLM proposes opportunistic_limit: `🎯 Opportunistic LIMIT VALIDATED for {symbol}: {side} @ {entry}, RR={rr}, TP={tp}%, SL={sl}%, edge_score={edge}`
- Log when rejected: `🚫 Opportunistic LIMIT rejected for {symbol}: {reason}`

### C. Dashboard Updates (`dashboard/components/ai_reasoning.py`)

Added display of new indicators from input_snapshot:
- Range: `{range_low}-{range_high} (width: {width}%)`
- Bollinger Bands: `{bb_lower}-{bb_upper} (width: {width}%)`
- Volume Z-Score: Color-coded display (green >1, red <-1, orange otherwise)

### D. Testing (`test_indicators_opportunistic.py`)

Comprehensive test suite with 6 tests:
1. Range metrics calculation on synthetic data
2. Bollinger Bands calculation on synthetic data
3. Volume z-score calculation on synthetic data
4. Backward compatibility (missing/insufficient data)
5. Validator with environment variable overrides
6. Integration test (indicators in multi_tf_analysis)

**All tests pass**: ✅

## Usage Examples

### For LLM Context

The LLM now receives in market_data:
```json
{
  "15m": {
    "price": 50000.0,
    "rsi": 32,
    "range_high": 50500.0,
    "range_low": 49500.0,
    "range_mid": 50000.0,
    "range_width_pct": 2.0,
    "distance_to_range_low_pct": 1.0,
    "distance_to_range_high_pct": 1.0,
    "bb_upper": 50200.0,
    "bb_middle": 50000.0,
    "bb_lower": 49800.0,
    "bb_width_pct": 0.8,
    "volume_zscore": 2.1
  }
}
```

### LLM Decision Example

```json
{
  "action": "HOLD",
  "opportunistic_limit": {
    "side": "LONG",
    "entry_price": 49850.0,
    "entry_expires_sec": 180,
    "tp_pct": 0.012,
    "sl_pct": 0.008,
    "rr": 1.5,
    "edge_score": 72,
    "reasoning_bullets": [
      "Price near range_low at 49500 (distance_to_range_low_pct: 0.7%)",
      "Price touching bb_lower (49800), BB width 0.8% shows volatility",
      "Volume z-score +2.1 confirms accumulation at support",
      "RSI 15m oversold at 32, 1h trend neutral"
    ]
  }
}
```

## Backward Compatibility

- ✅ Returns empty dict `{}` for missing/insufficient data
- ✅ Indicators only calculated for 15m and 1h (not 4h, 1d)
- ✅ Existing code without indicators continues to work
- ✅ Dashboard gracefully handles missing indicator data
- ✅ All existing tests pass

## Validation Gates

Updated gates with configurable thresholds:
1. Action must be HOLD
2. No hard blockers
3. RR >= `OPP_LIMIT_MIN_RR` (default 1.5)
4. TP >= `OPP_LIMIT_MIN_TP_PCT` (default 0.008)
5. SL within bounds
6. entry_expires_sec in [60, 300]
7. Entry price distance <= `OPP_LIMIT_MAX_ENTRY_DISTANCE_PCT` (default 0.006)
8. Volatility above minimum
9. Edge score >= `OPP_LIMIT_MIN_EDGE_SCORE` (default 60)
10. Required fields present
11. Valid data types

## Conservative Mode Maintained

- ✅ Maximum 1 opportunistic_limit per symbol per cycle
- ✅ No fallback to MARKET orders
- ✅ All validation gates still active
- ✅ Configurable thresholds only change values, not logic
- ✅ LLM must justify why no opportunistic_limit if action=HOLD

## Files Changed

1. `agents/01_technical_analyzer/indicators.py` - Added 3 indicator functions
2. `agents/04_master_ai_agent/main.py` - Updated prompt, added env vars, enhanced logging
3. `.env.example` - Added 4 new configuration variables
4. `dashboard/components/ai_reasoning.py` - Added indicator display
5. `test_indicators_opportunistic.py` - New comprehensive test suite

## Verification

- ✅ All new tests pass (6/6)
- ✅ All existing opportunistic_limit tests pass (9/9)
- ✅ Manual verification of indicator calculations
- ✅ Code review completed and feedback addressed
- ✅ Integration verification passed
- ✅ Backward compatibility verified

## Next Steps

1. Deploy to test environment
2. Monitor LLM generation of opportunistic_limit with new indicators
3. Analyze count of opportunistic_limit proposals (should be > 0 now)
4. Fine-tune thresholds based on real trading data if needed
5. Consider adding more indicators if LLM still struggles (Fibonacci overlap, VWAP, etc.)

## Configuration Recommendations

### Conservative (Default)
```bash
OPP_LIMIT_MIN_TP_PCT=0.008              # 0.8%
OPP_LIMIT_MIN_RR=1.5
OPP_LIMIT_MAX_ENTRY_DISTANCE_PCT=0.006  # 0.6%
OPP_LIMIT_MIN_EDGE_SCORE=60
```

### Moderate
```bash
OPP_LIMIT_MIN_TP_PCT=0.006              # 0.6%
OPP_LIMIT_MIN_RR=1.3
OPP_LIMIT_MAX_ENTRY_DISTANCE_PCT=0.008  # 0.8%
OPP_LIMIT_MIN_EDGE_SCORE=55
```

### Aggressive (Not Recommended for Production)
```bash
OPP_LIMIT_MIN_TP_PCT=0.005              # 0.5%
OPP_LIMIT_MIN_RR=1.2
OPP_LIMIT_MAX_ENTRY_DISTANCE_PCT=0.010  # 1.0%
OPP_LIMIT_MIN_EDGE_SCORE=50
```

---

**Implementation Date**: 2026-01-19
**Status**: ✅ Complete and Ready for Deployment
