# Security and AI Autonomy Enhancements

This PR implements comprehensive security improvements and AI autonomy enhancements to make the trading system safer for LIVE trading with small accounts (~100 USDT) while reducing AI prompt bias.

## Problem Statement

**Context**: Trading LIVE with ~100 USDT account, 1 position per symbol, LIMIT order entries with trailing/dynamic stops.

**Issues to Address**:
1. System could blow up account with oversized positions or poor risk management
2. AI prompt was prescriptive with hard-coded strategies and thresholds
3. AI received biased inputs (regime labels, pre_score/range_score)
4. Recovery sizing (martingale-like) was risky for LIVE trading
5. LIMIT orders would fallback to MARKET automatically (unsafe)
6. No enforcement of one-position-per-symbol constraint

## Solution Overview

### A) Security / Risk Management (Anti-Blowup)

#### 1. **Risk-Based Sizing**
Position size calculated deterministically based on maximum acceptable loss per trade:

```python
notional = MAX_LOSS_USDT_PER_TRADE / sl_distance_pct
margin_required = notional / leverage
```

**Configuration** (`.env`):
```bash
MAX_LOSS_USDT_PER_TRADE=0.35          # Max loss per trade
MAX_TOTAL_RISK_USDT=1.5               # Max total portfolio risk
MIN_SL_DISTANCE_PCT=0.0025            # Min SL distance (0.25%)
MAX_SL_DISTANCE_PCT=0.025             # Max SL distance (2.5%)
MAX_NOTIONAL_USDT=50.0                # Max notional per trade
MARGIN_SAFETY_FACTOR=0.85             # Margin safety factor
```

**Benefits**:
- Prevents account blow-up from oversized positions
- Enforces consistent risk per trade
- Accounts for stop loss distance (tighter SL = larger position, wider SL = smaller position)
- Validates against available margin

#### 2. **Recovery Sizing Disabled (Default OFF)**
Martingale-like "recovery sizing" after losses is now disabled by default:

```bash
ENABLE_RECOVERY_SIZING=false  # Default for LIVE
```

When disabled:
- No automatic position size increase after losses
- Uses risk-based sizing only
- Prevents revenge trading and martingale spirals

#### 3. **LIMIT Entry Validation (No Fallback to MARKET)**
Invalid LIMIT entries now convert to HOLD instead of automatically falling back to MARKET:

**Old Behavior**:
```
LIMIT without entry_price → Fallback to MARKET → Potentially bad fill
```

**New Behavior**:
```
LIMIT without entry_price → Convert to HOLD with blocked_by=["INVALID_ENTRY_PRICE"]
```

**Why**: MARKET orders can get bad fills during volatile conditions. Better to wait for valid LIMIT setup.

#### 4. **Leverage Clamping**
Enforced leverage range with optional confidence-based adjustment:

**Basic Clamping**:
```bash
MIN_LEVERAGE=3                        # Floor
MAX_LEVERAGE_OPEN=10                  # Ceiling
```
All OPEN decisions clamped to [3, 10] range.

**Confidence-Based Adjustment** (optional):
```bash
ENABLE_CONFIDENCE_LEVERAGE_ADJUST=true
LEVERAGE_CAP_CONFIDENCE_LOW=60        # If confidence < 60, max leverage = 4
LEVERAGE_CAP_CONFIDENCE_MED=75        # If 60 <= confidence < 75, max leverage = 6
LEVERAGE_MAX_CONFIDENCE_LOW=4
LEVERAGE_MAX_CONFIDENCE_MED=6
```

**Example**:
- AI proposes leverage=8 with confidence=55
- Clamped to 4 (low confidence cap)

#### 5. **SYMBOL_ALREADY_OPEN Constraint**
Hard constraint preventing multiple positions on same symbol:

**Enforcement**:
```python
if symbol in active_positions:
    decision.action = "HOLD"
    decision.blocked_by.append("SYMBOL_ALREADY_OPEN")
```

**Why**: One position per symbol policy prevents overexposure and simplifies risk management.

### B) AI Autonomy / Debias Prompt

#### 1. **Neutral System Prompt**
Rewrote system prompt to be neutral and analytical:

**Removed**:
- ❌ "MASSIMIZZARE I PROFITTI"
- ❌ "SCALPING AGGRESSIVE MA PROFITTEVOLI"
- ❌ Prescriptive trading strategies
- ❌ Hard-coded numeric thresholds
- ❌ Aggressive trading objectives

**Added**:
- ✅ Neutral role: "experienced crypto trading AI analyzing market data"
- ✅ Analytical approach: "make informed trading decisions based on assessment"
- ✅ Clear structure: role, data, constraints, decision format
- ✅ Guidelines without bias

**Result**: AI makes decisions based on data analysis, not pre-programmed strategies.

#### 2. **Removed Policy/Constraint Text Concatenation**
Old system prompt was dynamically built by concatenating:
- constraints_text (positions, wallet, drawdown warnings)
- margin_text (insufficient margin warnings)
- cooldown_text (recent closes)
- performance_text (system performance)
- learning_policy_text (evolved parameters)

**New approach**:
- All context data included in structured `prompt_data` JSON
- System prompt remains static and neutral
- AI accesses data from JSON, not from concatenated text instructions

**Why**: Concatenated policy text was prescriptive and could bias AI decisions.

#### 3. **Clean Data Input (No Labels)**
Removed biased labels from LLM payload:

**Removed from LLM**:
- ❌ `fase2_metrics.regime` label ("TREND" / "RANGE")
- ❌ `pre_score` (base confidence score with label)
- ❌ `range_score` (range playbook score with label)

**Kept (Numeric Metrics Only)**:
- ✅ `volatility_pct` (numeric)
- ✅ `atr` (numeric)
- ✅ `trend_strength` (numeric)
- ✅ `adx` (numeric)
- ✅ `ema_20`, `ema_200` (numeric)

**Why**: Labels like "TREND" or "RANGE" bias AI toward specific strategies. Numeric metrics let AI decide.

**Note**: `pre_score` and `range_score` are still computed and used **server-side** for validation, but **not sent to LLM**.

### C) Audit / Observability

#### Enhanced Decision Logging
`ai_decisions.json` now includes:

```json
{
  "timestamp": "...",
  "symbol": "BTCUSDT",
  "action": "OPEN_LONG",
  "confidence": 75,
  "leverage": 5,
  "size_pct": 0.12,
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

**Benefits**:
- Correlate decisions with input conditions
- Track prompt version for A/B testing
- Debug AI behavior
- Audit trail for regulatory/compliance

## Impact Summary

### Security Improvements
| Feature | Before | After | Risk Reduction |
|---------|--------|-------|----------------|
| Position Sizing | AI-proposed size_pct | Risk-based calc | **High** - Prevents over-leverage |
| Recovery Sizing | Always active | Off by default | **Critical** - Prevents martingale |
| Leverage | AI-proposed (1-10) | Clamped [3,10] + confidence | **Medium** - Caps excessive leverage |
| LIMIT Fallback | Auto MARKET | Convert to HOLD | **Medium** - Prevents bad fills |
| Symbol Constraint | Not enforced | Hard constraint | **Low** - Prevents overexposure |
| SL Distance | Not validated | Min/max bounds | **Medium** - Prevents extreme SLs |
| Portfolio Risk | Not tracked | Max total risk | **High** - Prevents account blow-up |

### AI Autonomy Improvements
| Feature | Before | After | Benefit |
|---------|--------|-------|---------|
| Prompt Style | Prescriptive playbook | Neutral analytical | Less bias, more adaptive |
| Policy Text | Concatenated to prompt | Structured in data | Cleaner separation |
| Regime Label | Sent to LLM | Only numeric metrics | AI decides strategy |
| Score Labels | Sent to LLM | Server-side only | AI analyzes raw data |

## Configuration

### Recommended Settings (LIVE, ~100 USDT)

```bash
# Risk Management
MAX_LOSS_USDT_PER_TRADE=0.35          # Max $0.35 loss per trade
MAX_TOTAL_RISK_USDT=1.5               # Max $1.50 total portfolio risk
MAX_NOTIONAL_USDT=50.0                # Max $50 position size
MIN_SL_DISTANCE_PCT=0.0025            # Min 0.25% SL
MAX_SL_DISTANCE_PCT=0.025             # Max 2.5% SL
MARGIN_SAFETY_FACTOR=0.85             # Leave 15% margin buffer

# Recovery Sizing
ENABLE_RECOVERY_SIZING=false          # Disable martingale

# Leverage
MIN_LEVERAGE=3                        # Minimum leverage
MAX_LEVERAGE_OPEN=10                  # Maximum leverage
ENABLE_CONFIDENCE_LEVERAGE_ADJUST=false  # Disable for now (can enable later)

# Existing (unchanged)
BYBIT_HEDGE_MODE=false                # One-way mode
MAX_OPEN_POSITIONS=10                 # Max positions
```

### Recommended Settings (TESTNET, Testing)

```bash
# Risk Management (more permissive for testing)
MAX_LOSS_USDT_PER_TRADE=1.0           # Allow $1 loss per trade
MAX_TOTAL_RISK_USDT=5.0               # Allow $5 total portfolio risk
MAX_NOTIONAL_USDT=200.0               # Allow $200 position size
MIN_SL_DISTANCE_PCT=0.0010            # Min 0.1% SL
MAX_SL_DISTANCE_PCT=0.050             # Max 5% SL
MARGIN_SAFETY_FACTOR=0.80             # 20% margin buffer

# Recovery Sizing (can test both modes)
ENABLE_RECOVERY_SIZING=true           # Test recovery sizing if needed

# Leverage (can test confidence adjustment)
ENABLE_CONFIDENCE_LEVERAGE_ADJUST=true  # Test confidence-based caps
```

## Testing

See [VERIFICATION_SECURITY_ENHANCEMENTS.md](./VERIFICATION_SECURITY_ENHANCEMENTS.md) for:
- Manual verification steps
- Test scenarios for each feature
- Expected behaviors
- Compatibility checks
- Rollback procedures

## Migration Notes

### Breaking Changes
None. All changes are backward compatible with default behavior preserved.

### Opt-In Features
- `ENABLE_RECOVERY_SIZING=true` to restore old recovery sizing
- `ENABLE_CONFIDENCE_LEVERAGE_ADJUST=true` for confidence-based leverage caps

### Position Manager
**No changes** to Position Manager. All trailing stop, break-even, and profit lock features continue to work as before.

## Monitoring

### Key Metrics to Track
1. **Average position size** - Should be smaller and more consistent
2. **Max drawdown** - Should not exceed risk limits
3. **Number of HOLD decisions** - May increase (safer)
4. **LIMIT order fill rate** - Should remain similar (LIMIT→HOLD doesn't affect successful LIMITs)
5. **Number of blocked decisions** - Track which constraints trigger most

### Log Messages to Monitor
```
📊 Risk-based sizing for SYMBOL: ...
📊 Leverage clamped for SYMBOL: ...
🚫 Blocked OPEN_X on SYMBOL: symbol already has open position
⚠️ LIMIT entry without valid entry_price for SYMBOL: ... Converting to HOLD.
```

## Rollback

If issues in LIVE:
1. Set `ENABLE_RECOVERY_SIZING=true` (reverts sizing to old behavior)
2. Set `ENABLE_CONFIDENCE_LEVERAGE_ADJUST=false` (disables confidence caps)
3. Can revert commit if AI behavior is problematic
4. Monitor for 1-2 cycles before re-enabling

## Future Enhancements

Potential follow-ups:
1. **Dynamic risk limits** based on account balance changes
2. **Per-symbol risk limits** (e.g., max 10% of portfolio per symbol)
3. **Correlation-based position limits** (avoid correlated pairs)
4. **AI confidence calibration** (track accuracy vs reported confidence)
5. **A/B test prompt versions** (track performance by prompt_version)

## References

- Issue: [GitHub Issue Link]
- PR: [GitHub PR Link]
- Verification: [VERIFICATION_SECURITY_ENHANCEMENTS.md](./VERIFICATION_SECURITY_ENHANCEMENTS.md)
