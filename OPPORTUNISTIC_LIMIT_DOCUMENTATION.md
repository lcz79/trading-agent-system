# Opportunistic LIMIT Feature

## Overview

The **Opportunistic LIMIT** feature enables the Master AI agent to propose conservative LIMIT orders even when the main trading decision is HOLD. This allows the system to capture good opportunities at key price levels without encouraging overtrading or compromising safety.

## Use Case

**Scenario:** The Master AI determines that a setup is not strong enough for an immediate OPEN action (low confidence, insufficient confirmations, conflicting signals), but recognizes a valid opportunity at a specific price level (e.g., Fibonacci support, key resistance).

**Traditional behavior:** The system would return HOLD and do nothing.

**With Opportunistic LIMIT:** The system can propose a conservative LIMIT order that will only execute if price reaches the specified level within a short time window.

## Key Principles

1. **Conservative by Design**: Only proposed when there's a valid opportunity with good risk/reward
2. **LIMIT-only**: No fallback to MARKET orders
3. **Strict Gates**: Must pass 11 hard validation checks
4. **Risk-Managed**: Full risk-based sizing applied
5. **Time-Bound**: Orders expire quickly (60-300 seconds)
6. **One per Symbol**: Maximum 1 opportunistic LIMIT per symbol per cycle
7. **Backward Compatible**: Existing decisions without opportunistic_limit work unchanged

## Architecture

### 1. Master AI Agent (`agents/04_master_ai_agent/main.py`)

#### Decision Model
```python
class Decision(BaseModel):
    symbol: str
    action: Literal["OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE"]
    # ... standard fields ...
    
    # New: Opportunistic LIMIT (optional)
    opportunistic_limit: Optional[Dict[str, Any]] = None
```

#### Opportunistic LIMIT Structure
```python
{
    "side": "LONG" | "SHORT",           # Direction
    "entry_price": float,                # Specific entry price (required)
    "entry_expires_sec": int,            # TTL in seconds (60-300)
    "tp_pct": float,                     # Take profit % (>= 0.010)
    "sl_pct": float,                     # Stop loss % (within bounds)
    "rr": float,                         # Risk/Reward ratio (>= 1.5)
    "edge_score": int,                   # Confidence in opportunity (0-100)
    "reasoning_bullets": List[str]       # Why this is a good opportunity
}
```

#### Validation Function
```python
def validate_opportunistic_limit(
    opportunistic_limit: Optional[Dict[str, Any]],
    action: str,
    blocked_by: List[str],
    symbol: str,
    current_price: float,
    volatility_pct: float
) -> dict:
    """
    Validates opportunistic_limit with 11 hard gates:
    1. Action must be HOLD
    2. No hard blockers active
    3. RR >= 1.5
    4. tp_pct >= 0.010 (1% minimum)
    5. sl_pct within safe bounds
    6. entry_expires_sec between 60-300
    7. entry_price within 0.8% of current price
    8. Volatility above minimum
    9. Required fields present and valid
    10. Risk-based sizing applicable
    11. Conservative leverage enforceable
    """
```

### 2. Orchestrator (`agents/orchestrator/main.py`)

The orchestrator detects HOLD decisions with `opportunistic_limit` and maps them to position manager LIMIT orders:

```python
if action == "HOLD":
    opportunistic_limit = d.get('opportunistic_limit')
    if opportunistic_limit:
        # Extract parameters
        opp_side = opportunistic_limit.get('side')
        opp_entry_price = opportunistic_limit.get('entry_price')
        # ... etc ...
        
        # Map to OPEN_LONG/OPEN_SHORT action
        opp_action = "OPEN_LONG" if opp_side == "LONG" else "OPEN_SHORT"
        
        # Build position manager payload
        payload = {
            "symbol": sym,
            "side": opp_action,
            "entry_type": "LIMIT",
            "entry_price": opp_entry_price,
            "entry_ttl_sec": opp_entry_expires_sec,
            "features": {
                "opportunistic": True,
                "original_action": "HOLD"
            }
        }
        
        # Execute via position manager
        await c.post(f"{URLS['pos']}/open_position", json=payload)
```

### 3. Dashboard (`dashboard/components/ai_reasoning.py`)

The dashboard displays opportunistic LIMIT details with visual indicators:

```python
if opportunistic_limit:
    # Show:
    # - Side (LONG/SHORT) with color coding
    # - Entry price and distance from current
    # - RR, TP, SL percentages
    # - Edge score
    # - Gate pass/fail status
    # - Reasoning bullets
```

## Example Flow

### Step 1: Market Analysis
```
Symbol: ETHUSDT
Current Price: 3510 USDT
Regime: RANGE
RSI 15m: 48 (neutral)
Fibonacci 0.618 support: 3500 USDT (0.28% away)
```

### Step 2: Master AI Decision
```json
{
  "symbol": "ETHUSDT",
  "action": "HOLD",
  "confidence": 58,
  "rationale": "Main setup insufficient, but valid support test opportunity",
  "blocked_by": [],
  "soft_blockers": ["LOW_CONFIDENCE"],
  
  "opportunistic_limit": {
    "side": "LONG",
    "entry_price": 3500.0,
    "entry_expires_sec": 180,
    "tp_pct": 0.015,
    "sl_pct": 0.010,
    "rr": 1.5,
    "edge_score": 74,
    "reasoning_bullets": [
      "Price at Fib 0.618 support",
      "Volume spike near support",
      "1h trend neutral",
      "Support held 3x in 24h"
    ]
  }
}
```

### Step 3: Gate Validation
```
✅ Action is HOLD
✅ No hard blockers present
✅ RR 1.5 >= 1.5
✅ TP 1.5% >= 1.0%
✅ SL 1.0% within bounds
✅ Expires 180s within [60, 300]
✅ Entry price 0.28% from current (< 0.8%)
✅ Volatility sufficient
✅ Risk-based sizing applied
✅ Conservative leverage (3.5x)

🎉 ALL GATES PASSED
```

### Step 4: Order Execution
```
LIMIT order placed:
- Entry: 3500 USDT
- TP: 3552.5 USDT (+1.5%)
- SL: 3465.0 USDT (-1.0%)
- Leverage: 3.5x
- Expires: 180 seconds
- Marked: opportunistic=true
```

## Safety Gates

### Gate 1: Action Check
- **Rule**: Opportunistic LIMIT only allowed when `action == "HOLD"`
- **Rationale**: Prevents double-opening when AI already wants OPEN_LONG/OPEN_SHORT

### Gate 2: Hard Blockers
- **Rule**: No hard blockers present in `blocked_by`
- **Rationale**: Respects critical system constraints (margin, crash guard, etc.)
- **Hard Blockers**: INSUFFICIENT_MARGIN, CRASH_GUARD, LOW_VOLATILITY, COOLDOWN, MAX_POSITIONS, etc.

### Gate 3: Risk/Reward Ratio
- **Rule**: `rr >= 1.5`
- **Rationale**: Ensures favorable risk/reward; minimum 1.5:1 for conservative trading

### Gate 4: Take Profit
- **Rule**: `tp_pct >= 0.010` (1% minimum)
- **Rationale**: Ensures meaningful profit target; avoids noise trading

### Gate 5: Stop Loss
- **Rule**: `MIN_SL_DISTANCE_PCT <= sl_pct <= MAX_SL_DISTANCE_PCT`
- **Rationale**: Prevents too-tight stops (noise) and too-wide stops (excessive risk)
- **Default Bounds**: [0.25%, 2.5%]

### Gate 6: Order Expiry
- **Rule**: `60 <= entry_expires_sec <= 300`
- **Rationale**: Time-bound opportunities; not too short (miss fills) or too long (stale setup)

### Gate 7: Entry Price Distance
- **Rule**: `|entry_price - current_price| / current_price <= 0.008` (0.8%)
- **Rationale**: Entry must be near current price; prevents unrealistic limit prices

### Gate 8: Volatility Check
- **Rule**: `volatility_pct >= 0.0010`
- **Rationale**: Requires minimum volatility for meaningful trading opportunity

### Gate 9: Field Validation
- **Rule**: All required fields present and valid types
- **Required**: side, entry_price, entry_expires_sec, tp_pct, sl_pct, rr

### Gate 10: Risk-Based Sizing
- **Rule**: Standard risk-based sizing must be computable
- **Rationale**: Ensures position size aligns with risk management rules

### Gate 11: Position Checks
- **Rule**: Symbol must not have existing open position
- **Rationale**: Respects one-position-per-symbol constraint

## Configuration

### Environment Variables

```bash
# General risk parameters (inherited)
MIN_SL_DISTANCE_PCT=0.0025         # 0.25%
MAX_SL_DISTANCE_PCT=0.025          # 2.5%
MAX_LOSS_USDT_PER_TRADE=0.35       # Max loss per trade
MAX_NOTIONAL_USDT=50.0             # Max notional size

# Opportunistic LIMIT has these constraints hardcoded:
# - RR >= 1.5
# - tp_pct >= 0.010 (1%)
# - entry_expires_sec: 60-300 seconds
# - entry_price distance: <= 0.8%
# - leverage: 3-4x (conservative)
```

## Testing

### Run Test Suite
```bash
python test_opportunistic_limit.py
```

### Test Coverage
- ✅ Valid opportunistic LIMIT acceptance
- ✅ Invalid RR rejection (< 1.5)
- ✅ Invalid TP rejection (< 1%)
- ✅ Invalid action rejection (not HOLD)
- ✅ Hard blockers rejection
- ✅ Orchestrator mapping validation
- ✅ Backward compatibility
- ✅ Entry price distance check
- ✅ Entry expires bounds check

### Run Demo
```bash
python demo_opportunistic_limit.py
```

## Logging & Telemetry

### AI Decisions Log (`/data/ai_decisions.json`)
```json
{
  "timestamp": "2024-01-20T10:30:00",
  "symbol": "ETHUSDT",
  "action": "HOLD",
  "confidence": 58,
  "rationale": "...",
  
  "opportunistic_limit": {
    "side": "LONG",
    "entry_price": 3500.0,
    "tp_pct": 0.015,
    "sl_pct": 0.010,
    "rr": 1.5,
    "edge_score": 74,
    "leverage": 3.5,
    "size_pct": 0.092
  },
  
  "opportunistic_gate": {
    "passed": true,
    "reasons": []
  }
}
```

### Position Manager Features
```json
{
  "symbol": "ETHUSDT",
  "side": "OPEN_LONG",
  "entry_type": "LIMIT",
  "features": {
    "opportunistic": true,
    "rr": 1.5,
    "edge_score": 74,
    "reasoning": ["..."],
    "original_action": "HOLD"
  }
}
```

## Dashboard Display

The dashboard shows opportunistic LIMIT orders with:
- 🎯 Opportunistic LIMIT badge
- Side with color coding (green=LONG, red=SHORT)
- Entry price and distance from current
- RR, TP, SL percentages
- Edge score
- Gate pass/fail status with emoji indicators
- Reasoning bullets (first 3)

## Best Practices

### When to Use Opportunistic LIMIT

✅ **Good Use Cases:**
- Price near key Fibonacci levels
- Price testing major support/resistance
- RANGE regime with clear S/R levels
- RSI approaching oversold/overbought
- Volume confirming level importance
- Multiple timeframe alignment (no opposition)

❌ **Avoid When:**
- Hard blockers active
- Volatility too low (chop)
- Price far from key levels
- Crash guard active
- Insufficient margin
- Symbol already has position

### Prompt Engineering

The Master AI prompt includes detailed guidelines:
```
## Opportunistic LIMIT (Conservative Mode for HOLD)
When your main action is HOLD, you MAY propose an opportunistic_limit:
- Only if you see a valid opportunity with good risk/reward
- RR must be >= 1.5
- tp_pct must be >= 0.010 (1% minimum)
- entry_price within 0.8% of current
- Do NOT propose if blocked_by contains hard blockers
```

## Future Enhancements

### Potential Improvements
1. **Additional Indicators** (optional, not critical):
   - Bollinger Bands (20,2)
   - VWAP (session/day)
   - Volume Z-score

2. **Dynamic Thresholds**:
   - RR threshold based on market regime
   - TP/SL bounds adjusted for volatility

3. **Multiple Opportunities**:
   - Allow 2-3 opportunistic orders per cycle (different symbols)
   - Coordinate across portfolio

4. **Learning Integration**:
   - Track opportunistic order performance
   - Adjust edge_score thresholds based on results

## Troubleshooting

### Opportunistic LIMIT Not Appearing

**Check:**
1. Is main action HOLD? (required)
2. Are hard blockers present? (blocks opportunistic)
3. Is volatility sufficient? (>= 0.0010)
4. Is entry price too far? (must be <= 0.8%)
5. Is RR >= 1.5? (required)
6. Is TP >= 1%? (required)

### Gate Failures

View `/data/ai_decisions.json` for `opportunistic_gate` field:
```json
{
  "opportunistic_gate": {
    "passed": false,
    "reasons": [
      "RR 1.2 < 1.5 (minimum)",
      "tp_pct 0.008 < 0.010 (1% minimum)"
    ]
  }
}
```

### Orders Not Executing

**Check orchestrator logs:**
- Symbol already has open position?
- Position checks failing?
- Position manager rejecting order?

## Conclusion

The Opportunistic LIMIT feature enables conservative, opportunistic trading while maintaining all safety guardrails. It captures good opportunities at key price levels without encouraging overtrading, using LIMIT-only execution with strict validation gates and full risk management integration.

---

**Version:** 1.0  
**Last Updated:** 2024-01-20  
**Author:** Trading Agent System Team
