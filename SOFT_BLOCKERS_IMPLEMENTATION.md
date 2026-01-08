# Soft Blockers Implementation (Option 2)

## Overview

This document describes the implementation of **Option 2: Soft Blockers** in the trading bot's decision-making system. The implementation separates HARD constraints (which must block trades) from SOFT warnings (which provide context but don't force HOLD).

## Problem Statement

Previously, the system treated all `blocked_by` reasons equally, forcing the AI to output HOLD whenever ANY reason was present. This prevented the AI from reasoning freely about trade opportunities even when constraints were soft or could be overridden with sufficient confirmation.

## Solution

We introduced a clear separation between:
- **HARD constraints** (`blocked_by`) - Must force HOLD
- **SOFT warnings** (`soft_blockers`) - Provide context but allow OPEN with justification

## Changes Made

### 1. Schema Updates (`agents/04_master_ai_agent/main.py`)

#### New Types
```python
# HARD constraints that ALWAYS block OPEN actions
HARD_BLOCKER_REASONS = Literal[
    "INSUFFICIENT_MARGIN",
    "MAX_POSITIONS",
    "COOLDOWN",
    "DRAWDOWN_GUARD",
    "CRASH_GUARD",
    "LOW_PRE_SCORE",
    "LOW_RANGE_SCORE",
    "MOMENTUM_UP_15M",
    "MOMENTUM_DOWN_15M",
    "LOW_VOLATILITY",
    ""
]

# SOFT constraints that are warnings/flags but don't force HOLD
SOFT_BLOCKER_REASONS = Literal[
    "LOW_CONFIDENCE",
    "CONFLICTING_SIGNALS",
    ""
]
```

#### Decision Model
```python
class Decision(BaseModel):
    # ... existing fields ...
    blocked_by: Optional[List[HARD_BLOCKER_REASONS]] = None  # HARD constraints only
    soft_blockers: Optional[List[SOFT_BLOCKER_REASONS]] = None  # SOFT warnings/flags
```

### 2. Enforcement Logic (`enforce_decision_consistency`)

The function now:
1. **Migrates** legacy soft reasons from `blocked_by` to `soft_blockers` for backward compatibility
2. **Infers** soft blockers (LOW_CONFIDENCE, CONFLICTING_SIGNALS) when appropriate
3. **Only forces HOLD** when HARD blockers exist in `blocked_by`
4. **Allows OPEN** even when soft blockers are present

### 3. SYSTEM_PROMPT Updates

Updated the prompt to clearly explain:
- Which constraints are HARD (go in `blocked_by`)
- Which constraints are SOFT (go in `soft_blockers`)
- How the AI can override SOFT constraints with proper justification
- JSON output format including both fields

Example from prompt:
```json
{
  "symbol": "ETHUSDT",
  "action": "OPEN_SHORT",
  "blocked_by": [],  // Empty - no HARD blockers
  "soft_blockers": ["LOW_CONFIDENCE"],  // SOFT warning present
  "rationale": "Setup SHORT scalping: 4 strong confirmations justify entry despite confidence 55%..."
}
```

### 4. Downstream Logic

All hard constraint checks now properly populate `blocked_by`:
- ✅ Insufficient margin check
- ✅ Crash guard
- ✅ Momentum guard (SOL airbag)
- ✅ Volatility filter
- ✅ Pre-score/range-score guardrail

Soft constraints are inferred by `enforce_decision_consistency`:
- ✅ LOW_CONFIDENCE (when confidence < 50%)
- ✅ CONFLICTING_SIGNALS (when < 2 confirmations)

## Constraint Classification

### HARD Constraints (Block OPEN)

These constraints **must** prevent opening new positions:

| Constraint | Reason | Enforcement |
|------------|--------|-------------|
| INSUFFICIENT_MARGIN | Margine < 10 USDT | System safety |
| MAX_POSITIONS | Max positions reached | Risk management |
| COOLDOWN | Recent close same direction | Prevent revenge trading |
| DRAWDOWN_GUARD | Drawdown < -10% | Portfolio protection |
| CRASH_GUARD | Rapid price movement | Avoid knife catching |
| LOW_PRE_SCORE + LOW_RANGE_SCORE | Both scores below threshold AND < 3 confirmations | Setup quality |
| MOMENTUM_UP_15M / MOMENTUM_DOWN_15M | SOL contrarian filter | Prevent churn |
| LOW_VOLATILITY | ATR/price too low | Avoid chop |

### SOFT Constraints (Warnings Only)

These constraints are **warnings** that the AI can override with sufficient justification:

| Constraint | When Present | Override Condition |
|------------|--------------|-------------------|
| LOW_CONFIDENCE | Confidence < 50% | ≥3 strong confirmations + rationale |
| CONFLICTING_SIGNALS | Mixed indicators | Dominant signal identified |

## Backward Compatibility

### Migration Strategy

When legacy decisions have soft reasons in `blocked_by`:
```python
# Before (legacy)
{
  "blocked_by": ["LOW_CONFIDENCE", "INSUFFICIENT_MARGIN"],
  "soft_blockers": None
}

# After (migrated)
{
  "blocked_by": ["INSUFFICIENT_MARGIN"],  # Only HARD
  "soft_blockers": ["LOW_CONFIDENCE"]     # Soft migrated
}
```

### Reading Old Decisions

- Old decisions without `soft_blockers` field continue to work
- `enforce_decision_consistency` fills in missing fields
- Dashboard reads both `blocked_by` and `soft_blockers`

## Testing

### Test Coverage

Created comprehensive test suite in `test_soft_blockers.py`:

1. ✅ **HARD blocker forces HOLD** - Validates INSUFFICIENT_MARGIN blocks OPEN
2. ✅ **SOFT blocker allows OPEN** - Validates LOW_CONFIDENCE doesn't block
3. ✅ **Backward compatibility** - Validates migration from old format
4. ✅ **Mixed HARD/SOFT** - Validates handling of both together
5. ✅ **Decision model** - Validates new field in Pydantic model
6. ✅ **Inference** - Validates soft blocker inference on HOLD

### Updated Existing Tests

- ✅ `test_acceptance_criteria.py` - Updated for new behavior
- ✅ `test_master_ai_refactor.py` - Updated for new behavior
- ✅ All tests passing (16/16)

## Usage Examples

### Example 1: Opening with SOFT blocker

```json
{
  "symbol": "ETHUSDT",
  "action": "OPEN_SHORT",
  "leverage": 4.0,
  "size_pct": 0.12,
  "confidence": 55,
  "blocked_by": [],
  "soft_blockers": ["LOW_CONFIDENCE"],
  "setup_confirmations": [
    "Resistance rejection",
    "RSI overbought",
    "Bearish momentum",
    "Volume increase"
  ],
  "rationale": "Moderate confidence but 4 strong confirmations justify entry. Opening SHORT with conservative size (12%) and tight stops.",
  "tp_pct": 0.02,
  "sl_pct": 0.015
}
```

**Result**: Position OPENS despite LOW_CONFIDENCE flag

### Example 2: Blocked by HARD constraint

```json
{
  "symbol": "BTCUSDT",
  "action": "HOLD",
  "leverage": 0,
  "size_pct": 0,
  "blocked_by": ["INSUFFICIENT_MARGIN"],
  "soft_blockers": [],
  "rationale": "Strong setup but insufficient margin (available=8.5 USDT, threshold=10.0). Wait for margin availability.",
  "confidence": 0
}
```

**Result**: Position is HELD due to INSUFFICIENT_MARGIN (HARD constraint)

### Example 3: HOLD due to lack of confirmations (SOFT)

```json
{
  "symbol": "SOLUSDT",
  "action": "HOLD",
  "leverage": 0,
  "size_pct": 0,
  "blocked_by": [],
  "soft_blockers": ["CONFLICTING_SIGNALS"],
  "rationale": "Mixed signals - RSI neutral, momentum weak, no clear support/resistance. Better to wait for clearer setup.",
  "confidence": 45
}
```

**Result**: Position is HELD voluntarily (no HARD blockers, AI chose HOLD)

## Orchestrator Integration

The orchestrator (`agents/orchestrator/main.py`) already correctly handles the new behavior:

```python
# Orchestrator only checks blocked_by (HARD constraints)
blocked_by = d.get("blocked_by") or []
if blocked_by:
    print(f"🧱 SKIP {action} on {sym}: blocked_by={blocked_by}")
    continue

# soft_blockers are not checked - AI decision is respected
```

This means:
- ✅ HARD blockers prevent execution
- ✅ SOFT blockers are logged but don't prevent execution
- ✅ AI has freedom to reason about trades

## Benefits

1. **AI Autonomy**: AI can reason freely about opportunities while respecting hard safety constraints
2. **Transparency**: Clear distinction between must-follow rules and advisory warnings
3. **Flexibility**: System can handle nuanced trading decisions (e.g., low confidence but strong confirmations)
4. **Safety**: Hard constraints remain strictly enforced
5. **Backward Compatible**: Existing code and decisions continue to work

## Acceptance Criteria Met

✅ Agent can output OPEN_LONG/OPEN_SHORT with `soft_blockers` present, without being coerced to HOLD

✅ Any hard constraint in `blocked_by` always coerces action to HOLD

✅ pre_score/range_score guardrail still blocks OPEN when both below thresholds (HARD constraint)

✅ `python -m compileall agents` succeeds

✅ All tests pass (16/16)

✅ Backward compatibility maintained

## Future Enhancements

Possible future improvements:
- Add dashboard visualization of soft vs hard blockers
- Track which soft blockers are most frequently overridden
- Learn optimal soft blocker thresholds from trading performance
- Add more granular soft blockers (e.g., "WEAK_VOLUME", "MINOR_DIVERGENCE")

## References

- Implementation PR: [Link to PR]
- Original Issue: Option 2 - Soft Blockers
- Test Suite: `test_soft_blockers.py`
- Main Implementation: `agents/04_master_ai_agent/main.py`
