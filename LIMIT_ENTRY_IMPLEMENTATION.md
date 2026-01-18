# DeepSeek LIMIT Entry Implementation

## Summary

This implementation adds intelligent LIMIT order entry support with multi-timeframe confirmations to the trading system. The DeepSeek AI agent now makes informed decisions about when to use LIMIT vs MARKET entries and computes precise entry prices based on Fibonacci support/resistance levels and ATR bands.

## Key Changes

### 1. Master AI Prompt Enhancement (`agents/04_master_ai_agent/main.py`)

#### LIMIT Entry Formulas
Added deterministic rules for computing `entry_price`:

**For LONG entries (RANGE playbook):**
```
1. Find nearest Fibonacci support (0.786 or 0.618)
2. If price within 0.5% of support:
   entry_price = fib_support * (1 - 0.001)  # -0.1% for better fill
3. Otherwise use ATR:
   entry_price = current_price - (atr * 0.5)
```

**For SHORT entries (RANGE playbook):**
```
1. Find nearest Fibonacci resistance (1.272 or 1.618)
2. If price within 0.5% of resistance:
   entry_price = fib_resistance * (1 + 0.001)  # +0.1% for better fill
3. Otherwise use ATR:
   entry_price = current_price + (atr * 0.5)
```

#### TTL Guidance
```
- Strong setup + price near target: 60-120s
- Normal setup + price within 0.3%: 180-300s  
- Patient setup + price within 0.5%: 300-600s
- Max for 15m scalping: 600s
```

#### When to Use LIMIT
```
✅ LIMIT Entry Criteria:
  - Regime: RANGE (range_score >= 50)
  - Price within 0.5% of Fibonacci support/resistance
  - Setup: mean-reversion with RSI extreme
  - Confidence >= 70%
  - Gann levels confirm the S/R level

❌ Use MARKET Instead:
  - Regime: TREND (momentum/breakout)
  - High volatility (ATR > 2% of price)
  - Price already beyond target level
  - Confidence < 70%
  - No clear Fibonacci/Gann level nearby
```

### 2. Multi-Timeframe Confirmations

Added comprehensive multi-TF section to prompt:

**Trend Alignment Check (1h/4h):**
- For LONG: Verify 1h/4h not strongly bearish
- For SHORT: Verify 1h/4h not strongly bullish
- VETO if both higher TFs oppose direction

**Higher TF Momentum:**
- Check return_1h, return_4h for alignment
- Reduce size/leverage if 4h strongly opposes
- Boost confidence if 4h aligns

**ADX Multi-TF:**
- ADX 15m>25 AND 1h>20 → favor TREND playbook
- ADX 15m<20 AND 1h<20 → favor RANGE or HOLD
- Contradictory ADX → caution (potential fake breakout)

**RSI Multi-TF Divergence:**
- Both 15m and 1h >70 or <30 → STRONG mean-reversion signal
- Divergent RSI → WEAK signal, reduce confidence

**Veto Blockers:**
```python
# If 15m signals LONG but 1h+4h both in strong downtrend:
blocked_by: ["MOMENTUM_DOWN_1H"]

# If 15m signals SHORT but 1h+4h both in strong uptrend:
blocked_by: ["MOMENTUM_UP_1H"]
```

### 3. Orchestrator Mapping (Verified)

The orchestrator already correctly maps:
```python
# Line 930 in agents/orchestrator/main.py
payload["entry_ttl_sec"] = entry_expires_sec  # LLM → PM mapping
```

### 4. Position Manager (No Changes Needed)

The position manager already supports:
- LIMIT order submission with `orderLinkId`
- TTL-based expiry and cancellation
- Fill detection and post-fill SL placement
- Cancel+replace logic for price updates

## Tests

Created comprehensive test suite (`test_limit_entry_deepseek.py`):

1. **LIMIT Entry Decision Parsing** - Validates DeepSeek can produce LIMIT decisions with valid entry_price
2. **MARKET Entry Backward Compatibility** - Ensures MARKET entries still work
3. **Multi-Timeframe Veto** - Tests that higher TF conflicts properly block entries
4. **Orchestrator Mapping** - Verifies entry_expires_sec → entry_ttl_sec mapping
5. **Trailing Stop Regression** - Confirms no breaking changes to dynamic SL

All tests pass ✅

## Demo

Created end-to-end demo (`demo_limit_entry_flow.py`) showing:
- Sample market data for ETHUSDT in RANGE setup
- Step-by-step entry_price computation using Fibonacci
- Multi-timeframe confirmation checks
- Final AI decision with LIMIT entry
- Orchestrator payload mapping
- Position manager actions

## Expected Behavior

### Before (Current State)
```json
{
  "action": "OPEN_LONG",
  "entry_type": "MARKET",
  "entry_price": null,
  "entry_expires_sec": null
}
```

### After (With This Implementation)
```json
{
  "action": "OPEN_LONG",
  "entry_type": "LIMIT",
  "entry_price": 3506.49,
  "entry_expires_sec": 180,
  "rationale": "Playbook: RANGE. LIMIT entry at $3506.49 (Fib 0.786 support). Multi-TF confirmed: 1h neutral, 4h caution."
}
```

## Acceptance Criteria

✅ **Prompt includes LIMIT entry formulas** - Deterministic computation based on Fibonacci + ATR

✅ **Multi-timeframe confirmations** - 1h/4h trend alignment checks with veto rules

✅ **entry_expires_sec → entry_ttl_sec mapping** - Verified correct in orchestrator

✅ **Pending intent lifecycle** - TTL expiry, cancel+replace (already implemented in PM)

✅ **No regression in trailing SL** - Tests confirm dynamic SL continues to work

✅ **Tests validate end-to-end flow** - All tests pass

⏳ **Runtime verification** - Need to observe actual LIMIT decisions in logs (requires live system)

## Files Changed

1. `agents/04_master_ai_agent/main.py` - Enhanced SYSTEM_PROMPT with LIMIT formulas and multi-TF guidance
2. `test_limit_entry_deepseek.py` - Comprehensive test suite
3. `demo_limit_entry_flow.py` - End-to-end demonstration
4. `LIMIT_ENTRY_IMPLEMENTATION.md` - This documentation

## Next Steps

1. **Deploy to staging** - Test with real market data
2. **Monitor logs** - Verify LIMIT decisions appear in practice
3. **Tune parameters** - Adjust TTL ranges and thresholds based on live behavior
4. **A/B test** - Compare LIMIT vs MARKET entry performance (win rate, slippage, R:R)

## Notes

- LIMIT entries are **preferred for RANGE playbook** (mean-reversion at S/R levels)
- MARKET entries remain **default for TREND playbook** (momentum/breakout trades)
- Multi-timeframe vetos **prevent counter-trend entries** when higher TFs strongly oppose
- The system gracefully **falls back to MARKET** if entry_price is invalid or missing
- **No code changes** needed in orchestrator or position manager - they already support LIMIT
