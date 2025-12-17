# Crash Guard & Risk Management Features

## Overview
This document describes the crash guard momentum filters and risk management improvements implemented to prevent knife-catching entries and improve position management safety.

## Features Implemented

### 1. Crash Guard Metrics (Technical Analyzer)

The technical analyzer now collects short-term momentum metrics to detect rapid price movements:

**Metrics Added:**
- `return_1m`: 1-minute price change percentage (close-to-close)
- `return_5m`: 5-minute price change percentage (close-to-close)
- `return_15m`: 15-minute price change percentage (close-to-close)
- `range_5m_pct`: 5-minute range percentage ((high-low)/close * 100)
- `volume_spike_5m`: 5-minute volume spike (current_volume / avg_volume_20)

These metrics are included in the `get_multi_tf_analysis` endpoint response under the `summary` section and individual timeframe data.

**Location:** `agents/01_technical_analyzer/indicators.py`

### 2. Momentum Hard-Block (Master AI)

The Master AI now implements hard-block rules to prevent counter-momentum entries during rapid price movements.

**Blocking Rules:**
- **Block OPEN_LONG** if `return_5m <= -0.6%` (rapid dump)
- **Block OPEN_SHORT** if `return_5m >= +0.6%` (rapid pump)

When a position is blocked by crash guard:
- Action is converted to `HOLD`
- `blocked_by` field includes `"CRASH_GUARD"`
- Rationale explains the momentum condition that triggered the block
- Leverage and size_pct are set to 0

**Configuration (Environment Variables):**
```bash
# Block LONG entries when 5m return is below this threshold (negative %)
CRASH_GUARD_5M_LONG_BLOCK_PCT=0.6

# Block SHORT entries when 5m return is above this threshold (positive %)
CRASH_GUARD_5M_SHORT_BLOCK_PCT=0.6
```

**Location:** `agents/04_master_ai_agent/main.py`

### 3. 2-Cycle CRITICAL CLOSE Confirmation (Orchestrator)

To avoid premature exits on single wick spikes, the orchestrator now requires **2 consecutive cycles** before executing a CRITICAL CLOSE or REVERSE action.

**How It Works:**
1. **First Cycle**: CLOSE action is marked as pending, not executed
2. **Second Cycle**: If CLOSE is still requested, position is closed
3. **Reset**: If any other action (HOLD, REVERSE) occurs, pending is cleared

**State Tracking:**
- `pending_critical_closes`: Dictionary tracking pending close requests per symbol
- `check_critical_close_confirmation()`: Function implementing the 2-cycle logic

**Benefits:**
- Prevents closing positions on temporary spikes
- Gives positions time to recover from brief drawdowns
- Reduces false signals from high volatility

**Location:** `agents/orchestrator/main.py`

### 4. AI Parameters Pass-Through with Clamping (Orchestrator)

The orchestrator now respects AI-chosen leverage and size parameters while applying safety guardrails.

**Parameter Ranges:**
```python
MIN_LEVERAGE = 3      # Minimum allowed leverage
MAX_LEVERAGE = 10     # Maximum allowed leverage
MIN_SIZE_PCT = 0.08   # Minimum position size (8%)
MAX_SIZE_PCT = 0.20   # Maximum position size (20%)
```

**Behavior:**
- AI can choose leverage between 3x and 10x based on confidence
- AI can choose size_pct between 0.08 and 0.20 based on analysis
- Values outside ranges are clamped to min/max
- Clamping operations are logged for monitoring

**Fallback:**
- If AI doesn't provide values: defaults to conservative (3x, 0.08)
- Learning params can be used as fallback guidance

**Function:** `clamp_ai_params(leverage, size_pct, symbol)`

**Location:** `agents/orchestrator/main.py`

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Crash Guard - Momentum Filters
CRASH_GUARD_5M_LONG_BLOCK_PCT=0.6
CRASH_GUARD_5M_SHORT_BLOCK_PCT=0.6

# Critical Position Management
CRITICAL_LOSS_PCT_LEV=6.0
```

### Adjusting Sensitivity

**More Conservative (avoid more entries during volatility):**
```bash
CRASH_GUARD_5M_LONG_BLOCK_PCT=0.4  # Block LONG at -0.4% or below
CRASH_GUARD_5M_SHORT_BLOCK_PCT=0.4 # Block SHORT at +0.4% or above
```

**More Aggressive (allow more entries):**
```bash
CRASH_GUARD_5M_LONG_BLOCK_PCT=1.0  # Block LONG only at -1.0% or below
CRASH_GUARD_5M_SHORT_BLOCK_PCT=1.0 # Block SHORT only at +1.0% or above
```

## Usage Examples

### Example 1: LONG Entry Blocked During Dump

**Scenario:** BTC dumps -0.8% in 5 minutes

**System Behavior:**
1. Technical analyzer reports: `return_5m: -0.8`
2. Master AI considers LONG entry (RSI oversold, support nearby)
3. Crash guard detects: `-0.8% <= -0.6%`
4. Master AI blocks: 
   - Action: `HOLD`
   - blocked_by: `["CRASH_GUARD"]`
   - Rationale: "CRASH_GUARD: Blocked OPEN_LONG due to rapid dump (return_5m=-0.80% <= -0.6%). Avoiding knife catching."

### Example 2: SHORT Entry Blocked During Pump

**Scenario:** ETH pumps +0.9% in 5 minutes

**System Behavior:**
1. Technical analyzer reports: `return_5m: +0.9`
2. Master AI considers SHORT entry (RSI overbought, resistance)
3. Crash guard detects: `+0.9% >= +0.6%`
4. Master AI blocks:
   - Action: `HOLD`
   - blocked_by: `["CRASH_GUARD"]`
   - Rationale: "CRASH_GUARD: Blocked OPEN_SHORT due to rapid pump (return_5m=+0.90% >= +0.6%). Avoiding counter-momentum entry."

### Example 3: 2-Cycle CRITICAL CLOSE

**Scenario:** Position in -7% loss (with leverage)

**Cycle 1:**
- Master AI recommends: `CLOSE`
- Orchestrator: "⏸️ CRITICAL CLOSE pending for BTCUSDT (1st cycle, need confirmation)"
- Position: Remains open

**Cycle 2 (60 seconds later):**
- Still in loss, Master AI recommends: `CLOSE`
- Orchestrator: "✅ CRITICAL CLOSE confirmed for BTCUSDT (2nd cycle)"
- Position: Closed

**Cycle 2 Alternative (if recovered):**
- Recovered to -4% loss
- Master AI recommends: `HOLD`
- Orchestrator: "🔄 CRITICAL CLOSE reset for BTCUSDT (no CLOSE in this cycle)"
- Position: Remains open, pending cleared

### Example 4: AI Parameters with Clamping

**High Confidence Setup:**
- AI chooses: leverage=8.0, size_pct=0.18
- Orchestrator: Passes through unchanged (within ranges)
- Result: 8x leverage, 18% position size

**AI Overconfident:**
- AI chooses: leverage=15.0, size_pct=0.25
- Orchestrator: "⚙️ CLAMP BTCUSDT: leverage 15.0→10.0, size_pct 0.250→0.200"
- Result: 10x leverage (clamped), 20% position size (clamped)

**Low Confidence Setup:**
- AI chooses: leverage=3.0, size_pct=0.10
- Orchestrator: Passes through unchanged
- Result: 3x leverage, 10% position size

## Testing

Run the comprehensive test suite:

```bash
python3 test_crash_guard.py
```

**Tests Cover:**
- ✅ Crash guard metrics presence in technical analyzer
- ✅ Master AI momentum hard-block logic
- ✅ 2-cycle CRITICAL CLOSE confirmation
- ✅ AI parameters clamping
- ✅ Environment variable configuration

## Monitoring

**Watch for these log messages:**

**Crash Guard Blocks:**
```
🚫 CRASH_GUARD: Blocked OPEN_LONG due to rapid dump (return_5m=-0.80% <= -0.6%). Avoiding knife catching.
🚫 CRASH_GUARD: Blocked OPEN_SHORT due to rapid pump (return_5m=+0.90% >= +0.6%). Avoiding counter-momentum entry.
```

**2-Cycle Confirmation:**
```
⏸️ CRITICAL CLOSE pending for BTCUSDT (1st cycle, need confirmation)
✅ CRITICAL CLOSE confirmed for BTCUSDT (2nd cycle)
🔄 CRITICAL CLOSE reset for BTCUSDT (no CLOSE in this cycle)
```

**Parameter Clamping:**
```
⚙️ CLAMP BTCUSDT: leverage 15.0→10.0, size_pct 0.250→0.200
⚙️ CLAMP ETHUSDT: leverage 2.0→3.0, size_pct 0.050→0.080
```

## Performance Impact

**Expected Improvements:**
- **Fewer knife-catching entries**: Reduced losses from counter-momentum trades
- **Better exit timing**: 2-cycle confirmation prevents premature exits on wicks
- **Controlled risk**: AI params clamping ensures positions stay within safe ranges
- **Maintained flexibility**: AI can still choose params within safe ranges based on analysis

**Trade-offs:**
- May miss some reversal entries during strong moves
- Delayed exits may increase losses in sustained downtrends
- Adjust thresholds based on your risk tolerance and market conditions

## Troubleshooting

**Issue:** Too many entries blocked
**Solution:** Increase crash guard thresholds (e.g., from 0.6 to 1.0)

**Issue:** Still catching falling knives
**Solution:** Decrease crash guard thresholds (e.g., from 0.6 to 0.4)

**Issue:** Positions closing too early
**Solution:** 2-cycle confirmation is working as designed. Consider increasing `CRITICAL_LOSS_PCT_LEV` threshold.

**Issue:** Positions not closing in real crashes
**Solution:** Check that Master AI is detecting critical losses. May need to adjust `CRITICAL_LOSS_PCT_LEV` or monitor for technical analyzer data issues.

## Future Enhancements

Potential improvements for future versions:
- Adaptive thresholds based on market volatility
- Volume confirmation requirements
- Multi-timeframe momentum alignment
- Machine learning-based momentum classification
- Configurable confirmation cycles (1-3 cycles)

---

**Version:** 1.0  
**Last Updated:** 2025-12-17  
**Related Files:**
- `agents/01_technical_analyzer/indicators.py`
- `agents/04_master_ai_agent/main.py`
- `agents/orchestrator/main.py`
- `.env.example`
- `test_crash_guard.py`
