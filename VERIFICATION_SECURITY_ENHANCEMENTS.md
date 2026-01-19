# Security & AI Autonomy Enhancements - Verification Guide

This document provides manual verification steps and test scenarios for the security and AI autonomy enhancements implemented in this PR.

## Overview of Changes

### A) Security / Risk Management (Anti-Blowup)
1. **Risk-based sizing**: Deterministic position sizing based on max loss per trade
2. **Recovery sizing disabled**: Martingale-like behavior disabled by default (ENABLE_RECOVERY_SIZING=false)
3. **LIMIT fallback removed**: Invalid LIMIT entries convert to HOLD (not MARKET)
4. **Leverage clamping**: Enforced range [3,10] with optional confidence-based adjustment
5. **Symbol already open**: Hard constraint preventing multiple positions on same symbol

### B) AI Autonomy / Debias
1. **Neutral system prompt**: Removed prescriptive trading strategies and thresholds
2. **Clean data input**: Removed regime labels and score labels from LLM payload
3. **No policy concatenation**: System prompt not modified with constraints/policy text

### C) Audit/Observability
1. **Enhanced decision logging**: Input snapshots and prompt version included in ai_decisions.json

## Environment Variables Added

```bash
# Risk-based sizing (Anti-Blowup Protection)
MAX_LOSS_USDT_PER_TRADE=0.35          # Max loss per trade in USDT
MAX_TOTAL_RISK_USDT=1.5               # Max total portfolio risk in USDT
MIN_SL_DISTANCE_PCT=0.0025            # Min SL distance (0.25%)
MAX_SL_DISTANCE_PCT=0.025             # Max SL distance (2.5%)
MAX_NOTIONAL_USDT=50.0                # Max notional size per trade
MARGIN_SAFETY_FACTOR=0.85             # Margin safety factor

# Recovery sizing (default OFF for LIVE)
ENABLE_RECOVERY_SIZING=false          # Disable martingale-like recovery

# Leverage constraints
MIN_LEVERAGE=3                        # Minimum leverage (floor)
MAX_LEVERAGE_OPEN=10                  # Maximum leverage (ceiling)
ENABLE_CONFIDENCE_LEVERAGE_ADJUST=false  # Confidence-based leverage caps
LEVERAGE_CAP_CONFIDENCE_LOW=60        # Low confidence threshold
LEVERAGE_CAP_CONFIDENCE_MED=75        # Medium confidence threshold
LEVERAGE_MAX_CONFIDENCE_LOW=4         # Max leverage if confidence < 60
LEVERAGE_MAX_CONFIDENCE_MED=6         # Max leverage if 60 <= confidence < 75
```

## Manual Verification Steps

### Test 1: Risk-Based Sizing

**Scenario**: Force an OPEN decision with valid SL and verify size is limited by risk-based calc.

**Steps**:
1. Set `MAX_LOSS_USDT_PER_TRADE=0.35` and `MAX_NOTIONAL_USDT=50.0`
2. Trigger a decision with:
   - Entry price: $50,000
   - SL: $49,500 (1% SL distance)
   - Leverage: 5x
3. Expected notional: `0.35 / 0.01 = 35 USDT` (clamped to 50 max)
4. Expected margin: `35 / 5 = 7 USDT`

**Verification**:
- Check logs for: `📊 Risk-based sizing for SYMBOL: size_pct X → Y, notional=35 USDT, margin=7 USDT`
- Confirm size_pct is calculated correctly
- Confirm no recovery sizing is applied (if ENABLE_RECOVERY_SIZING=false)

### Test 2: LIMIT Entry Without Valid Price → HOLD

**Scenario**: AI proposes LIMIT entry but entry_price is missing or invalid.

**Steps**:
1. Force AI to return entry_type="LIMIT" but entry_price=null or 0
2. Observe decision processing

**Expected Behavior**:
- Decision converted to HOLD
- blocked_by includes "INVALID_ENTRY_PRICE"
- Log shows: `⚠️ LIMIT entry without valid entry_price for SYMBOL: X. Converting to HOLD.`
- **NOT** converted to MARKET (old behavior removed)

### Test 3: Symbol Already Open Constraint

**Scenario**: Attempt to open second position on same symbol.

**Steps**:
1. Open a position on BTCUSDT (any side)
2. Trigger AI decision to open another position on BTCUSDT

**Expected Behavior**:
- Second decision converted to HOLD
- blocked_by includes "SYMBOL_ALREADY_OPEN"
- Log shows: `🚫 Blocked OPEN_X on BTCUSDT: symbol already has open position`
- Position manager rejects order with same error

### Test 4: Leverage Clamping

**Scenario A**: AI proposes leverage outside [3,10] range.

**Steps**:
1. Force AI to return leverage=15 or leverage=2
2. Observe clamping

**Expected Behavior**:
- Leverage=15 clamped to 10
- Leverage=2 clamped to 3
- Log shows: `📊 Leverage clamped for SYMBOL: 15.0x → 10.0x` or `2.0x → 3.0x`

**Scenario B**: Confidence-based leverage adjustment (if enabled).

**Steps**:
1. Set `ENABLE_CONFIDENCE_LEVERAGE_ADJUST=true`
2. Force AI to return leverage=8 with confidence=55

**Expected Behavior**:
- Leverage clamped to 4 (confidence < 60)
- Log shows: `📊 Leverage clamped for SYMBOL: 8.0x → 4.0x (confidence=55)`

### Test 5: Recovery Sizing Disabled

**Scenario**: Verify recovery sizing is not applied when disabled.

**Steps**:
1. Ensure `ENABLE_RECOVERY_SIZING=false`
2. Close a losing position
3. Trigger AI decision for reverse/recovery

**Expected Behavior**:
- size_pct calculated using risk-based sizing only
- **NO** recovery_extra added
- **NO** martingale-like size increase

### Test 6: Neutral AI Prompt

**Scenario**: Verify AI receives neutral prompt without prescriptive strategies.

**Steps**:
1. Enable debug logging
2. Trigger AI decision
3. Inspect request payload and system prompt

**Expected Behavior**:
- System prompt does **NOT** contain:
  - "MASSIMIZZARE I PROFITTI"
  - "SCALPING AGGRESSIVE"
  - Specific playbook instructions
  - Numeric thresholds (45, 50, etc.)
  - Policy concatenations (constraints_text, margin_text, etc.)
- System prompt **DOES** contain:
  - Neutral role description
  - JSON format specification
  - List of hard/soft constraints
  - General decision guidelines

### Test 7: Clean Data Input (No Labels)

**Scenario**: Verify AI payload does not contain regime/score labels.

**Steps**:
1. Enable debug logging
2. Inspect prompt_data sent to AI

**Expected Behavior**:
- `market_data[SYMBOL].fase2_metrics` contains numeric metrics only:
  - volatility_pct ✓
  - atr ✓
  - trend_strength ✓
  - adx ✓
  - ema_20, ema_200 ✓
  - regime ✗ (NOT present)
- `market_data[SYMBOL]` does **NOT** contain:
  - pre_score ✗
  - range_score ✗

### Test 8: Input Snapshot in Decisions

**Scenario**: Verify ai_decisions.json includes input metadata for audit.

**Steps**:
1. Trigger AI decision (any action)
2. Inspect `/data/ai_decisions.json`

**Expected Fields**:
```json
{
  "timestamp": "...",
  "symbol": "BTCUSDT",
  "action": "OPEN_LONG",
  "input_snapshot": {
    "entry_price": 50000,
    "sl_pct": 0.015,
    "tp_pct": 0.02,
    "leverage": 5,
    "entry_type": "LIMIT",
    "wallet_available": 100,
    "positions_open": 1
  },
  "prompt_version": "v3_neutral",
  ...
}
```

### Test 9: SL Distance Validation

**Scenario**: Verify SL distance bounds are enforced.

**Steps**:
1. Force AI decision with SL very tight (0.1%)
2. Force AI decision with SL very wide (5%)

**Expected Behavior**:
- SL < 0.25% (MIN_SL_DISTANCE_PCT) → blocked_by includes "SL_TOO_TIGHT"
- SL > 2.5% (MAX_SL_DISTANCE_PCT) → blocked_by includes "SL_TOO_WIDE"
- Decision converted to HOLD

### Test 10: Portfolio Risk Limit

**Scenario**: Verify total portfolio risk is capped.

**Steps**:
1. Set `MAX_TOTAL_RISK_USDT=1.5`
2. Open position with 1.0 USDT risk
3. Attempt to open second position with 0.8 USDT risk (would exceed 1.5)

**Expected Behavior**:
- Second decision blocked
- blocked_by includes "MAX_TOTAL_RISK_EXCEEDED"
- Log shows: `Total portfolio risk X USDT > max 1.5 USDT`

## Position Manager Compatibility

**Verification**: Ensure Position Manager trailing/dynamic SL continues to work.

**What to Check**:
1. Trailing stop still activates when ROI reaches threshold
2. Break-even protection still works
3. Profit lock mechanism still functions
4. Dynamic SL tightening still applies
5. `/data/trailing_state.json` and `/data/profit_lock_state.json` still update

**Expected Behavior**:
- **NO changes** to Position Manager logic
- All existing trailing/stop mechanisms work as before
- Only Master AI decision-making is affected

## Test Results Template

```
Date: [YYYY-MM-DD]
Environment: [testnet/live]
Tester: [name]

| Test | Status | Notes |
|------|--------|-------|
| 1. Risk-based sizing | ✓/✗ | |
| 2. LIMIT→HOLD (not MARKET) | ✓/✗ | |
| 3. Symbol already open | ✓/✗ | |
| 4. Leverage clamping | ✓/✗ | |
| 5. Recovery sizing disabled | ✓/✗ | |
| 6. Neutral AI prompt | ✓/✗ | |
| 7. Clean data input | ✓/✗ | |
| 8. Input snapshot logging | ✓/✗ | |
| 9. SL distance validation | ✓/✗ | |
| 10. Portfolio risk limit | ✓/✗ | |
| Position Manager compat | ✓/✗ | |
```

## Known Limitations

1. **Risk-based sizing** requires valid entry_price and sl_pct. If missing, falls back to warning but doesn't block.
2. **Portfolio risk calculation** for existing positions is approximate (assumes 1% SL if actual SL unknown).
3. **Confidence-based leverage** requires AI to provide confidence field (usually does).

## Rollback Procedure

If issues are found in LIVE:

1. **Disable risk-based sizing**: Set `ENABLE_RECOVERY_SIZING=true` (reverts to old size_pct)
2. **Disable leverage adjust**: Set `ENABLE_CONFIDENCE_LEVERAGE_ADJUST=false`
3. **Restore old prompt**: Revert `SYSTEM_PROMPT` changes (git revert)
4. **Monitor** for 1-2 trading cycles
5. **Report** issues for investigation

## Success Criteria

✅ All manual tests pass
✅ No Position Manager regressions
✅ Risk-based sizing prevents over-leverage
✅ SYMBOL_ALREADY_OPEN prevents duplicate positions
✅ AI receives clean, unbiased data
✅ Decisions are auditable with input snapshots
